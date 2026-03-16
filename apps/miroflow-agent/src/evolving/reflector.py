# Copyright (c) 2025 MiroMind
# Self-Evolving: Reflector module
# Analyses completed task logs via LLM, generates structured experiences
# conforming to the Experience schema, and writes them to ExperienceStore.

import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any, List, Optional

if TYPE_CHECKING:
    from omegaconf import DictConfig

    from ..logging.task_logger import TaskLog
    from .experience_store import ExperienceStore

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Prompt
# ---------------------------------------------------------------------------

REFLECTION_PROMPT = """\
You are analyzing the execution trace of an AI prediction agent. The agent was given a prediction task and produced an answer. Your job is to reflect on why the agent succeeded or failed, and extract a reusable lesson.

## Task
Question: {question}
Agent's Answer: {agent_answer}
Ground Truth: {ground_truth}
Result: {result}

## Tools Detected in Trace
{tools_used_hint}

## Agent's Execution Trace (key steps)
{trace_summary}

## Instructions
Analyze the agent's strategy and produce a JSON object with ALL of the following fields:
- "question_type": categorize the question (e.g. "sports_event", "politics_election", "finance_market", "technology", "entertainment", "science", "geopolitics", "other")
- "level": the difficulty level (integer, 1-4)
- "question_summary": one-line summary of the question
- "search_strategy": what the agent searched for and how it reasoned
- "was_correct": true/false
- "failure_pattern": if incorrect, what went wrong (e.g. "outdated_info", "insufficient_search", "wrong_reasoning", "missed_options", "overconfident"). Set to null if correct.
- "lesson": a concrete, actionable lesson for future similar tasks. Keep it to 1-2 sentences.
- "reasoning_type": one of "numerical_computation", "logical_reasoning", "info_retrieval", "multi_step", "planning"
- "knowledge_domain": one of "finance", "sports", "geopolitics", "tech", "entertainment", "science", "other"
- "tools_used": list of tools the agent actually used, e.g. ["web_search", "code_execution", "solver", "browsing"]
- "strategy_name": short name for the overall strategy the agent adopted (e.g. "search_heavy", "code_compute", "multi_source_verify", "direct_reasoning")

Return ONLY the JSON object, no other text."""

# ---------------------------------------------------------------------------
# Multi-path comparison reflection prompt
# ---------------------------------------------------------------------------

MULTI_PATH_COMPARISON_PROMPT = """\
You are analyzing how multiple parallel agent paths performed on the SAME prediction task, each using a different search strategy. Your job is to compare the paths and extract lessons about which strategies work best for this type of question.

## Task
Question: {question}
Ground Truth: {ground_truth}

## Path Results
{path_summaries}

## Instructions
Analyze the differences between paths and produce a JSON object with ALL fields:
- "question_type": categorize the question (e.g. "sports_event", "finance_market", "politics_election", etc.)
- "question_summary": one-line summary of the question
- "knowledge_domain": one of "finance", "sports", "geopolitics", "tech", "entertainment", "science", "other"
- "winning_strategy": name of the strategy that produced the correct answer (or "none" if all failed)
- "losing_strategies": list of strategy names that failed
- "comparison_lesson": a concrete lesson about WHY the winning strategy worked and the losing ones didn't (2-3 sentences). If all failed, explain what all paths missed.
- "strategy_insights": dict mapping each strategy_name to a brief insight about its performance on this question
- "recommended_strategies": list of strategy names recommended for this question type (based on this comparison)
- "avoid_strategies": list of strategy names to avoid for this question type

Return ONLY the JSON object, no other text."""

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

_TOOL_TAG_MAP = {
    "[TOOL>": "tool_call",
    "[SEARCH]": "web_search",
    "[BROWSER]": "browsing",
    "[PY]": "code_execution",
}


