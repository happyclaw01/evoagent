# Copyright (c) 2025 MiroMind
# Multi-Path Exploration Layer (EvoAgent - Layer 1)
#
# Runs N parallel agent paths with different search strategies on the same task,
# then selects the best answer via cross-validation voting.

import asyncio
import copy
import logging
import uuid
from typing import Any, Dict, List, Optional, Tuple

from miroflow_tools.manager import ToolManager
from omegaconf import DictConfig, OmegaConf

from ..config.settings import create_mcp_server_parameters, get_env_info
from ..io.output_formatter import OutputFormatter
from ..llm.factory import ClientFactory
from ..logging.task_logger import TaskLog, get_utc_plus_8_time

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
        # Wait for any task to complete
        done, still_pending = await asyncio.wait(
            async_tasks,
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


# Strategy variants for multi-path exploration
STRATEGY_VARIANTS = [
    {
        "name": "breadth_first",
        "description": "Broad search strategy",
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
        "prompt_suffix": (
            "\n\n[Strategy: Lateral Thinking]\n"
            "Approach the problem from unexpected angles. "
            "Consider alternative phrasings, related concepts, or indirect paths to the answer. "
            "If direct searches don't work, try searching for related entities, events, or contexts. "
            "Use code execution to compute, verify, or transform data when helpful. "
            "Think creatively about what tools and queries might reveal the answer."
        ),
    },
]


async def _run_single_path(
    *,
    cfg: DictConfig,
    task_id: str,
    task_description: str,
    task_file_name: str,
    main_agent_tool_manager: ToolManager,
    sub_agent_tool_managers: Dict[str, ToolManager],
    output_formatter: OutputFormatter,
    strategy: Dict[str, str],
    path_index: int,
    ground_truth: Optional[Any] = None,
    log_dir: str = "logs",
    tool_definitions: Optional[List[Dict[str, Any]]] = None,
    sub_agent_tool_definitions: Optional[Dict[str, List[Dict[str, Any]]]] = None,
) -> Tuple[str, str, str, str, Dict]:
    """
    Run a single agent path with a specific strategy.
    
    Returns:
        Tuple of (final_summary, final_boxed_answer, log_file_path, strategy_name, metadata)
    """
    from .orchestrator import Orchestrator

    strategy_name = strategy["name"]
    path_task_id = f"{task_id}_path{path_index}_{strategy_name}"

    # Create task log for this path
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
        f"Starting path with strategy: {strategy_name} - {strategy['description']}",
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

        # Inject strategy into the orchestrator's prompt generation
        original_generate = llm_client.generate_agent_system_prompt

        def strategy_augmented_prompt(date, mcp_servers):
            base_prompt = original_generate(date=date, mcp_servers=mcp_servers)
            return base_prompt + strategy["prompt_suffix"]

        llm_client.generate_agent_system_prompt = strategy_augmented_prompt

        # Run the agent
        start_time = asyncio.get_event_loop().time()
        final_summary, final_boxed_answer = await orchestrator.run_main_agent(
            task_description=task_description,
            task_file_name=task_file_name,
            task_id=path_task_id,
        )
        elapsed = asyncio.get_event_loop().time() - start_time

        llm_client.close()

        task_log.final_boxed_answer = final_boxed_answer
        task_log.status = "success"
        task_log.end_time = get_utc_plus_8_time()
        log_file_path = task_log.save()

        metadata = {
            "strategy": strategy_name,
            "elapsed_seconds": round(elapsed, 2),
            "turns": task_log.steps_count if hasattr(task_log, "steps_count") else 0,
            "status": "success",
        }

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

        logger.warning(f"Path {path_index} ({strategy_name}) failed: {e}")

        return (
            f"Error in path {path_index}: {str(e)}",
            "",
            log_file_path,
            strategy_name,
            {"strategy": strategy_name, "status": "failed", "error": str(e)},
        )


async def _vote_best_answer(
    results: List[Tuple[str, str, str, str, Dict]],
    task_description: str,
    cfg: DictConfig,
    task_log: TaskLog,
) -> Tuple[str, str, str]:
    """
    Cross-validate answers from multiple paths and select the best one.
    Uses majority voting + LLM judge if answers differ.
    
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
        # Majority vote - multiple paths agree
        task_log.log_step(
            "info",
            "MultiPath | Vote | Majority",
            f"{most_common_count}/{len(valid_results)} paths agree on the answer",
        )
        # Return the first result that matches the majority answer
        for r in valid_results:
            if r[1].strip().lower() == most_common_answer:
                return r[0], r[1], r[2]

    # All answers differ - use LLM judge
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
    num_paths: int = 3,
    strategies: Optional[List[Dict]] = None,
    tool_definitions: Optional[List[Dict[str, Any]]] = None,
    sub_agent_tool_definitions: Optional[Dict[str, List[Dict[str, Any]]]] = None,
    # EA-009: Early stopping parameters
    early_stop_k: int = 2,
    early_stop_threshold: float = 1.0,
) -> Tuple[str, str, str]:
    """
    Execute multiple parallel agent paths and select the best answer.
    
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
        strategies = STRATEGY_VARIANTS[:num_paths]

    # Create master task log
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

    # Create independent tool managers for each path to avoid state conflicts
    # Each path needs its own ToolManager instances
    path_tool_managers = []
    path_sub_managers = []
    for i in range(len(strategies)):
        # Create fresh tool managers for each path
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

    # Launch all paths concurrently
    tasks = []
    for i, strategy in enumerate(strategies):
        task = _run_single_path(
            cfg=cfg,
            task_id=task_id,
            task_description=task_description,
            task_file_name=task_file_name,
            main_agent_tool_manager=path_tool_managers[i],
            sub_agent_tool_managers=path_sub_managers[i],
            output_formatter=OutputFormatter(),
            strategy=strategy,
            path_index=i,
            ground_truth=ground_truth,
            log_dir=log_dir,
            tool_definitions=tool_definitions,
            sub_agent_tool_definitions=sub_agent_tool_definitions,
        )
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
            master_log, log_dir
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

    master_log.log_step(
        "info",
        "MultiPath | Final",
        f"Selected answer: {best_answer[:200]}",
    )

    master_log.final_boxed_answer = best_answer
    master_log.status = "success"
    master_log.end_time = get_utc_plus_8_time()
    master_log_path = master_log.save()

    return best_summary, best_answer, master_log_path
