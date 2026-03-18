# Copyright (c) 2025 MiroMind
# Multi-Path Exploration Layer (EvoAgent - Layer 1)
#
# EA-001: Multi-path scheduler — runs N parallel agent paths on the same task
# EA-002: Strategy variant definitions — pluggable strategy templates (see STRATEGY_VARIANTS)
# EA-003: LLM voting — LLM Judge selects best answer when paths disagree (see _vote_best_answer)
# EA-004: Majority vote fast path — skip LLM Judge when paths agree (see _vote_best_answer)
# EA-005: Independent ToolManagers — each path owns its own ToolManager (see execute_multi_path_pipeline)
# EA-006: Path-level log isolation — each path generates independent TaskLog (see _run_single_path)
# EA-007: Master log aggregation — scheduler aggregates all path results (see execute_multi_path_pipeline)
# EA-008: Dynamic path count — NUM_PATHS env var / config controls parallelism
#
# Runs N parallel agent paths with different search strategies on the same task,
# then selects the best answer via cross-validation voting.

import asyncio
import copy
import logging
import os
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from miroflow_tools.manager import ToolManager
from omegaconf import DictConfig, OmegaConf

from ..config.settings import create_mcp_server_parameters, get_env_info
from ..io.output_formatter import OutputFormatter
from ..llm.factory import ClientFactory
from ..logging.task_logger import TaskLog, get_utc_plus_8_time

# EA-304: Cost Tracker
from .cost_tracker import CostTracker, format_cost_report

# EA-307: OpenViking Context
from .openviking_context import OpenVikingContext, Discovery

# EA-011: Streaming
from .streaming import (
    get_stream_manager, 
    StreamEventType,
    ConsoleStreamConsumer,
    FileStreamConsumer,
)

# EA-012: Retry logic
RETRYABLE_ERROR_PATTERNS = [
    "rate_limit", "rate limit", "429", "timeout", "timed out",
    "connection", "ConnectionError", "httpx", "API error",
    "Service Unavailable", "503", "502", "504",
    "internal error", "InternalServerError", "quota",
]
FALLBACK_STRATEGIES = ["breadth_first", "lateral_thinking"]
MAX_RETRIES = 2

def _is_retryable_error(error: str) -> bool:
    """Check if an error is retryable"""
    error_lower = error.lower()
    for pattern in RETRYABLE_ERROR_PATTERNS:
        if pattern.lower() in error_lower:
            return True
    return False

def _get_fallback_strategy(original_strategy: str):
    """Get a fallback strategy different from the original"""
    for fallback in FALLBACK_STRATEGIES:
        if fallback != original_strategy:
            for s in STRATEGY_VARIANTS:
                if s["name"] == fallback:
                    return s
    return None

logger = logging.getLogger(__name__)


def _check_consensus(
    results: List[Tuple],
    early_stop_k: int,
    early_stop_threshold: float,
) -> Tuple[bool, Optional[str]]:
    """
    Check if consensus has been reached among completed paths.
    
    Returns:
        (has_consensus, consensus_answer) if consensus reached
        (False, None) if no consensus yet
    """
    # Filter valid results (successful and non-empty) - handle None results
    valid_results = [
        r for r in results
        if r is not None and len(r) > 4 and r[4].get("status") == "success" and r[1].strip()
    ]
    
    if len(valid_results) < early_stop_k:
        return False, None
    
    # Count answer frequencies (normalized)
    answers = [r[1].strip().lower() for r in valid_results]
    from collections import Counter
    answer_counts = Counter(answers)
    
    most_common_answer, most_common_count = answer_counts.most_common(1)[0]
    agreement_ratio = most_common_count / len(valid_results)
    
    # Check if we have enough agreements
    # Logic: if K or more paths agree (regardless of total ratio), stop early
    # The threshold is used to require minimum agreement among the top answers
    if most_common_count >= early_stop_k:
        # When early_stop_threshold < 1.0, use it; otherwise require full agreement
        if early_stop_threshold >= 1.0:
            # For threshold=1.0, require that all valid results agree
            if agreement_ratio >= 1.0:
                return True, valid_results[0][1]
        else:
            # For threshold < 1.0, use it (e.g., 0.66 means 2/3 agreement)
            if agreement_ratio >= early_stop_threshold:
                return True, valid_results[0][1]
    
    return False, None


