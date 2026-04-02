#!/usr/bin/env python3
"""
Run EvoAgent on a single prediction question (interactive mode).

Usage:
    cd apps/miroflow-agent
    PYTHONPATH=.:benchmarks python scripts/run_single_question.py \
        --question "Who will win: JDG vs GEN in LoL Vanguard Series tonight?" \
        [--evolving] \
        [--experience_file ../../data/cat10_r4_experiences.jsonl] \
        [--num_paths 3] \
        [--llm openrouter_gpt5] \
        [--agent single_agent_futurex]
"""

import argparse
import asyncio
import json
import logging
import os
import sys
import uuid
from datetime import datetime, timezone, timedelta
from pathlib import Path

# Add parent dirs to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "benchmarks"))

from dotenv import load_dotenv
load_dotenv()

import hydra
from omegaconf import DictConfig, OmegaConf


logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s][%(name)s][%(levelname)s] - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("single_question")


async def run_question(cfg: DictConfig, question: str, log_dir: str, num_paths: int):
    """Run a single question through the multi-path pipeline."""
    from src.core.pipeline import (
        create_pipeline_components,
        execute_multi_path_task_pipeline,
        execute_task_pipeline,
    )

    task_id = f"interactive_{uuid.uuid4().hex[:8]}"

    # Wrap question in the futurex prediction prompt format
    task_description = f"""You are an agent that can predict future events. The event to be predicted: "{question}"
        IMPORTANT: Your final answer MUST end with this exact format:
        \\boxed{{YourAnswer}}
        Do not use any other format. Do not refuse to make a prediction. Do not say "I cannot predict the future." You must make a clear prediction based on the best data currently available, using the box format specified above.

Use web search to gather the latest information before making your prediction. Search for recent news, odds, expert analyses, team form, and any relevant data."""

    logger.info(f"Task ID: {task_id}")
    logger.info(f"Question: {question}")
    logger.info(f"Num paths: {num_paths}")
    logger.info(f"Evolving: {cfg.get('evolving', {}).get('enabled', False)}")

    # Create pipeline components
    main_tm, sub_tms, output_fmt = create_pipeline_components(cfg)

    try:
        if num_paths > 1:
            summary, answer, log_path = await execute_multi_path_task_pipeline(
                cfg=cfg,
                task_id=f"{task_id}_attempt-1_format-retry-0",
                task_file_name="",
                task_description=task_description,
                main_agent_tool_manager=main_tm,
                sub_agent_tool_managers=sub_tms,
                output_formatter=output_fmt,
                ground_truth=None,
                log_dir=log_dir,
                num_paths=num_paths,
                early_stop_k=2,
                early_stop_threshold=1.0,
            )
        else:
            summary, answer, log_path = await execute_task_pipeline(
                cfg=cfg,
                task_id=f"{task_id}_attempt-1_format-retry-0",
                task_file_name="",
                task_description=task_description,
                main_agent_tool_manager=main_tm,
                sub_agent_tool_managers=sub_tms,
                output_formatter=output_fmt,
                ground_truth=None,
                log_dir=log_dir,
            )

        print("\n" + "=" * 60)
        print(f"🎯 PREDICTION RESULT")
        print("=" * 60)
        print(f"Question: {question}")
        print(f"Answer:   {answer}")
        print(f"Log:      {log_path}")
        print("=" * 60)

        # Print summary (truncated)
        if summary:
            print(f"\n📝 Summary:\n{summary[:2000]}")

        return answer, log_path

    except Exception as e:
        logger.error(f"Pipeline failed: {e}", exc_info=True)
        raise
    finally:
        if hasattr(main_tm, 'cleanup'):
            await main_tm.cleanup()
        elif hasattr(main_tm, 'close'):
            await main_tm.close()
        for sm in sub_tms.values():
            if hasattr(sm, 'cleanup'):
                await sm.cleanup()
            elif hasattr(sm, 'close'):
                await sm.close()


def main():
    parser = argparse.ArgumentParser(description="Run EvoAgent on a single question")
    parser.add_argument("--question", "-q", required=True, help="The prediction question")
    parser.add_argument("--evolving", action="store_true", help="Enable experience injection")
    parser.add_argument("--experience_file", default="../../data/cat10_r4_experiences.jsonl",
                        help="Path to experience JSONL file")
    parser.add_argument("--num_paths", type=int, default=3, help="Number of parallel paths")
    parser.add_argument("--llm", default="openrouter_gpt5", help="LLM config name")
    parser.add_argument("--agent", default="single_agent_futurex", help="Agent config name")
    parser.add_argument("--log_dir", default="../../logs/interactive", help="Log output dir")
    args = parser.parse_args()

    # Build Hydra config manually via compose API
    from hydra import compose, initialize_config_dir
    from hydra.core.global_hydra import GlobalHydra

    GlobalHydra.instance().clear()

    config_dir = str(Path(__file__).resolve().parent.parent / "conf")

    with initialize_config_dir(config_dir=config_dir, version_base=None):
        overrides = [
            f"llm={args.llm}",
            f"agent={args.agent}",
            "benchmark=futurex_cat10",
            f"evolving.enabled={'true' if args.evolving else 'false'}",
            "question_parser.enabled=true",
            "+openviking.enabled=true",
            "+openviking.server_url=http://localhost:1933",
            "+storage.openviking.enabled=true",
            "+pipeline.auto_reflect=false",
        ]
        if args.evolving:
            overrides.append(f"evolving.experience_file={args.experience_file}")

        cfg = compose(config_name="config", overrides=overrides)

    # Ensure log dir exists
    log_dir = str(Path(args.log_dir).resolve()) if os.path.isabs(args.log_dir) else \
              str((Path(__file__).resolve().parent.parent / args.log_dir).resolve())
    os.makedirs(log_dir, exist_ok=True)

    logger.info(f"Log dir: {log_dir}")

    # Run
    answer, log_path = asyncio.run(run_question(cfg, args.question, log_dir, args.num_paths))

    return 0 if answer else 1


if __name__ == "__main__":
    sys.exit(main())
