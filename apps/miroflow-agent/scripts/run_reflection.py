#!/usr/bin/env python
"""
Self-Evolving: Run reflection on completed task logs to generate experiences.

Usage:
    python scripts/run_reflection.py \
        --log_dir ../../logs/futurex/0305/online_openai_openai/gpt-5-2025-08-07_single_agent_keep5 \
        --ground_truth_file ../../data/futurex/online_data.jsonl \
        --output ../../data/experiences.jsonl \
        --model gpt-5

    # With strategy evolution after reflection:
    python scripts/run_reflection.py \
        --log_dir ... --ground_truth_file ... --output ... \
        --evolve --auto-approve

This reads all task log JSONs from log_dir, matches them with ground truths,
and calls the LLM to reflect on each task. Results are written to the output
file via ExperienceStore (with task_id deduplication).

When --evolve is given, strategy preference aggregation and prompt patch
generation are run automatically after reflection completes.
"""

import argparse
import asyncio
import json
import logging
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.evolving.experience_store import ExperienceStore
from src.evolving.reflector import reflect_on_batch

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

DEFAULT_PREFERENCES_FILE = "../../data/strategy_preferences.json"
DEFAULT_OVERRIDES_FILE = "../../data/prompt_overrides.jsonl"


def load_ground_truths(gt_file: str) -> dict:
    """Load ground truths from a JSONL file. Returns task_id -> ground_truth mapping."""
    gt_map = {}
    with open(gt_file, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            entry = json.loads(line)
            task_id = entry.get("task_id", "")
            gt = entry.get("ground_truth")
            if task_id and gt is not None:
                gt_map[task_id] = gt
    logger.info(f"Loaded {len(gt_map)} ground truths from {gt_file}")
    return gt_map


async def _run(args) -> None:
    from openai import AsyncOpenAI

    api_key = args.api_key or os.environ.get("OPENAI_API_KEY", "")
    base_url = args.base_url or os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1")
    llm_client = AsyncOpenAI(api_key=api_key, base_url=base_url)

    store = ExperienceStore(args.output)

    gt_map = load_ground_truths(args.ground_truth_file)
    if not gt_map:
        logger.warning("No ground truths with non-null values found. Nothing to reflect on.")
        return

    experiences = await reflect_on_batch(
        log_dir=args.log_dir,
        ground_truths=gt_map,
        experience_store=store,
        llm_client=llm_client,
        model=args.model,
    )

    if experiences:
        correct = sum(1 for e in experiences if e["was_correct"])
        print(
            f"\nReflection done. {len(experiences)} experiences generated "
            f"({correct} correct, {len(experiences) - correct} incorrect)"
        )
        print(f"Saved to: {args.output}")
    else:
        print("No experiences generated (no matching logs with ground truths found)")

    if args.evolve:
        from src.evolving.strategy_evolver import StrategyEvolver

        prefs_file = args.preferences_file or DEFAULT_PREFERENCES_FILE
        overrides_file = args.overrides_file or DEFAULT_OVERRIDES_FILE

        evolver = StrategyEvolver(
            experience_store=store,
            preferences_file=prefs_file,
            prompt_overrides_file=overrides_file,
        )

        print("\n--- Strategy Evolution ---")
        prefs = evolver.aggregate_strategy_preferences()
        print(f"Strategy preferences: {len(prefs.get('stats', {}))} question types")
        for qt, recs in prefs.get("recommendations", {}).items():
            print(f"  {qt}: {recs}")

        patches = await evolver.generate_prompt_patches(
            llm_client=llm_client,
            model=args.model,
            auto_approve=args.auto_approve,
        )
        if patches:
            print(f"\nGenerated {len(patches)} prompt patches:")
            for i, p in enumerate(patches):
                status = "AUTO-APPROVED" if p["auto_approved"] else "PENDING REVIEW"
                print(f"  [{i}] {p['question_type']} ({status}): {p['content'][:80]}...")
        else:
            print("No prompt patches needed.")


def main():
    parser = argparse.ArgumentParser(description="Run reflection on task logs")
    parser.add_argument("--log_dir", required=True, help="Directory containing task log JSONs")
    parser.add_argument("--ground_truth_file", required=True, help="JSONL file with ground truths")
    parser.add_argument("--output", default="../../data/experiences.jsonl", help="Output experiences file")
    parser.add_argument("--model", default="", help="LLM model for reflection (empty = client default)")
    parser.add_argument("--api_key", default="", help="API key (falls back to OPENAI_API_KEY env var)")
    parser.add_argument("--base_url", default="", help="Base URL (falls back to OPENAI_BASE_URL env var)")
    parser.add_argument("--evolve", action="store_true",
                        help="After reflection, run strategy aggregation and prompt patch generation")
    parser.add_argument("--auto-approve", action="store_true",
                        help="Auto-approve generated prompt patches (only with --evolve)")
    parser.add_argument("--preferences_file", default="", help="Strategy preferences output file")
    parser.add_argument("--overrides_file", default="", help="Prompt overrides output file")
    args = parser.parse_args()

    asyncio.run(_run(args))


if __name__ == "__main__":
    main()