async def _run_with_early_stopping(
    tasks: List,
    strategies: List[Dict],
    early_stop_k: int,
    early_stop_threshold: float,
    master_log,
    log_dir: str,
    task_id: str = "",
) -> List:
    """
    Run tasks with early stopping: cancel remaining tasks when consensus is reached.
    
    EA-009: Early Stopping Mechanism
    """
    results = [None] * len(tasks)
    pending = set(range(len(tasks)))
    completed_count = 0
    
    # Create asyncio Task objects
    async_tasks = [asyncio.create_task(t) for t in tasks]
    
    while pending:
        # Wait for any task to complete — only pass pending tasks
        pending_tasks = [async_tasks[i] for i in pending]
        done, still_pending = await asyncio.wait(
            pending_tasks,
            return_when=asyncio.FIRST_COMPLETED
        )
        
        # Process completed tasks
        for task in done:
            idx = async_tasks.index(task)
            completed_count += 1
            
            try:
                result = task.result()
                results[idx] = result
            except Exception as e:
                # Convert exception to failed result
                results[idx] = (
                    f"Path {idx} exception: {str(e)}",
                    "",
                    "",
                    strategies[idx]["name"],
                    {"strategy": strategies[idx]["name"], "status": "failed", "error": str(e)},
                )
            
            pending.discard(idx)
            
            # Log completion
            r = results[idx]
            master_log.log_step(
                "info",
                f"MultiPath | Path {idx} Complete",
                f"Strategy: {r[3]} | Status: {r[4].get('status')} | "
                f"Answer: {r[1][:100] if r[1] else '(empty)'} | "
                f"Completed: {completed_count}/{len(tasks)}",
            )
            
            # Check for early stopping consensus
            if len(pending) > 0:  # Only check if there are remaining tasks
                has_consensus, consensus_answer = _check_consensus(
                    results, early_stop_k, early_stop_threshold
                )
                
                if has_consensus:
                    master_log.log_step(
                        "info",
                        "MultiPath | Early Stopping",
                        f"Consensus reached: {early_stop_k}+ paths agree on answer. "
                        f"Cancelling {len(pending)} remaining paths.",
                    )
                    
                    # EA-011: Stream consensus reached
                    from .streaming import get_stream_manager, StreamEvent, StreamEventType
                    stream_mgr = get_stream_manager()
                    consensus_event = StreamEvent(
                        event_type=StreamEventType.CONSENSUS,
                        path_id=task_id,
                        content=f"Early stopping: consensus reached ({early_stop_k}+ paths agree)",
                        metadata={"answer": consensus_answer[:200] if consensus_answer else ""},
                    )
                    await stream_mgr.broadcast(consensus_event)
                    
                    # Cancel all remaining tasks
                    for remaining_idx in pending:
                        async_tasks[remaining_idx].cancel()
                    
                    # Wait for cancellation to complete
                    await asyncio.gather(*[async_tasks[i] for i in pending], 
                                         return_exceptions=True)
                    
                    # Fill in remaining results as cancelled
                    for remaining_idx in pending:
                        results[remaining_idx] = (
                            f"Path {remaining_idx} cancelled (early stopping)",
                            "",
                            "",
                            strategies[remaining_idx]["name"],
                            {"strategy": strategies[remaining_idx]["name"], 
                             "status": "cancelled", 
                             "reason": "early_stopping"},
                        )
                    
                    break
        
        # Update pending set after potential cancellations
        pending = {i for i in range(len(async_tasks)) 
                   if not async_tasks[i].done() and i in pending}
        
        if not pending:
            break
    
    return results


# EA-002: Strategy variant definitions
# Each strategy is a pluggable template with name, description, prompt_suffix.
# EA-010: Each strategy also has a max_turns budget for path-level cost control.
STRATEGY_VARIANTS = [
    {
        "name": "breadth_first",
        "description": "Broad search strategy",
        "max_turns": 100,  # Fewer turns - wide but shallow
        "prompt_suffix": (
            "\n\n[Strategy: Breadth-First Exploration]\n"
            "Start by performing multiple diverse searches to gather a wide range of sources. "
            "Use different search queries and keywords to maximize coverage. "
            "Only dive deep into specific sources after surveying the landscape. "
            "Prioritize finding multiple independent sources that confirm or contradict each other."
        ),
    },
    {
        "name": "depth_first",
        "description": "Deep investigation strategy",
        "max_turns": 300,  # More turns - deep exploration
        "prompt_suffix": (
            "\n\n[Strategy: Depth-First Investigation]\n"
            "Focus on finding the most authoritative primary source first. "
            "Once you find a promising lead, follow it deeply - read full articles, "
            "follow references, and extract precise details. "
            "Prefer official/academic sources over secondary summaries. "
            "Be thorough with each source before moving to the next."
        ),
    },
    {
        "name": "lateral_thinking",
        "description": "Alternative angle strategy",
        "max_turns": 200,  # Medium turns - creative exploration
        "prompt_suffix": (
            "\n\n[Strategy: Lateral Thinking]\n"
            "Approach the problem from unexpected angles. "
            "Consider alternative phrasings, related concepts, or indirect paths to the answer. "
            "If direct searches don't work, try searching for related entities, events, or contexts. "
            "Use code execution to compute, verify, or transform data when helpful. "
            "Think creatively about what tools and queries might reveal the answer."
        ),
    },
    # EA-010: New strategy with custom max_turns
    {
        "name": "verification_heavy",
        "description": "Verification-focused strategy",
        "max_turns": 150,  # Medium-high, focused on verification
        "prompt_suffix": (
            "\n\n[Strategy: Verification-Heavy]\n"
            "After finding an answer, verify it through multiple independent sources. "
            "Cross-reference dates, numbers, and facts. "
            "If you find conflicting information, investigate further until you have high confidence. "
            "Always prefer verifiable facts over unverified claims."
        ),
    },
]


