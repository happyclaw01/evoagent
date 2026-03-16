# Copyright (c) 2025 MiroMind
# This source code is licensed under the MIT License.

import asyncio
import gc
import json
import os
import random
import re
from abc import ABC
from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

print("[debug] common_benchmark.py: imports (stdlib) done", flush=True)

print("[debug] importing hydra...", flush=True)
import hydra
print("[debug] imported hydra", flush=True)

print("[debug] importing evaluators.eval_utils.verify_answer_for_datasets...", flush=True)
from evaluators.eval_utils import verify_answer_for_datasets
print("[debug] imported evaluators.eval_utils.verify_answer_for_datasets", flush=True)

print("[debug] importing omegaconf (DictConfig, OmegaConf)...", flush=True)
from omegaconf import DictConfig, OmegaConf
print("[debug] imported omegaconf (DictConfig, OmegaConf)", flush=True)

print("[debug] importing src.core.pipeline (create_pipeline_components, execute_task_pipeline)...", flush=True)
from src.core.pipeline import (
    create_pipeline_components,
    execute_task_pipeline,
    execute_multi_path_task_pipeline,
)
print("[debug] imported src.core.pipeline", flush=True)

print("[debug] importing src.logging.summary_time_cost.generate_summary...", flush=True)
from src.logging.summary_time_cost import generate_summary
print("[debug] imported src.logging.summary_time_cost.generate_summary", flush=True)

print("[debug] common_benchmark.py: imports (project deps) done", flush=True)

# Constants for format error detection
FORMAT_ERROR_MESSAGE = "No \\boxed{} content found in the final answer."


def _task_worker(task_dict, cfg_dict, evaluator_kwargs):
    """
    Worker function to run a single task in a separate process.
    This function is called by ProcessPoolExecutor and must be at module level.
    """
    import asyncio

    from omegaconf import OmegaConf

    # Reconstruct config in this process
    cfg = OmegaConf.create(cfg_dict)

    # Reconstruct task
    task = BenchmarkTask(
        task_id=task_dict["task_id"],
        task_question=task_dict["task_question"],
        ground_truth=task_dict["ground_truth"],
        file_path=task_dict.get("file_path"),
        metadata=task_dict.get("metadata", {}),
    )

    # Create evaluator in this process
    evaluator = GenericEvaluator(
        data_dir=evaluator_kwargs["data_dir"],
        benchmark_name=evaluator_kwargs["benchmark_name"],
        cfg=cfg,
        metadata_file=evaluator_kwargs.get("metadata_file", "metadata.jsonl"),
        task_id_field=evaluator_kwargs.get("task_id_field", "task_id"),
        question_field=evaluator_kwargs.get("question_field", "task_question"),
        ground_truth_field=evaluator_kwargs.get("ground_truth_field", "ground_truth"),
        file_name_field=evaluator_kwargs.get("file_name_field"),
        additional_data_files=evaluator_kwargs.get("additional_data_files"),
    )
    
    # Set log_dir for subprocess (to avoid HydraConfig.get() in worker)
    if "log_dir" in evaluator_kwargs:
        evaluator._log_dir = evaluator_kwargs["log_dir"]

    # Run task in new event loop
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    # Set exception handler to suppress "Task exception was never retrieved" warnings
    def exception_handler(loop, context):
        # Suppress all asyncio internal warnings for cleaner output
        pass

    loop.set_exception_handler(exception_handler)

    try:
        result = loop.run_until_complete(evaluator.run_single_task(task))
        # Convert result to dict for serialization
        return asdict(result)
    finally:
        loop.close()


@dataclass
class BenchmarkTask:
    """Generic benchmark task data structure"""

    task_id: str
    task_question: str
    ground_truth: str
    file_path: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    model_boxed_answer: str = ""
    status: str = "pending"  # pending, success, failed


@dataclass
class BenchmarkResult:
    """Generic benchmark evaluation result structure"""

    task_id: str
    task_question: str
    ground_truth: str
    file_path: Optional[str]
    status: str
    model_boxed_answer: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)
    error_message: str = ""
    final_judge_result: Optional[str] = None
    judge_type: Optional[str] = None
    log_file_path: Optional[str] = None
    # Pass@K support fields
    attempts: List[Dict[str, Any]] = field(default_factory=list)  # Store all attempts
    pass_at_k_success: bool = False  # Whether task passed using pass@k evaluation
    k_value: int = 1  # The k value used for this evaluation


