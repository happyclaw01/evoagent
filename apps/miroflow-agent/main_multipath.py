# Copyright (c) 2025 MiroMind
# Multi-Path Agent Entry Point (EvoAgent Layer 1)
#
# EA-001: Runs the same task through N parallel agent paths with different strategies,
#          then votes on the best answer.
# EA-008: Path count configurable via NUM_PATHS env var or num_paths Hydra override.
#
# Usage:
#   uv run python main_multipath.py llm=openrouter-local agent=single_agent
#   uv run python main_multipath.py llm=openrouter-local agent=single_agent num_paths=2

import asyncio
import os

import hydra
from omegaconf import DictConfig, OmegaConf

from src.core.pipeline import (
    create_pipeline_components,
    execute_multi_path_task_pipeline,
)
from src.logging.task_logger import bootstrap_logger

logger = bootstrap_logger()


async def amain(cfg: DictConfig) -> None:
    """Asynchronous main function for multi-path execution."""

    logger.info(OmegaConf.to_yaml(cfg))

    # Create pipeline components
    main_agent_tool_manager, sub_agent_tool_managers, output_formatter = (
        create_pipeline_components(cfg)
    )

    # Task parameters
    task_id = "task_multipath_demo"
    task_description = "What is the title of today's arxiv paper in computer science?"
    task_file_name = ""

    # EA-008: Number of parallel paths (from env or default 3)
    num_paths = int(os.environ.get("NUM_PATHS", "3"))
    
    # EA-009: Early stopping configuration
    early_stop_k = int(os.environ.get("EARLY_STOP_K", "2"))
    early_stop_threshold = float(os.environ.get("EARLY_STOP_THRESHOLD", "1.0"))

    logger.info(f"Running multi-path pipeline with {num_paths} paths, early_stop_k={early_stop_k}, threshold={early_stop_threshold}")

    # Execute multi-path pipeline
    final_summary, final_boxed_answer, log_file_path = (
        await execute_multi_path_task_pipeline(
            cfg=cfg,
            task_id=task_id,
            task_file_name=task_file_name,
            task_description=task_description,
            main_agent_tool_manager=main_agent_tool_manager,
            sub_agent_tool_managers=sub_agent_tool_managers,
            output_formatter=output_formatter,
            log_dir=cfg.debug_dir,
            num_paths=num_paths,
            early_stop_k=early_stop_k,
            early_stop_threshold=early_stop_threshold,
        )
    )

    logger.info(f"Final answer: {final_boxed_answer}")
    logger.info(f"Log saved to: {log_file_path}")


@hydra.main(config_path="conf", config_name="config", version_base=None)
def main(cfg: DictConfig) -> None:
    asyncio.run(amain(cfg))


if __name__ == "__main__":
    main()