def _select_strategies(
    cfg: DictConfig,
    task_description: str,
    num_paths: int,
) -> List[Dict]:
    """Select strategies based on StrategyEvolver preferences (if available).

    If evolving is enabled and strategy_preferences.json has recommendations
    for the detected question type, prioritize recommended strategies.
    Falls back to default STRATEGY_VARIANTS[:num_paths].
    """
    default = STRATEGY_VARIANTS[:num_paths]

    evolving_cfg = cfg.get("evolving", {})
    if not evolving_cfg.get("enabled", False):
        return default

    try:
        from ..evolving.experience_injector import ExperienceInjector
        from ..evolving.experience_store import ExperienceStore
        from ..evolving.strategy_evolver import StrategyEvolver

        prefs_file = evolving_cfg.get("strategy_preferences_file", "")
        if not prefs_file:
            return default

        store = ExperienceStore(evolving_cfg.get("experience_file", ""))
        evolver = StrategyEvolver(store, prefs_file, evolving_cfg.get("prompt_overrides_file", ""))

        prefs = evolver.load_strategy_preferences()
        if not prefs or not prefs.get("stats"):
            return default

        # Classify the task to find question_type
        labels = ExperienceInjector._classify_via_rules(task_description)
        question_type = labels.get("question_type", "")
        if not question_type:
            return default

        recs = prefs.get("recommendations", {}).get(question_type, [])
        if isinstance(recs, str) or not recs:
            return default

        # Build strategy list: recommended first, then fill with others
        strategy_map = {s["name"]: s for s in STRATEGY_VARIANTS}
        selected = []
        for name in recs:
            if name in strategy_map and len(selected) < num_paths:
                selected.append(strategy_map[name])
        for s in STRATEGY_VARIANTS:
            if s not in selected and len(selected) < num_paths:
                selected.append(s)

        logger.info(
            f"Dynamic strategy selection for '{question_type}': "
            f"{[s['name'] for s in selected]} (recommended: {recs})"
        )
        return selected

    except Exception as e:
        logger.warning(f"Strategy selection failed, using defaults: {e}")
        return default