class BenchmarkEvaluator(ABC):
    """Abstract base class for benchmark evaluators"""

    def __init__(self, data_dir: str, benchmark_name: str, cfg: DictConfig):
        """
        Initialize benchmark evaluator

        Args:
            data_dir: Path to benchmark data directory
            benchmark_name: Name of the benchmark
            cfg: The Hydra configuration object
        """
        self.data_dir = Path(data_dir)
        self.benchmark_name = benchmark_name
        self.cfg = cfg
        self.pass_at_k = cfg.benchmark.execution.get("pass_at_k", 1)
        self.tasks: List[BenchmarkTask] = []
        self.results: List[BenchmarkResult] = []

        # Format error tracking and retry configuration
        self.format_error_retry_limit = cfg.benchmark.execution.get(
            "format_error_retry_limit", 3
        )

        # Get LLM provider and model from the config object
        self.llm_provider = cfg.llm.provider
        self.llm_model = cfg.llm.model_name

        # Initialize pipeline components
        print("Initializing pipeline components...")
        (
            self.main_agent_tool_manager,
            self.sub_agent_tool_managers,
            self.output_formatter,
        ) = create_pipeline_components(cfg)
        print(
            f"Pipeline components initialized successfully! Using pass@{self.pass_at_k}"
        )

    def get_log_dir(self) -> Path:
        """Get the log directory for the current benchmark and model."""
        try:
            # Try to get from Hydra config (works in main process)
            return Path(hydra.core.hydra_config.HydraConfig.get().run.dir)
        except (AttributeError, RuntimeError, ValueError):
            # Fallback for subprocess: use hydra.run.dir from config or construct from cfg
            if hasattr(self, '_log_dir'):
                return Path(self._log_dir)
            # Try to get from cfg.hydra.run.dir
            hydra_run_dir = self.cfg.get("hydra", {}).get("run", {}).get("dir")
            if hydra_run_dir:
                return Path(hydra_run_dir)
            # Last resort: construct a default path
            return Path("outputs") / self.benchmark_name / "default"

    async def run_single_task(self, task: BenchmarkTask) -> BenchmarkResult:
        """
        Run inference for a single benchmark task with pass@k support

        Args:
            task: BenchmarkTask object

        Returns:
            BenchmarkResult object
        """
        print(f"Processing task {task.task_id} with pass@{self.pass_at_k}")

        result = BenchmarkResult(
            task_id=task.task_id,
            task_question=task.task_question,
            ground_truth=task.ground_truth,
            file_path=task.file_path,
            model_boxed_answer="",
            status="pending",
            metadata=task.metadata.copy(),
            k_value=self.pass_at_k,
        )

        logs_dir = self.get_log_dir()
        found_correct_answer = False

        # Print debug info about log directory
        print(f"  Current log directory: {logs_dir}")

        try:
            # Prepare task
            task_description, task_file_path = self.prepare_task_description(task)

            # Run up to k attempts (with early stopping when correct answer found)
            for attempt in range(1, self.pass_at_k + 1):
                print(f"  Attempt {attempt}/{self.pass_at_k} for task {task.task_id}")
                format_retry_count = 0

                # Check if log file exists for this specific attempt in current directory
                log_pattern = f"task_{task.task_id}_attempt-{attempt}_*.json"
                matching_logs = []

                # Search only in current log directory
                if logs_dir.exists():
                    dir_logs = sorted(list(logs_dir.glob(log_pattern)))
                    if dir_logs:
                        matching_logs.extend(dir_logs)

                if matching_logs:
                    # Sort by timestamp in filename to get the most recent
                    def extract_timestamp(file_path):
                        filename = file_path.name
                        # Extract timestamp from filename like: task_xxx_attempt-1_format-retry-0_2025-08-13-10-13-20.json
                        # The timestamp is the last part before .json
                        if "_" in filename and filename.endswith(".json"):
                            timestamp_part = filename.split("_")[-1].replace(
                                ".json", ""
                            )
                            # Convert timestamp to datetime for proper sorting
                            from datetime import datetime

                            return datetime.strptime(
                                timestamp_part, "%Y-%m-%d-%H-%M-%S"
                            )
                        return filename

                    matching_logs = sorted(matching_logs, key=extract_timestamp)

                attempt_result = {
                    "attempt_number": attempt,
                    "model_boxed_answer": "",
                    "status": "pending",
                    "log_file_path": None,
                    "final_judge_result": None,
                    "judge_type": None,
                    "is_correct": False,
                }

                # Try to load existing result for this attempt
                if matching_logs:
                    log_file = matching_logs[-1]
                    attempt_result["log_file_path"] = str(log_file)
                    print(
                        f"    Found existing log for attempt {attempt}: {log_file.name}"
                    )

                    match = re.search(r"retry-(\d+)", os.path.basename(str(log_file)))
                    if match:
                        format_retry_count = int(match.group(1))
                    else:
                        raise ValueError(
                            f"Failed to extract retry number from log file: {log_file}"
                        )

                    try:
                        with open(log_file) as f:
                            log_data = json.loads(f.read())
                            if log_data.get("status") == "success":
                                format_retry_count += 1
                            if log_data.get("final_boxed_answer"):
                                attempt_result["model_boxed_answer"] = log_data[
                                    "final_boxed_answer"
                                ]
                                attempt_result["status"] = log_data.get("status")
                                # Check if we already have judge result in log
                                if log_data.get("final_judge_result"):
                                    attempt_result["final_judge_result"] = log_data[
                                        "final_judge_result"
                                    ]
                                    attempt_result["judge_type"] = log_data.get(
                                        "judge_type", ""
                                    )
                                    attempt_result["is_correct"] = (
                                        log_data["final_judge_result"] == "CORRECT"
                                    )
                                print(
                                    f"    Loaded existing result: {attempt_result['model_boxed_answer']}"
                                )
                    except Exception as e:
                        print(f"    Error loading log file {log_file}: {e}")

                # Run inference if no existing result or if we have a format error
                if (
                    not attempt_result["model_boxed_answer"]
                    or attempt_result["model_boxed_answer"] == FORMAT_ERROR_MESSAGE
                ):
                    # Try to get a valid response with format retry
                    print(f"TASK ID: {task.task_id}, ATTEMPT: {attempt}")

                    max_format_retries = self.format_error_retry_limit

                    while format_retry_count <= max_format_retries:
                        try:
                            # Check if multi-path is enabled
                            multi_path_cfg = self.cfg.benchmark.get("multi_path", {})
                            use_multi_path = multi_path_cfg.get("enabled", False)

                            if use_multi_path:
                                (
                                    response,
                                    final_boxed_answer,
                                    log_file_path,
                                ) = await execute_multi_path_task_pipeline(
                                    cfg=self.cfg,
                                    task_id=f"{task.task_id}_attempt-{attempt}_format-retry-{format_retry_count}",
                                    task_file_name=task_file_path,
                                    task_description=task_description,
                                    main_agent_tool_manager=self.main_agent_tool_manager,
                                    sub_agent_tool_managers=self.sub_agent_tool_managers,
                                    output_formatter=self.output_formatter,
                                    ground_truth=task.ground_truth,
                                    log_dir=str(self.get_log_dir()),
                                    num_paths=multi_path_cfg.get("num_paths", 3),
                                    early_stop_k=multi_path_cfg.get("early_stop_k", 2),
                                    early_stop_threshold=multi_path_cfg.get("early_stop_threshold", 1.0),
                                )
                            else:
                                (
                                    response,
                                    final_boxed_answer,
                                    log_file_path,
                                ) = await execute_task_pipeline(
                                    cfg=self.cfg,
                                    task_id=f"{task.task_id}_attempt-{attempt}_format-retry-{format_retry_count}",
                                    task_file_name=task_file_path,
                                    task_description=task_description,
                                    main_agent_tool_manager=self.main_agent_tool_manager,
                                    sub_agent_tool_managers=self.sub_agent_tool_managers,
                                    output_formatter=self.output_formatter,
                                    ground_truth=task.ground_truth,
                                    log_dir=str(self.get_log_dir()),
                                )

                            attempt_result["model_boxed_answer"] = (
                                final_boxed_answer if final_boxed_answer else ""
                            )
                            attempt_result["log_file_path"] = log_file_path

                            # Check for format error
                            if (
                                attempt_result["model_boxed_answer"]
                                == FORMAT_ERROR_MESSAGE
                            ):
                                format_retry_count += 1
                                if format_retry_count <= max_format_retries:
                                    continue
                                else:
                                    # Exceeded format retry limit
                                    attempt_result["status"] = "success"
                                    attempt_result["model_boxed_answer"] = (
                                        "No \\boxed{} content found after format error retry limit exceeded."
                                    )
                                    attempt_result["error_message"] = (
                                        f"Exceeded format error retry limit ({max_format_retries})"
                                    )
                                    break
                            else:
                                # Got valid response, success
                                attempt_result["status"] = "success"
                                break

                        except Exception as e:
                            attempt_result["status"] = "failed"
                            attempt_result["error_message"] = str(e)
                            print(
                                f"    Error in attempt {attempt}, format retry {format_retry_count}: {e}"
                            )
                            break

                # Perform LLM verification if we have an answer and haven't verified yet
                if (
                    attempt_result["model_boxed_answer"]
                    and attempt_result["final_judge_result"] is None
                    and task.ground_truth is not None
                ):
                    print(f"    Verifying answer for attempt {attempt}...")
                    try:
                        (
                            evaluation_result,
                            judge_type,
                        ) = await verify_answer_for_datasets(
                            benchmark_name=self.benchmark_name,
                            question=task.task_question,
                            target=task.ground_truth,
                            predicted_answer=attempt_result["model_boxed_answer"],
                        )
                        attempt_result["final_judge_result"] = evaluation_result
                        attempt_result["judge_type"] = judge_type
                        attempt_result["is_correct"] = evaluation_result == "CORRECT"

                        # Update the log file with verification result
                        if attempt_result["log_file_path"]:
                            self._update_log_file_with_evaluation(
                                attempt_result["model_boxed_answer"],
                                attempt_result["log_file_path"],
                                evaluation_result,
                                judge_type,
                            )

                        if attempt_result["is_correct"]:
                            print(f"    [OK] Attempt {attempt}: CORRECT!")
                            found_correct_answer = True
                        else:
                            print(
                                f"    [FAIL] Attempt {attempt}: INCORRECT ({evaluation_result})"
                            )

                    except Exception as e:
                        print(f"    Error verifying attempt {attempt}: {e}")
                        attempt_result["final_judge_result"] = "ERROR"
                        attempt_result["judge_type"] = "error"
                        attempt_result["is_correct"] = False

                elif attempt_result["is_correct"]:
                    print(f"    [OK] Attempt {attempt}: CORRECT (cached)")
                    found_correct_answer = True

                elif attempt_result["final_judge_result"]:
                    print(
                        f"    [FAIL] Attempt {attempt}: INCORRECT (cached: {attempt_result['final_judge_result']})"
                    )
                else:
                    print(f"    [WARN] Attempt {attempt}: No valid answer to verify")

                result.attempts.append(attempt_result)

                # Update main result with the first successful attempt or best attempt so far
                if attempt == 1 or (
                    attempt_result["status"] == "success"
                    and not result.model_boxed_answer
                ):
                    result.model_boxed_answer = attempt_result["model_boxed_answer"]
                    result.log_file_path = attempt_result["log_file_path"]
                    result.status = attempt_result["status"]
                    if "error_message" in attempt_result:
                        result.error_message = attempt_result["error_message"]

                # Early stopping: if we found a correct answer, we can stop
                if found_correct_answer:
                    print(
                        f"    Found correct answer! Stopping early after {attempt} attempts."
                    )
                    break

        except Exception as e:
            result.error_message = str(e)
            result.status = "failed"
            print(f"Error processing task {task.task_id}: {e}")

        finally:
            result.pass_at_k_success = found_correct_answer

            # Set main result judge result based on pass@k outcome
            if found_correct_answer:
                result.final_judge_result = "PASS_AT_K_SUCCESS"
                result.judge_type = "pass_at_k"
            else:
                if result.ground_truth is None:
                    result.final_judge_result = "TEST_SET_MODE"
                else:
                    result.final_judge_result = "PASS_AT_K_FAILED"
                result.judge_type = "pass_at_k"

            print(f"Task {task.task_id} completed with {len(result.attempts)} attempts")
            if result.ground_truth is not None:
                status = "SUCCESS" if found_correct_answer else "FAILED"
                print(f"    Pass@{self.pass_at_k} result: {status}")

        gc.collect()
        return result

    def _run_single_task_sync(self, task: BenchmarkTask) -> BenchmarkResult:
        """Sync wrapper for run_single_task to be used in threads"""
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        # Set exception handler to suppress "Task exception was never retrieved" warnings
        def exception_handler(loop, context):
            # Suppress all asyncio internal warnings for cleaner output
            pass

        loop.set_exception_handler(exception_handler)

        try:
            # Direct await is simpler and cleaner than gather for single task
            return loop.run_until_complete(self.run_single_task(task))
        finally:
            loop.close()

    def run_sequential_inference(self, tasks: List[BenchmarkTask]) -> List[BenchmarkResult]:
        """Run inference on tasks sequentially in the current process (no multiprocessing)."""
        print(f"Running inference on {len(tasks)} tasks (sequential, single process)")
        processed_results: List[BenchmarkResult] = []
        total = len(tasks)
        for idx, task in enumerate(tasks, start=1):
            print(f"Progress: {idx}/{total} (task_id={task.task_id})")
            try:
                result = self._run_single_task_sync(task)
            except Exception as e:
                result = BenchmarkResult(
                    task_id=task.task_id,
                    task_question=task.task_question,
                    ground_truth=task.ground_truth,
                    file_path=task.file_path,
                    status="failed",
                    model_boxed_answer="",
                    metadata=task.metadata.copy(),
                    error_message=str(e),
                )
            processed_results.append(result)
        self.results = processed_results
        return processed_results

    def run_parallel_inference(
        self, tasks: List[BenchmarkTask], max_concurrent: int = 3
    ) -> List[BenchmarkResult]:
        """Run inference on multiple tasks in parallel using multiprocessing"""
        # If user requests sequential execution, avoid spawning subprocesses.
        if max_concurrent <= 1:
            return self.run_sequential_inference(tasks)

        print(
            f"Running inference on {len(tasks)} tasks with max_concurrent={max_concurrent} (multiprocessing)"
        )

        # Serialize config
        cfg_dict = OmegaConf.to_container(self.cfg, resolve=True)

        # Shuffle tasks to avoid order bias and improve balancing
        shuffled_tasks = tasks.copy()
        random.shuffle(shuffled_tasks)

        # Get log_dir from main process before passing to workers
        try:
            main_log_dir = str(self.get_log_dir())
        except Exception:
            # If we can't get it, use a default
            main_log_dir = str(Path("outputs") / self.benchmark_name / "default")
        
        # Prepare evaluator kwargs for worker processes
        evaluator_kwargs = {
            "data_dir": str(self.data_dir),
            "benchmark_name": self.benchmark_name,
            "log_dir": main_log_dir,  # Pass log_dir to workers
        }
        # Add GenericEvaluator specific kwargs if available
        if hasattr(self, "metadata_file"):
            evaluator_kwargs["metadata_file"] = str(self.metadata_file.name)
        if hasattr(self, "task_id_field"):
            evaluator_kwargs["task_id_field"] = self.task_id_field
        if hasattr(self, "question_field"):
            evaluator_kwargs["question_field"] = self.question_field
        if hasattr(self, "ground_truth_field"):
            evaluator_kwargs["ground_truth_field"] = self.ground_truth_field
        if hasattr(self, "file_name_field"):
            evaluator_kwargs["file_name_field"] = self.file_name_field

        # Prepare serializable arguments for worker processes
        worker_args = []
        for task in shuffled_tasks:
            task_dict = {
                "task_id": task.task_id,
                "task_question": task.task_question,
                "ground_truth": task.ground_truth,
                "file_path": task.file_path,
                "metadata": task.metadata,
            }
            worker_args.append((task_dict, cfg_dict, evaluator_kwargs))

        # Use ProcessPoolExecutor for true parallelism (bypasses GIL)
        processed_results = []
        task_index_map = {
            task.task_id: (i, task) for i, task in enumerate(shuffled_tasks)
        }
        results_dict = {}  # Store results by task_id to maintain order

        executor = None
        try:
            executor = ProcessPoolExecutor(max_workers=max_concurrent)
            # Submit all tasks
            future_to_task_id = {}
            for args in worker_args:
                task_dict = args[0]  # First element is task_dict
                future = executor.submit(_task_worker, *args)
                future_to_task_id[future] = task_dict["task_id"]

            # Collect results as they complete
            from concurrent.futures import as_completed

            for future in as_completed(future_to_task_id):
                task_id = future_to_task_id[future]
                try:
                    result_dict = future.result()
                    # Reconstruct BenchmarkResult from dict
                    result = BenchmarkResult(**result_dict)
                    results_dict[task_id] = result
                    completed = len(results_dict)
                    print(
                        f"Progress: {completed}/{len(shuffled_tasks)} tasks completed"
                    )
                except Exception as e:
                    print(f"Exception in task {task_id}: {e}")
                    # Get original task for error result
                    _, original_task = task_index_map[task_id]
                    error_result = BenchmarkResult(
                        task_id=original_task.task_id,
                        task_question=original_task.task_question,
                        ground_truth=original_task.ground_truth,
                        file_path=original_task.file_path,
                        model_boxed_answer="",
                        status="failed",
                        metadata=original_task.metadata.copy(),
                        error_message=str(e),
                    )
                    results_dict[task_id] = error_result
        except KeyboardInterrupt:
            print("\n[WARN] Received interrupt signal, shutting down gracefully...")
            if executor:
                print("  Cancelling pending tasks and terminating worker processes...")
                # Cancel all pending futures
                for future in future_to_task_id:
                    future.cancel()

                # Forcefully terminate worker processes
                # Access internal processes and terminate them
                if hasattr(executor, "_processes") and executor._processes:
                    for pid, process in executor._processes.items():
                        try:
                            if process.is_alive():
                                print(f"    Terminating worker process {pid}...")
                                process.terminate()
                        except Exception as e:
                            print(
                                f"    Warning: Failed to terminate process {pid}: {e}"
                            )

                    # Give processes a short time to terminate gracefully
                    import time

                    time.sleep(0.5)

                    # Force kill any remaining processes
                    for pid, process in executor._processes.items():
                        try:
                            if process.is_alive():
                                print(f"    Force killing worker process {pid}...")
                                process.kill()
                        except Exception as e:
                            print(f"    Warning: Failed to kill process {pid}: {e}")

                # Shutdown executor without waiting for pending tasks
                executor.shutdown(wait=False, cancel_futures=True)
            print("  Shutdown complete.")
            raise
        finally:
            # Ensure executor is properly cleaned up
            if executor:
                try:
                    executor.shutdown(wait=True)
                except Exception:
                    pass  # Ignore errors during cleanup

        # Reconstruct results in original task order
        processed_results = [results_dict[task.task_id] for task in shuffled_tasks]

        # Sort results to maintain original task order
        task_id_to_index = {task.task_id: i for i, task in enumerate(tasks)}
        processed_results.sort(
            key=lambda r: task_id_to_index.get(r.task_id, len(tasks))
        )

        self.results = processed_results
        return processed_results

    def save_results(self, output_file: str) -> str:
        """Save evaluation results to JSONL file"""
        output_path = Path(output_file)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        with open(output_path, "w", encoding="utf-8") as f:
            for result in self.results:
                f.write(json.dumps(asdict(result), ensure_ascii=False) + "\n")

        print(f"Results saved to {output_path}")
        return str(output_path)

    def evaluate_accuracy(self) -> float:
        """Evaluate pass@k accuracy (verification already done in run_single_task)"""
        if not self.results:
            print("No results to evaluate")
            return 0.0

        print(
            f"Calculating pass@{self.pass_at_k} accuracy for {len(self.results)} results..."
        )

        correct_count = 0
        total_count = 0
        f1_scores = []

        for result in self.results:
            total_count += 1

            # Display task results
            print(f"\nTask {result.task_id}:")
            print(f"  Attempts: {len(result.attempts)}")
            if result.ground_truth is not None:
                # Use ASCII characters for Windows compatibility
                status = "SUCCESS" if result.pass_at_k_success else "FAILED"
                print(f"  Pass@{self.pass_at_k}: {status}")

            print("  " + "=" * 50)
            print(f"  Reference: {result.ground_truth}")
            print("  " + "=" * 50)

            if result.pass_at_k_success:
                correct_count += 1

            # Extract F1 score from judge_type if available (futurex)
            for attempt in result.attempts:
                jt = attempt.get("judge_type", "") or ""
                if "futurex_f1" in jt:
                    import re as _re
                    m = _re.search(r"futurex_f1\(([\d.]+)\)", jt)
                    if m:
                        f1_scores.append(float(m.group(1)))
                        break
            else:
                # No futurex F1 found, use binary
                if result.pass_at_k_success:
                    f1_scores.append(1.0)
                elif result.ground_truth is not None:
                    f1_scores.append(0.0)

        pass_at_k_accuracy = correct_count / total_count if total_count > 0 else 0.0

        print(f"\nPass@{self.pass_at_k} Final Results:")
        print(f"Tasks passed: {correct_count}/{total_count}")
        print(f"Pass@{self.pass_at_k} Accuracy: {pass_at_k_accuracy:.2%}")

        # Print F1-based accuracy if available
        if f1_scores:
            avg_f1 = sum(f1_scores) / len(f1_scores)
            print(f"Average F1 Score: {avg_f1:.4f} ({avg_f1:.2%})")

        return pass_at_k_accuracy

    def _update_log_file_with_evaluation(
        self,
        model_boxed_answer: str,
        log_file_path: str,
        evaluation_result: str,
        judge_type: str,
    ):
        """Helper method to update log file with evaluation result"""
        try:
            log_file = Path(log_file_path)
            # Read existing data
            with open(log_file, "r", encoding="utf-8") as f:
                log_data = json.load(f)

            # Update with evaluation result
            log_data["final_boxed_answer"] = model_boxed_answer
            log_data["final_judge_result"] = evaluation_result
            log_data["judge_type"] = judge_type

            # Write to a temporary file and then atomically replace
            temp_log_file = log_file.with_suffix(f"{log_file.suffix}.tmp")
            with open(temp_log_file, "w", encoding="utf-8") as f:
                json.dump(log_data, f, indent=2, ensure_ascii=False)

            os.replace(temp_log_file, log_file)
            print(f"    Updated log file {log_file.name} with evaluation result.")
        except Exception as e:
            print(f"    Error updating log file {log_file_path}: {e}")