def _extract_trace_summary(task_log: dict, max_steps: int = 15) -> str:
    """Extract a condensed trace from a task log.

    Uses the correct StepLog field names: step_logs / info_level / step_name / message.
    """
    steps = task_log.get("step_logs", [])
    if not steps:
        return "(no execution trace available)"

    summary_parts: list[str] = []
    step_count = 0
    for step in steps:
        if step_count >= max_steps:
            summary_parts.append(f"... ({len(steps) - max_steps} more steps omitted)")
            break
        level = step.get("info_level", "info")
        label = step.get("step_name", "")
        content = step.get("message", "")
        if len(content) > 300:
            content = content[:300] + "..."
        summary_parts.append(f"[{level}] {label}: {content}")
        step_count += 1

    return "\n".join(summary_parts)


def _extract_tools_used(task_log: dict) -> List[str]:
    """Scan step_logs for tool-use markers and return a deduplicated tool list."""
    tools_seen: dict[str, None] = {}
    for step in task_log.get("step_logs", []):
        name = step.get("step_name", "")
        for tag, tool_name in _TOOL_TAG_MAP.items():
            if tag in name:
                tools_seen[tool_name] = None
    return list(tools_seen.keys())


def _classify_question_level(task_log: dict) -> int:
    """Try to extract the level from the task log or default to 2."""
    return task_log.get("level", 2)


def _normalize(s: str) -> str:
    """Normalize answer string for comparison."""
    if not s:
        return ""
    s = s.strip().lower()
    s = re.sub(r"[\\{}\s]", "", s)
    return s


# ---------------------------------------------------------------------------
# Core reflection functions
# ---------------------------------------------------------------------------


async def reflect_on_task(
    task_log: dict,
    ground_truth: str,
    llm_client: Any,
    model: str = "",
    experience_store: Optional["ExperienceStore"] = None,
) -> Optional[dict]:
    """Reflect on a single task and produce an experience dict.

    Args:
        task_log: Task log dict (from TaskLog.to_json() deserialised).
        ground_truth: The expected correct answer.
        llm_client: Any OpenAI-compatible async client exposing
                     ``chat.completions.create()``.
        model: Model name for the reflection call.  Empty uses the client default.
        experience_store: If provided, the experience is written automatically.

    Returns:
        Experience dict, or ``None`` on failure.
    """
    inp = task_log.get("input", {})
    question = inp.get("task_description", "")
    agent_answer = task_log.get("final_boxed_answer", "")

    if not question or not ground_truth:
        return None

    is_correct = _normalize(agent_answer) == _normalize(ground_truth)
    result = "CORRECT" if is_correct else "INCORRECT"

    trace_summary = _extract_trace_summary(task_log)
    tools_used = _extract_tools_used(task_log)
    tools_used_hint = ", ".join(tools_used) if tools_used else "(none detected)"

    prompt = REFLECTION_PROMPT.format(
        question=question,
        agent_answer=agent_answer,
        ground_truth=ground_truth,
        result=result,
        trace_summary=trace_summary,
        tools_used_hint=tools_used_hint,
    )

    create_kwargs: dict[str, Any] = dict(
        messages=[{"role": "user", "content": prompt}],
        max_completion_tokens=1024,
        temperature=0.3,
    )
    if model:
        create_kwargs["model"] = model

    try:
        response = await llm_client.chat.completions.create(**create_kwargs)
        content = response.choices[0].message.content.strip()

        json_match = re.search(r"\{[\s\S]*\}", content)
        if json_match:
            experience = json.loads(json_match.group())
            experience["was_correct"] = is_correct
            experience["task_id"] = task_log.get("task_id", "")
            experience.setdefault("tools_used", tools_used)
            experience.setdefault("created_at", datetime.now(timezone.utc).isoformat())

            if experience_store is not None:
                experience_store.add(experience)

            return experience
    except Exception as e:
        logger.warning(f"Reflection failed for task {task_log.get('task_id', '?')}: {e}")

    return None