async def _run_single_path(
    *,
    cfg: DictConfig,
    task_id: str,
    task_description: str,
    task_file_name: str,
    main_agent_tool_manager: ToolManager,  # EA-005: Independent ToolManager per path
    sub_agent_tool_managers: Dict[str, ToolManager],
    output_formatter: OutputFormatter,
    strategy: Dict[str, str],  # EA-002: Strategy variant definition
    path_index: int,
    ground_truth: Optional[Any] = None,
    log_dir: str = "logs",
    tool_definitions: Optional[List[Dict[str, Any]]] = None,
    sub_agent_tool_definitions: Optional[Dict[str, List[Dict[str, Any]]]] = None,
    # EA-010: Custom max_turns per strategy (optional override)
    max_turns: Optional[int] = None,
    # EA-307: OpenViking context for cross-path sharing
    viking_context: Optional[OpenVikingContext] = None,
) -> Tuple[str, str, str, str, Dict]:
    """
    EA-001: Run a single agent path with a specific strategy.
    EA-006: Each path creates its own TaskLog for isolated logging.
    EA-307: Optionally loads context from OpenViking and shares discoveries.
    
    Returns:
        Tuple of (final_summary, final_boxed_answer, log_file_path, strategy_name, metadata)
    """
    from .orchestrator import Orchestrator

    strategy_name = strategy["name"]
    path_task_id = f"{task_id}_path{path_index}_{strategy_name}"
    
    # EA-010: Override max_turns with strategy-specific value
    # If max_turns is not provided, use strategy's max_turns or fall back to config
    if max_turns is None:
        max_turns = strategy.get("max_turns", None)
    
    # Create a modified config with strategy-specific max_turns
    if max_turns is not None:
        cfg = OmegaConf.create(OmegaConf.to_container(cfg, resolve=True))
        if hasattr(cfg, 'agent') and hasattr(cfg.agent, 'main_agent'):
            cfg.agent.main_agent.max_turns = max_turns
        elif hasattr(cfg, 'agent'):
            cfg.agent.max_turns = max_turns

    # EA-006: Create isolated task log for this path
    task_log = TaskLog(
        log_dir=log_dir,
        task_id=path_task_id,
        start_time=get_utc_plus_8_time(),
        input={"task_description": task_description, "task_file_name": task_file_name},
        env_info=get_env_info(cfg),
        ground_truth=ground_truth,
    )

    task_log.log_step(
        "info",
        f"MultiPath | Path {path_index}",
        f"Starting path with strategy: {strategy_name} - {strategy['description']} "
        f"(max_turns: {max_turns or 'default'})",
    )

    # Set task_log for tool managers
    main_agent_tool_manager.set_task_log(task_log)
    if sub_agent_tool_managers:
        for sub_tm in sub_agent_tool_managers.values():
            sub_tm.set_task_log(task_log)

    try:
        # Create LLM client for this path
        random_uuid = str(uuid.uuid4())
        unique_id = f"{path_task_id}-{random_uuid}"
        llm_client = ClientFactory(task_id=unique_id, cfg=cfg, task_log=task_log)

        # Create orchestrator with strategy-augmented prompt
        orchestrator = Orchestrator(
            main_agent_tool_manager=main_agent_tool_manager,
            sub_agent_tool_managers=sub_agent_tool_managers,
            llm_client=llm_client,
            output_formatter=output_formatter,
            cfg=cfg,
            task_log=task_log,
            tool_definitions=tool_definitions,
            sub_agent_tool_definitions=sub_agent_tool_definitions,
        )

        # EA-002: Inject strategy into the orchestrator's prompt generation
        # Strategy is applied via prompt suffix (DD-001: prompt injection, not code logic)
        # EA-307: Also inject OpenViking context (discoveries from other paths)
        original_generate = llm_client.generate_agent_system_prompt

        # EA-307: Load task context and cross-path discoveries
        viking_suffix = ""
        if viking_context:
            try:
                # Load strategy-specific context
                ctx_blocks = await viking_context.load_task_context(
                    task_description, strategy_name
                )
                if ctx_blocks:
                    viking_suffix += "\n\n[Context from Knowledge Base]\n"
                    for block in ctx_blocks:
                        viking_suffix += f"- {block.content}\n"

                # Query discoveries shared by other paths
                discoveries = await viking_context.query_shared_discoveries(
                    task_description, exclude_path=path_task_id
                )
                if discoveries:
                    viking_suffix += "\n[Discoveries from Other Research Paths]\n"
                    for d in discoveries:
                        viking_suffix += f"- [{d.strategy}] {d.title}: {d.snippet}\n"
                    viking_suffix += (
                        "Use these discoveries as additional leads, "
                        "but verify them independently.\n"
                    )
            except Exception as e:
                logger.warning(f"OpenViking context loading failed for path {path_index}: {e}")

        def strategy_augmented_prompt(date, mcp_servers):
            base_prompt = original_generate(date=date, mcp_servers=mcp_servers)
            return base_prompt + strategy["prompt_suffix"] + viking_suffix

        llm_client.generate_agent_system_prompt = strategy_augmented_prompt

        # Run the agent
        start_time = asyncio.get_event_loop().time()
        
        # EA-011: Stream path start
        from .streaming import get_stream_manager
        stream = get_stream_manager().create_path_stream(path_task_id, strategy_name, task_description)
        await stream.start()
        
        final_summary, final_boxed_answer = await orchestrator.run_main_agent(
            task_description=task_description,
            task_file_name=task_file_name,
            task_id=path_task_id,
        )
        elapsed = asyncio.get_event_loop().time() - start_time
        
        # EA-011: Stream path end
        await stream.end(final_answer=final_boxed_answer, status="success")

        llm_client.close()

        task_log.final_boxed_answer = final_boxed_answer
        task_log.status = "success"
        task_log.end_time = get_utc_plus_8_time()
        log_file_path = task_log.save()

        # EA-304: Extract cost data from task_log
        input_tokens = 0
        output_tokens = 0
        tool_calls = 0
        
        if hasattr(task_log, "usage_log") and task_log.usage_log:
            usage = task_log.usage_log
            if isinstance(usage, dict):
                input_tokens = usage.get("input_tokens", 0) or usage.get("input", 0)
                output_tokens = usage.get("output_tokens", 0) or usage.get("output", 0)
        
        if hasattr(task_log, "tool_call_count"):
            tool_calls = task_log.tool_call_count
        elif hasattr(task_log, "steps_count"):
            tool_calls = task_log.steps_count
        
        # Get model name from config or default
        model_name = "qwen/qwen3-8b"
        if hasattr(cfg, "llm") and hasattr(cfg.llm, "model_name"):
            model_name = cfg.llm.model_name
        elif hasattr(cfg, "model_name"):
            model_name = cfg.model_name
        
        metadata = {
            "strategy": strategy_name,
            "elapsed_seconds": round(elapsed, 2),
            "turns": task_log.steps_count if hasattr(task_log, "steps_count") else 0,
            "status": "success",
            # EA-010: Budget allocation
            "max_turns": max_turns,
            # EA-304: Cost tracking fields
            "model": model_name,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "tool_calls": tool_calls,
            "duration": round(elapsed, 2),
        }

        # EA-307: Save result and share discoveries via OpenViking
        if viking_context:
            try:
                await viking_context.save_path_result(
                    path_id=path_task_id,
                    strategy=strategy_name,
                    result={"answer": final_boxed_answer, "turns": metadata.get("turns", 0)},
                    success=True,
                )
                # Share key findings as discoveries for other paths
                if final_boxed_answer:
                    await viking_context.share_discovery(
                        path_id=path_task_id,
                        strategy=strategy_name,
                        discovery=Discovery(
                            path_id=path_task_id,
                            strategy=strategy_name,
                            uri=f"path://{path_task_id}/answer",
                            title=f"Path {path_index} ({strategy_name}) conclusion",
                            snippet=final_boxed_answer[:300],
                        ),
                    )
            except Exception as e:
                logger.warning(f"OpenViking post-path save failed: {e}")

        logger.info(
            f"Path {path_index} ({strategy_name}) completed: answer='{final_boxed_answer[:100]}...'"
        )

        return final_summary, final_boxed_answer, log_file_path, strategy_name, metadata

    except Exception as e:
        import traceback
        error_details = traceback.format_exc()
        task_log.status = "failed"
        task_log.error = error_details
        task_log.end_time = get_utc_plus_8_time()
        log_file_path = task_log.save()

        # EA-011: Stream error
        try:
            stream = get_stream_manager().get_path_stream(path_task_id)
            if stream:
                await stream.error(f"Path failed: {str(e)}", error_details[:500])
                await stream.end(final_answer="", status="failed")
        except:
            pass

        logger.warning(f"Path {path_index} ({strategy_name}) failed: {e}")

        return (
            f"Error in path {path_index}: {str(e)}",
            "",
            log_file_path,
            strategy_name,
            {
                "strategy": strategy_name, 
                "status": "failed", 
                "error": str(e),
                # EA-304: Cost tracking fields (failed paths have 0 tokens)
                "model": "qwen/qwen3-8b",
                "input_tokens": 0,
                "output_tokens": 0,
                "tool_calls": 0,
                "duration": 0.0,
            },
        )