class GenericEvaluator(BenchmarkEvaluator):
    """Generic benchmark evaluator for JSONL format"""

    def __init__(
        self,
        data_dir: str,
        benchmark_name: str,
        cfg: DictConfig,
        metadata_file: str = "metadata.jsonl",
        task_id_field: str = "task_id",
        question_field: str = "task_question",
        ground_truth_field: str = "ground_truth",
        file_name_field: Optional[str] = "file_name_field",
        additional_data_files: Optional[Dict[str, str]] = None,
    ):
        """
        Initialize generic evaluator

        Args:
            data_dir: Path to benchmark data directory
            benchmark_name: Name of the benchmark
            cfg: The Hydra configuration object
            metadata_file: Name of the metadata file
            task_id_field: Field name for task ID in the data
            question_field: Field name for task question in the data
            ground_truth_field: Field name for ground truth answer in the data
            file_name_field: Field name for file name in the data (optional)
            additional_data_files: Optional dict mapping metadata key to JSONL filename
                                  e.g., {"orderbook": "orderbook.jsonl", "price_history": "price_history.jsonl"}
        """
        super().__init__(data_dir=data_dir, benchmark_name=benchmark_name, cfg=cfg)
        self.metadata_file = self.data_dir / metadata_file
        self.task_id_field = task_id_field
        self.question_field = question_field
        self.ground_truth_field = ground_truth_field
        self.file_name_field = file_name_field
        self.additional_data_files = additional_data_files or {}
        self.tasks: List[BenchmarkTask] = []
        self.results: List[BenchmarkResult] = []

    def _load_additional_data(self) -> Dict[str, Dict[str, Any]]:
        """
        Load additional data files (e.g., orderbook.jsonl, price_history.jsonl)
        and index them by market_id or task_id.

        Returns:
            Dict mapping metadata key to dict of {task_id/market_id: data}
        """
        additional_data = {}
        
        for metadata_key, filename in self.additional_data_files.items():
            file_path = self.data_dir / filename
            if not file_path.exists():
                print(f"Warning: Additional data file not found: {file_path}")
                continue
            
            print(f"Loading additional data from {file_path}")
            data_dict = {}
            
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    for line in f:
                        if not line.strip():
                            continue
                        try:
                            record = json.loads(line.strip())
                            # Try to match by market_id first, then task_id
                            key = record.get("market_id") or record.get("task_id")
                            if key:
                                data_dict[key] = record
                        except json.JSONDecodeError as e:
                            print(f"Warning: Failed to parse line in {filename}: {e}")
                            continue
                
                additional_data[metadata_key] = data_dict
                print(f"Loaded {len(data_dict)} records from {filename}")
            except Exception as e:
                print(f"Warning: Failed to load {filename}: {e}")
        
        return additional_data

    def load_tasks(self, limit: Optional[int] = None) -> List[BenchmarkTask]:
        """
        Load benchmark tasks from metadata.jsonl

        Args:
            limit: Maximum number of tasks to load (None for all)

        Returns:
            List of BenchmarkTask objects
        """
        print(f"Loading tasks from {self.metadata_file}")

        if not self.metadata_file.exists():
            raise FileNotFoundError(f"Metadata file not found: {self.metadata_file}")

        # Load additional data files if specified
        additional_data = self._load_additional_data()

        tasks = []
        with open(self.metadata_file, "r", encoding="utf-8") as f:
            for i, line in enumerate(f):
                if limit and i >= limit:
                    break

                try:
                    data = json.loads(line.strip())

                    # Extract file path if specified
                    file_path = None
                    if self.file_name_field and self.file_name_field in data:
                        file_path = data[self.file_name_field]

                    # Create metadata dict with all remaining fields
                    metadata = {
                        k: v
                        for k, v in data.items()
                        if k
                        not in [
                            self.task_id_field,
                            self.question_field,
                            self.ground_truth_field,
                            self.file_name_field,
                        ]
                    }

                    # Add additional data from orderbook.jsonl, price_history.jsonl, etc.
                    # Match by market_id from metadata, or fall back to task_id
                    market_id = metadata.get("market_id")
                    task_id = data[self.task_id_field]
                    match_key = market_id or task_id
                    
                    for metadata_key, data_dict in additional_data.items():
                        if match_key in data_dict:
                            metadata[metadata_key] = data_dict[match_key]

                    task = BenchmarkTask(
                        task_id=task_id,
                        task_question=data[self.question_field],
                        ground_truth=data[self.ground_truth_field],
                        file_path=file_path,
                        metadata=metadata,
                    )
                    tasks.append(task)

                except Exception as e:
                    print(f"Warning: Failed to parse line {i + 1}: {e}")
                    continue

        gc.collect()
        self.tasks = tasks
        print(f"Loaded {len(tasks)} tasks")
        return tasks

    def prepare_task_description(
        self, task: BenchmarkTask
    ) -> Tuple[str, Optional[str]]:
        """
        Prepare task description and file path for the agent

        Args:
            task: BenchmarkTask object

        Returns:
            Tuple of (task_description, task_file_path)
        """

        task_file_path = None
        if task.file_path:
            # Build complete file path: data directory + relative path
            full_file_path = self.data_dir / task.file_path
            # Convert to absolute path and resolve any symbolic links
            task_file_path = str(full_file_path.resolve())
        else:
            task_file_path = None

        task_description = task.task_question
        end_time = task.metadata.get("end_time", "")
        if end_time:
            deadline = str(end_time).split(" ")[0]
            # Set env var — ToolManager auto-injects before_date into all search tool calls
            os.environ["SEARCH_BEFORE_DATE"] = deadline
            task_description += (
                f"\n\nIMPORTANT TIME CONSTRAINT: This event is expected to resolve around {deadline}. "
                f"You must ONLY use information that was available BEFORE {deadline}. "
                f"Do NOT use any information published on or after {deadline}. "
                f"Your goal is to PREDICT the outcome based on pre-deadline evidence, not to look up what already happened. "
                f"If you encounter any source that reveals the actual outcome or resolution result, you MUST IGNORE it and base your prediction solely on information available before {deadline}."
            )
        else:
            # Clear date filter for tasks without end_time
            os.environ.pop("SEARCH_BEFORE_DATE", None)

        return task_description, task_file_path