async def reflect_on_batch(
    log_dir: str,
    ground_truths: dict,
    experience_store: "ExperienceStore",
    llm_client: Any,
    model: str = "",
) -> List[dict]:
    """Reflect on all task logs in a directory.

    Args:
        log_dir: Directory containing task log JSON files.
        ground_truths: Mapping task_id -> ground_truth answer.
        experience_store: ExperienceStore instance for persisting results.
        llm_client: OpenAI-compatible async client.
        model: Model name (empty = client default).

    Returns:
        List of generated experience dicts.
    """
    log_path = Path(log_dir)
    log_files = list(log_path.glob("*.json"))
    logger.info(f"Found {len(log_files)} task logs in {log_dir}")

    experiences: List[dict] = []
    for log_file in log_files:
        try:
            with open(log_file, "r", encoding="utf-8") as f:
                task_log = json.load(f)
        except Exception as e:
            logger.warning(f"Failed to read {log_file}: {e}")
            continue

        task_id = task_log.get("task_id", "")
        gt = ground_truths.get(task_id)
        if gt is None:
            logger.debug(f"No ground truth for task {task_id}, skipping")
            continue

        experience = await reflect_on_task(
            task_log, gt, llm_client, model, experience_store=experience_store,
        )
        if experience:
            experiences.append(experience)
            logger.info(
                f"Reflected on {task_id}: "
                f"{'correct' if experience['was_correct'] else 'incorrect'}"
            )

    correct = sum(1 for e in experiences if e["was_correct"])
    logger.info(
        f"Reflection done: {len(experiences)} tasks reflected, {correct} correct, "
        f"{len(experiences) - correct} incorrect."
    )
    return experiences


# ---------------------------------------------------------------------------
# Pipeline auto-trigger entry point
# ---------------------------------------------------------------------------


async def auto_reflect_after_task(
    task_log: "TaskLog",
    cfg: "DictConfig",
    experience_store: "ExperienceStore",
) -> None:
    """Called by pipeline.py after task completion.

    Only runs when ``evolving.enabled`` and ``evolving.auto_reflect`` are true
    and ``task_log.ground_truth`` is present.  Exceptions are caught internally
    so as never to disrupt the main pipeline.
    """
    try:
        evolving_cfg = cfg.get("evolving", {})
        if not evolving_cfg.get("auto_reflect", True):
            return
        if not task_log.ground_truth:
            return

        from openai import AsyncOpenAI

        api_key = cfg.llm.get("api_key", "")
        base_url = cfg.llm.get("base_url", "")
        model = evolving_cfg.get("reflection_model", "") or cfg.llm.get("model_name", "")

        llm_client = AsyncOpenAI(api_key=api_key, base_url=base_url)

        task_log_dict = json.loads(task_log.to_json())

        await reflect_on_task(
            task_log_dict,
            str(task_log.ground_truth),
            llm_client,
            model=model,
            experience_store=experience_store,
        )
    except Exception as e:
        logger.warning(f"auto_reflect_after_task failed: {e}")


# ---------------------------------------------------------------------------
# Multi-path reflection
# ---------------------------------------------------------------------------