async def _vote_best_answer(
    results: List[Tuple[str, str, str, str, Dict]],
    task_description: str,
    cfg: DictConfig,
    task_log: TaskLog,
) -> Tuple[str, str, str]:
    """
    EA-003: LLM voting — cross-validate answers and select the best one.
    EA-004: Majority vote fast path — skip LLM Judge when paths agree.
    DD-003: Majority vote first + LLM Judge fallback (zero cost when consensus).
    
    Returns:
        Tuple of (best_summary, best_answer, best_log_path)
    """
    # Filter successful results
    valid_results = [r for r in results if r[4].get("status") == "success" and r[1].strip()]

    if not valid_results:
        task_log.log_step("warning", "MultiPath | Vote", "No valid results to vote on")
        # Return the first result even if failed
        if results:
            return results[0][0], results[0][1], results[0][2]
        return "No answer generated", "", ""

    if len(valid_results) == 1:
        task_log.log_step("info", "MultiPath | Vote", "Only one valid result, using it directly")
        r = valid_results[0]
        return r[0], r[1], r[2]

    # Check if answers agree (simple string matching after normalization)
    answers = [r[1].strip().lower() for r in valid_results]
    
    # Count answer frequencies
    from collections import Counter
    answer_counts = Counter(answers)
    most_common_answer, most_common_count = answer_counts.most_common(1)[0]

    if most_common_count > 1:
        # EA-004: Majority vote fast path — multiple paths agree, skip LLM Judge
        task_log.log_step(
            "info",
            "MultiPath | Vote | Majority",
            f"{most_common_count}/{len(valid_results)} paths agree on the answer",
        )
        # Return the first result that matches the majority answer
        for r in valid_results:
            if r[1].strip().lower() == most_common_answer:
                return r[0], r[1], r[2]

    # EA-003: All answers differ — invoke LLM Judge to select best answer
    task_log.log_step(
        "info",
        "MultiPath | Vote | LLM Judge",
        f"All {len(valid_results)} paths gave different answers. Using LLM to judge.",
    )

    judge_prompt = f"""You are evaluating multiple answers to the same question. Pick the best answer.

Question: {task_description}

"""
    for i, r in enumerate(valid_results):
        judge_prompt += f"--- Answer {i+1} (Strategy: {r[3]}) ---\n"
        judge_prompt += f"Summary: {r[0][:2000]}\n"
        judge_prompt += f"Final Answer: {r[1]}\n\n"

    judge_prompt += """Which answer is most likely correct and well-supported? 
Respond with ONLY the answer number (1, 2, or 3) and a brief reason.
Format: BEST: <number>
Reason: <brief explanation>"""

    try:
        random_uuid = str(uuid.uuid4())
        judge_client = ClientFactory(
            task_id=f"judge-{random_uuid}", cfg=cfg, task_log=task_log
        )

        message_history = [{"role": "user", "content": judge_prompt}]
        response, _ = await judge_client.create_message(
            system_prompt="You are an impartial judge evaluating answer quality.",
            message_history=message_history,
            tool_definitions=[],
            keep_tool_result=-1,
            step_id=0,
            task_log=task_log,
            agent_type="judge",
        )
        judge_client.close()

        # Parse judge response
        if response:
            from ..utils.parsing_utils import extract_llm_response_text
            judge_text = extract_llm_response_text(str(response)) or str(response)
            
            task_log.log_step(
                "info", "MultiPath | Vote | Judge Response", judge_text[:500]
            )

            # Extract the chosen number
            import re
            match = re.search(r"BEST:\s*(\d+)", judge_text)
            if match:
                chosen_idx = int(match.group(1)) - 1
                if 0 <= chosen_idx < len(valid_results):
                    r = valid_results[chosen_idx]
                    task_log.log_step(
                        "info",
                        "MultiPath | Vote | Selected",
                        f"Judge selected answer {chosen_idx + 1} (strategy: {r[3]})",
                    )
                    return r[0], r[1], r[2]

    except Exception as e:
        logger.warning(f"LLM judge failed: {e}")
        task_log.log_step("warning", "MultiPath | Vote | Judge Failed", str(e))

    # Fallback: return the first valid result
    r = valid_results[0]
    return r[0], r[1], r[2]