class CommonBenchmark:
    """Main class to run a benchmark"""

    def __init__(self, cfg: DictConfig):
        """
        Initialize the benchmark run

        Args:
            cfg: Hydra configuration object
        """
        self.cfg = cfg
        self.benchmark_name = cfg.benchmark.name
        evaluator_kwargs = cfg.benchmark.get("evaluator_kwargs", OmegaConf.create({}))
        # Support for legacy config structure
        if "metadata_file" in cfg.benchmark.data:
            evaluator_kwargs["metadata_file"] = cfg.benchmark.data.metadata_file
        if "field_mapping" in cfg.benchmark.data:
            mapping = cfg.benchmark.data.field_mapping
            if "task_id_field" in mapping:
                evaluator_kwargs["task_id_field"] = mapping.task_id_field
            if "task_question_field" in mapping:
                evaluator_kwargs["question_field"] = mapping.task_question_field
            if "ground_truth_field" in mapping:
                evaluator_kwargs["ground_truth_field"] = mapping.ground_truth_field
            if "file_name_field" in mapping:
                evaluator_kwargs["file_name_field"] = mapping.file_name_field
        if "additional_data_files" in cfg.benchmark.data:
            evaluator_kwargs["additional_data_files"] = dict(cfg.benchmark.data.additional_data_files)

        print("[debug] CommonBenchmark.__init__: creating evaluator...", flush=True)
        self.evaluator = GenericEvaluator(
            data_dir=cfg.benchmark.data.data_dir,
            benchmark_name=self.benchmark_name,
            cfg=cfg,
            **evaluator_kwargs,
        )
        print("[debug] CommonBenchmark.__init__: evaluator created", flush=True)

    def run_evaluation(self) -> float:
        """
        Run the full benchmark evaluation process
        """
        print(f"[debug] Starting evaluation for benchmark: {self.benchmark_name}", flush=True)
        print(f"[debug] LLM Provider: {self.evaluator.llm_provider}", flush=True)
        print(f"[debug] LLM Model: {self.evaluator.llm_model}", flush=True)

        # Load tasks
        print("[debug] load_tasks: begin", flush=True)
        self.evaluator.load_tasks(limit=self.cfg.benchmark.execution.max_tasks)
        print("[debug] load_tasks: done", flush=True)
        if not self.evaluator.tasks:
            print("[debug] No tasks loaded. Exiting.", flush=True)
            return 0.0

        # Run inference
        max_concurrent = int(self.cfg.benchmark.execution.max_concurrent)
        if max_concurrent <= 1:
            print("\n[debug] Starting sequential inference with max_concurrent=1 ...", flush=True)
        else:
            print(f"\n[debug] Starting parallel inference with {max_concurrent} concurrent tasks...", flush=True)
        print(f"[debug] Using pass@{self.evaluator.pass_at_k} evaluation...", flush=True)

        print("[debug] inference: begin", flush=True)
        self.evaluator.run_parallel_inference(self.evaluator.tasks, max_concurrent=max_concurrent)
        print("[debug] inference: done", flush=True)

        # Evaluate accuracy
        print("[debug] Evaluating accuracy...", flush=True)
        accuracy = self.evaluator.evaluate_accuracy()
        print(f"\n[debug] Overall pass@{self.evaluator.pass_at_k} accuracy: {accuracy:.2%}", flush=True)
        # Save results

        # Construct the full path in the correct log directory
        log_dir = self.evaluator.get_log_dir()
        results_path = log_dir / "benchmark_results.jsonl"

        self.evaluator.save_results(str(results_path))
        print(f"\nEvaluation completed! Results saved to {results_path}")

        # save accuracy to a file
        accuracy_file = str(results_path).replace(
            ".jsonl", f"_pass_at_{self.evaluator.pass_at_k}_accuracy.txt"
        )
        with open(accuracy_file, "w") as f:
            f.write(f"{accuracy:.2%}")
        # Generate and save summary
        generate_summary(log_dir)
        return accuracy


@hydra.main(config_path="../conf", config_name="config", version_base=None)
def run_benchmark(cfg: DictConfig) -> None:
    """
    Main entry point for running benchmarks with Hydra.
    """
    print("[debug] run_benchmark: entered hydra main", flush=True)
    print("Benchmark configuration:\n", OmegaConf.to_yaml(cfg.benchmark), flush=True)

    print("[debug] run_benchmark: constructing CommonBenchmark", flush=True)
    benchmark = CommonBenchmark(cfg)
    print("[debug] run_benchmark: running evaluation", flush=True)
    benchmark.run_evaluation()
    print("[debug] run_benchmark: done", flush=True)


if __name__ == "__main__":
    run_benchmark()
