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