async def execute_multi_path_pipeline(
    cfg: DictConfig,
    task_id: str,
    task_description: str,
    task_file_name: str,
    main_agent_tool_manager: ToolManager,
    sub_agent_tool_managers: Dict[str, ToolManager],
    output_formatter: OutputFormatter,
    ground_truth: Optional[Any] = None,
    log_dir: str = "logs",
    num_paths: int = 3,  # EA-008: Dynamic path count via NUM_PATHS env or config
    strategies: Optional[List[Dict]] = None,
    tool_definitions: Optional[List[Dict[str, Any]]] = None,
    sub_agent_tool_definitions: Optional[Dict[str, List[Dict[str, Any]]]] = None,
    # EA-009: Early stopping parameters
    early_stop_k: int = 2,
    early_stop_threshold: float = 1.0,
) -> Tuple[str, str, str]:
    """
    EA-001: Multi-path scheduler — execute N parallel agent paths and select best answer.
    EA-007: Master log aggregation — all path results aggregated to master_log.
    EA-008: Path count is configurable via num_paths parameter.
    
    Args:
        cfg: Hydra configuration
        task_id: Task identifier
        task_description: The question/task
        task_file_name: Associated file path
        main_agent_tool_manager: Tool manager for main agent
        sub_agent_tool_managers: Tool managers for sub-agents
        output_formatter: Output formatter
        ground_truth: Optional ground truth for evaluation
        log_dir: Directory for logs
        num_paths: Number of parallel paths (default 3)
        strategies: Custom strategy list (default: STRATEGY_VARIANTS)
        tool_definitions: Pre-fetched tool definitions
        sub_agent_tool_definitions: Pre-fetched sub-agent tool definitions
    
    Returns:
        Tuple of (final_summary, final_boxed_answer, log_file_path)
    """
    if strategies is None:
        strategies = _select_strategies(cfg, task_description, num_paths)

    # EA-307: Initialize OpenViking context for cross-path sharing
    viking_context = None
    ov_cfg = OmegaConf.to_container(cfg, resolve=True) if cfg else {}
    ov_enabled = ov_cfg.get("openviking", {}).get("enabled", False) if isinstance(ov_cfg, dict) else False
    # Also enable in fallback mode (in-memory) when evolving is on
    evolving_enabled = ov_cfg.get("evolving", {}).get("enabled", False) if isinstance(ov_cfg, dict) else False
    if ov_enabled or evolving_enabled:
        try:
            viking_context = OpenVikingContext(
                enabled=ov_enabled,
                fallback_mode=True,  # Always allow in-memory fallback
            )
            await viking_context.connect()
            logger.info(f"OpenViking context initialized (server={'connected' if viking_context._connected else 'fallback'})")
        except Exception as e:
            logger.warning(f"OpenViking init failed, continuing without: {e}")
            viking_context = None

    # EA-007: Create master task log for aggregation
    master_log = TaskLog(
        log_dir=log_dir,
        task_id=f"{task_id}_multipath",
        start_time=get_utc_plus_8_time(),
        input={"task_description": task_description, "task_file_name": task_file_name},
        env_info=get_env_info(cfg),
        ground_truth=ground_truth,
    )

    master_log.log_step(
        "info",
        "MultiPath | Start",
        f"Launching {len(strategies)} parallel paths for task: {task_id}",
    )
    
    # EA-011: Initialize streaming
    stream_manager = get_stream_manager()
    stream_manager.add_consumer(ConsoleStreamConsumer(verbose=True))
    stream_manager.add_consumer(FileStreamConsumer(Path(log_dir) / "stream.jsonl"))
    
    # Broadcast task start to all streams
    from .streaming import StreamEvent
    start_event = StreamEvent(
        event_type=StreamEventType.PATH_START,
        path_id=f"{task_id}_multipath",
        content=f"Starting multi-path task: {task_id}",
        metadata={"num_paths": len(strategies), "task_description": task_description},
    )
    await stream_manager.broadcast(start_event)

    # EA-005: Create independent ToolManagers for each path to avoid state conflicts
    # DD-002: Each path uses independent ToolManager (MCP connections are stateful)
    #
    # FIX: Pre-fetch tool definitions ONCE, then share across all paths.
    # Tool definitions are static schema data (name, description, inputSchema) —
    # they contain no runtime state and are identical across paths.
    # This avoids N×M concurrent MCP subprocess launches (N paths × M servers)
    # which frequently caused 30s timeouts, leaving paths with empty tool lists.
    # Actual tool EXECUTION still happens per-path via independent ToolManagers.
    if not tool_definitions:
        _prefetch_tm = ToolManager(
            *create_mcp_server_parameters(cfg, cfg.agent.main_agent)
        )
        master_log.log_step(
            "info",
            "MultiPath | Tool Prefetch",
            "Pre-fetching tool definitions once for all paths...",
        )
        try:
            tool_definitions = await asyncio.wait_for(
                _prefetch_tm.get_all_tool_definitions(),
                timeout=int(os.getenv("MIROFLOW_TOOL_DEFS_TIMEOUT_S", "30")),
            )
            master_log.log_step(
                "info",
                "MultiPath | Tool Prefetch",
                f"Successfully pre-fetched tool definitions: {sum(len(s.get('tools',[])) for s in tool_definitions)} tools from {len(tool_definitions)} servers",
            )
        except (asyncio.TimeoutError, Exception) as e:
            master_log.log_step(
                "warning",
                "MultiPath | Tool Prefetch",
                f"Failed to pre-fetch tool definitions ({e}); paths will retry individually.",
            )
            tool_definitions = None  # Let each path try on its own as fallback

    if not sub_agent_tool_definitions and cfg.agent.sub_agents:
        sub_agent_tool_definitions = {}
        for sub_agent in cfg.agent.sub_agents:
            sub_mcp_configs, sub_blacklist = create_mcp_server_parameters(
                cfg, cfg.agent.sub_agents[sub_agent]
            )
            _sub_tm = ToolManager(sub_mcp_configs, tool_blacklist=sub_blacklist)
            try:
                sub_agent_tool_definitions[sub_agent] = await asyncio.wait_for(
                    _sub_tm.get_all_tool_definitions(),
                    timeout=int(os.getenv("MIROFLOW_TOOL_DEFS_TIMEOUT_S", "30")),
                )
            except (asyncio.TimeoutError, Exception):
                sub_agent_tool_definitions[sub_agent] = None

    path_tool_managers = []
    path_sub_managers = []
    for i in range(len(strategies)):
        # Create fresh tool managers for each path (used for tool EXECUTION only)
        main_mcp_configs, main_blacklist = create_mcp_server_parameters(
            cfg, cfg.agent.main_agent
        )
        path_tm = ToolManager(main_mcp_configs, tool_blacklist=main_blacklist)
        path_tool_managers.append(path_tm)

        sub_tms = {}
        if cfg.agent.sub_agents:
            for sub_agent in cfg.agent.sub_agents:
                sub_mcp_configs, sub_blacklist = create_mcp_server_parameters(
                    cfg, cfg.agent.sub_agents[sub_agent]
                )
                sub_tms[sub_agent] = ToolManager(sub_mcp_configs, tool_blacklist=sub_blacklist)
        path_sub_managers.append(sub_tms)

    # EA-012: Create wrapped tasks with retry logic
    tasks = []
    for i, strategy in enumerate(strategies):
        strategy_max_turns = strategy.get("max_turns", None)
        
        async def run_with_retry(idx: int, strat: Dict, max_trns: Optional[int], retry_count: int = 0):
            """Run a path with retry on failure"""
            try:
                result = await _run_single_path(
                    cfg=cfg,
                    task_id=task_id,
                    task_description=task_description,
                    task_file_name=task_file_name,
                    main_agent_tool_manager=path_tool_managers[idx],
                    sub_agent_tool_managers=path_sub_managers[idx],
                    output_formatter=OutputFormatter(),
                    strategy=strat,
                    path_index=idx,
                    ground_truth=ground_truth,
                    log_dir=log_dir,
                    tool_definitions=tool_definitions,
                    sub_agent_tool_definitions=sub_agent_tool_definitions,
                    max_turns=max_trns,
                    viking_context=viking_context,
                )
                # EA-012: Check for retryable failure
                if len(result) > 4 and isinstance(result[4], dict):
                    status = result[4].get("status", "")
                    error = result[4].get("error", "")
                    if status == "failed" and retry_count < MAX_RETRIES:
                        if _is_retryable_error(error):
                            fallback = _get_fallback_strategy(strat["name"])
                            if fallback:
                                master_log.log_step("info", "MultiPath | Retry", 
                                    f"Path {idx} failed. Retrying with {fallback['name']} (attempt {retry_count + 1})")
                                return await run_with_retry(idx, fallback, max_trns, retry_count + 1)
                return result
            except Exception as e:
                if retry_count < MAX_RETRIES and _is_retryable_error(str(e)):
                    fallback = _get_fallback_strategy(strat["name"])
                    if fallback:
                        master_log.log_step("info", "MultiPath | Retry", f"Path {idx} exception: {e}. Retrying with {fallback['name']}")
                        return await run_with_retry(idx, fallback, max_trns, retry_count + 1)
                raise
        
        task = run_with_retry(i, strategy, strategy_max_turns)
        tasks.append(task)

    master_log.log_step(
        "info",
        "MultiPath | Running",
        f"All {len(tasks)} paths launched concurrently (early_stop_k={early_stop_k}, threshold={early_stop_threshold})",
    )

    # EA-009: Run with early stopping
    # If early_stop_k > number of paths, fall back to gather (no early stopping)
    if early_stop_k > len(tasks) or early_stop_threshold <= 0:
        # Standard gather without early stopping
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Process results - convert exceptions to failed results
        processed_results = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                logger.error(f"Path {i} raised exception: {result}")
                processed_results.append((
                    f"Path {i} exception: {str(result)}",
                    "",
                    "",
                    strategies[i]["name"],
                    {"strategy": strategies[i]["name"], "status": "failed", "error": str(result)},
                ))
            else:
                processed_results.append(result)
    else:
        # Use early stopping
        raw_results = await _run_with_early_stopping(
            tasks, strategies, early_stop_k, early_stop_threshold, 
            master_log, log_dir, task_id=task_id
        )
        
        # Post-process results (already in correct format from _run_with_early_stopping)
        processed_results = raw_results

    # Log all results
    for i, r in enumerate(processed_results):
        master_log.log_step(
            "info",
            f"MultiPath | Path {i} Result",
            f"Strategy: {r[3]} | Status: {r[4].get('status')} | Answer: {r[1][:200]}",
        )

    # Vote for the best answer
    best_summary, best_answer, best_log_path = await _vote_best_answer(
        processed_results, task_description, cfg, master_log
    )

    # EA-304: Track costs
    cost_tracker = CostTracker(log_dir=log_dir)
    
    for i, r in enumerate(processed_results):
        if r and len(r) > 4:
            # Extract cost data from result metadata
            metadata = r[4] if isinstance(r[4], dict) else {}
            
            cost_tracker.record_path_cost(
                path_id=f"{task_id}_path{i}_{r[3]}",
                strategy_name=r[3],
                model_name=metadata.get("model", "qwen/qwen3-8b"),
                input_tokens=metadata.get("input_tokens", 0),
                output_tokens=metadata.get("output_tokens", 0),
                num_turns=metadata.get("turns", 0),
                num_tool_calls=metadata.get("tool_calls", 0),
                duration_seconds=metadata.get("duration", 0.0),
                status=metadata.get("status", "unknown"),
            )
    
    # Generate and log cost report
    cost_summary = cost_tracker.get_summary()
    cost_report = format_cost_report(cost_summary)
    
    master_log.log_step(
        "info",
        "MultiPath | Cost Report",
        f"Total cost: ${cost_summary.total_cost_usd:.4f} | "
        f"Tokens: {cost_summary.total_tokens:,} | "
        f"Paths: {cost_summary.total_paths}",
    )
    
    # Log recommendations
    for rec in cost_summary.recommendations:
        master_log.log_step("info", "Cost | Recommendation", rec)
    
    # Save cost data to file
    cost_file = cost_tracker.save_to_file()
    logger.info(f"Cost data saved to: {cost_file}")
    
    # Add cost info to master log
    master_log.cost_info = cost_summary.to_dict()

    master_log.log_step(
        "info",
        "MultiPath | Final",
        f"Selected answer: {best_answer[:200]}",
    )

    # Self-Evolving: Multi-path reflection
    # Reflect on each path individually + cross-path comparison
    try:
        evolving_cfg = cfg.get("evolving", {})
        if evolving_cfg.get("enabled", False) and ground_truth:
            from ..evolving.experience_store import ExperienceStore
            from ..evolving.reflector import auto_reflect_multi_path

            store = ExperienceStore(evolving_cfg.get("experience_file", ""))
            await auto_reflect_multi_path(
                path_results=processed_results,
                task_description=task_description,
                ground_truth=str(ground_truth),
                cfg=cfg,
                experience_store=store,
            )
            master_log.log_step(
                "info",
                "MultiPath | Reflection",
                f"Multi-path reflection completed for {len(processed_results)} paths",
            )
    except Exception as e:
        logger.warning(f"Multi-path reflection failed: {e}")
        master_log.log_step(
            "warning",
            "MultiPath | Reflection Error",
            str(e),
        )

    # EA-307: Trigger memory iteration and cleanup
    if viking_context:
        try:
            iteration_result = await viking_context.trigger_memory_iteration()
            stats = viking_context.get_statistics()
            master_log.log_step(
                "info",
                "MultiPath | OpenViking Summary",
                f"Memories: {stats['total_memories']}, "
                f"Discoveries: {stats['total_discoveries']}, "
                f"Recommended strategy: {iteration_result.get('recommended_strategy', 'N/A')}",
            )
            await viking_context.close()
        except Exception as e:
            logger.warning(f"OpenViking cleanup failed: {e}")

    master_log.final_boxed_answer = best_answer
    master_log.status = "success"
    master_log.end_time = get_utc_plus_8_time()
    master_log_path = master_log.save()

    return best_summary, best_answer, master_log_path