async def reflect_on_multi_path(
    path_results: list,
    task_description: str,
    ground_truth: str,
    llm_client: Any,
    model: str = "",
    experience_store: Optional["ExperienceStore"] = None,
) -> list:
    """Reflect on all paths of a multi-path execution.

    1. Reflects on each path individually (reuses reflect_on_task)
    2. Generates a cross-path comparison experience

    Args:
        path_results: List of tuples (summary, answer, log_path, strategy_name, metadata)
                      as returned by execute_multi_path_pipeline's internal results.
        task_description: The original question.
        ground_truth: Expected correct answer.
        llm_client: OpenAI-compatible async client.
        model: Model name (empty = client default).
        experience_store: If provided, experiences are written automatically.

    Returns:
        List of generated experience dicts (individual + comparison).
    """
    experiences = []

    # --- Step 1: Reflect on each path individually ---
    for i, result in enumerate(path_results):
        if result is None or len(result) < 5:
            continue

        summary, answer, log_path, strategy_name, metadata = result
        status = metadata.get("status", "unknown") if isinstance(metadata, dict) else "unknown"

        if not log_path or status == "cancelled":
            continue

        # Load the path's TaskLog
        try:
            with open(log_path, "r", encoding="utf-8") as f:
                task_log_dict = json.load(f)
        except Exception as e:
            logger.warning(f"Could not load log for path {i} ({strategy_name}): {e}")
            continue

        exp = await reflect_on_task(
            task_log_dict,
            ground_truth,
            llm_client,
            model=model,
            experience_store=None,  # Don't write yet, we'll add strategy_name first
        )

        if exp:
            # Ensure strategy_name is correctly set from the multi-path metadata
            exp["strategy_name"] = strategy_name
            exp["task_id"] = f"{exp.get('task_id', '')}"  # Keep path-specific task_id

            if experience_store is not None:
                experience_store.add(exp)

            experiences.append(exp)

    # --- Step 2: Cross-path comparison reflection ---
    if len(path_results) >= 2 and ground_truth:
        comparison_exp = await _reflect_comparison(
            path_results=path_results,
            task_description=task_description,
            ground_truth=ground_truth,
            llm_client=llm_client,
            model=model,
        )
        if comparison_exp and experience_store is not None:
            experience_store.add(comparison_exp)
            experiences.append(comparison_exp)

    return experiences


async def _reflect_comparison(
    path_results: list,
    task_description: str,
    ground_truth: str,
    llm_client: Any,
    model: str = "",
) -> Optional[dict]:
    """Generate a cross-path comparison experience."""

    # Build path summaries text
    path_lines = []
    for i, result in enumerate(path_results):
        if result is None or len(result) < 5:
            continue
        summary, answer, log_path, strategy_name, metadata = result
        status = metadata.get("status", "unknown") if isinstance(metadata, dict) else "unknown"

        is_correct = _normalize(answer) == _normalize(ground_truth) if answer else False
        result_str = "CORRECT" if is_correct else "INCORRECT"

        path_lines.append(
            f"### Path {i}: {strategy_name}\n"
            f"- Status: {status}\n"
            f"- Answer: {answer[:200] if answer else '(empty)'}\n"
            f"- Result: {result_str}\n"
            f"- Duration: {metadata.get('elapsed_seconds', '?')}s\n"
            f"- Turns: {metadata.get('turns', '?')}"
        )

    if len(path_lines) < 2:
        return None

    prompt = MULTI_PATH_COMPARISON_PROMPT.format(
        question=task_description[:2000],
        ground_truth=ground_truth,
        path_summaries="\n\n".join(path_lines),
    )

    create_kwargs: dict[str, Any] = dict(
        messages=[{"role": "user", "content": prompt}],
        max_completion_tokens=1024,
        temperature=0.3,
    )
    if model:
        create_kwargs["model"] = model

    try:
        response = await llm_client.chat.completions.create(**create_kwargs)
        content = response.choices[0].message.content.strip()

        json_match = re.search(r"\{[\s\S]*\}", content)
        if json_match:
            comparison = json.loads(json_match.group())
            # Create a comparison experience record
            comparison["task_id"] = f"comparison_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"
            comparison["was_correct"] = bool(comparison.get("winning_strategy") and comparison["winning_strategy"] != "none")
            comparison["lesson"] = comparison.get("comparison_lesson", "")
            comparison["failure_pattern"] = "multi_path_comparison"
            comparison["strategy_name"] = comparison.get("winning_strategy", "none")
            comparison["tools_used"] = ["multi_path"]
            comparison["reasoning_type"] = "multi_step"
            comparison["level"] = 2
            comparison["created_at"] = datetime.now(timezone.utc).isoformat()
            comparison["search_strategy"] = f"multi-path comparison: {', '.join(comparison.get('recommended_strategies', []))}"
            return comparison
    except Exception as e:
        logger.warning(f"Multi-path comparison reflection failed: {e}")

    return None


async def auto_reflect_multi_path(
    path_results: list,
    task_description: str,
    ground_truth: str,
    cfg: "DictConfig",
    experience_store: "ExperienceStore",
) -> None:
    """Called by multi_path.py after task completion.

    Only runs when ``evolving.enabled`` and ``evolving.auto_reflect`` are true
    and ground_truth is present. Exceptions are caught internally.
    """
    try:
        import os as _os

        evolving_cfg = cfg.get("evolving", {})
        if not evolving_cfg.get("enabled", False):
            return
        if not evolving_cfg.get("auto_reflect", True):
            return
        if not ground_truth:
            return

        from openai import AsyncOpenAI

        # Read from env to avoid Hydra interpolation issues
        try:
            api_key = cfg.llm.get("api_key", "")
        except Exception:
            api_key = _os.environ.get("ANTHROPIC_API_KEY", "")
        try:
            base_url = cfg.llm.get("base_url", "")
        except Exception:
            base_url = _os.environ.get("ANTHROPIC_BASE_URL", "https://api.anthropic.com")
        try:
            model = evolving_cfg.get("reflection_model", "") or cfg.llm.get("model_name", "")
        except Exception:
            model = evolving_cfg.get("reflection_model", "") or "claude-sonnet-4-20250514"

        llm_client = AsyncOpenAI(api_key=api_key, base_url=base_url)

        await reflect_on_multi_path(
            path_results=path_results,
            task_description=task_description,
            ground_truth=ground_truth,
            llm_client=llm_client,
            model=model,
            experience_store=experience_store,
        )

        # Aggregate strategy preferences after new experiences
        from .strategy_evolver import StrategyEvolver
        prefs_file = evolving_cfg.get("strategy_preferences_file", "")
        overrides_file = evolving_cfg.get("prompt_overrides_file", "")
        if prefs_file or overrides_file:
            evolver = StrategyEvolver(experience_store, prefs_file, overrides_file)
            evolver.aggregate_strategy_preferences()

    except Exception as e:
        logger.warning(f"auto_reflect_multi_path failed: {e}")


# ---------------------------------------------------------------------------
# Legacy helpers (kept for backward compatibility)
# ---------------------------------------------------------------------------


def load_experiences(
    experience_file: str,
    question_type: Optional[str] = None,
    level: Optional[int] = None,
    max_count: int = 5,
    only_failures: bool = False,
) -> list[dict]:
    """Load experiences from file, optionally filtered.

    .. deprecated::
        Prefer ``ExperienceStore.query()`` instead.
    """
    path = Path(experience_file)
    if not path.exists():
        return []

    experiences: list[dict] = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                exp = json.loads(line)
                experiences.append(exp)
            except json.JSONDecodeError:
                continue

    if only_failures:
        experiences = [e for e in experiences if not e.get("was_correct", True)]
    if question_type:
        experiences = [
            e for e in experiences
            if question_type.lower() in e.get("question_type", "").lower()
        ]
    if level is not None:
        experiences = [e for e in experiences if e.get("level") == level]

    return experiences[-max_count:]


def format_experiences_for_prompt(experiences: list[dict]) -> str:
    """Format experiences for system prompt injection.

    .. deprecated::
        Prefer ``ExperienceStore.format_for_prompt()`` instead.
    """
    if not experiences:
        return ""

    lines = ["\n# Lessons from Past Predictions\n"]
    for exp in experiences:
        lesson = exp.get("lesson", "")
        q_summary = exp.get("question_summary", "")
        failure = exp.get("failure_pattern", "")

        if exp.get("was_correct"):
            lines.append(f"- [OK] {q_summary}: {lesson}")
        else:
            lines.append(f"- [FAIL] {q_summary} (error: {failure}): {lesson}")

    lines.append("")
    return "\n".join(lines)
