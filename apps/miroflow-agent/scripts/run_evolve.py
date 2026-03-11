#!/usr/bin/env python
"""
Self-Evolving: Run strategy evolution on an existing experience store.

This script reads accumulated experiences, aggregates strategy preferences
and failure patterns, and optionally generates prompt patches via LLM.

Usage:
    # Aggregate only (no LLM call):
    python scripts/run_evolve.py \
        --experience_file ../../data/experiences.jsonl \
        --preferences_file ../../data/strategy_preferences.json

    # Full evolution with prompt patch generation:
    python scripts/run_evolve.py \
        --experience_file ../../data/experiences.jsonl \
        --preferences_file ../../data/strategy_preferences.json \
        --overrides_file ../../data/prompt_overrides.jsonl \
        --model gpt-5 \
        --generate-patches

    # Auto-approve patches (for fully automated experiments):
    python scripts/run_evolve.py ... --generate-patches --auto-approve

    # Approve a specific patch by index:
    python scripts/run_evolve.py ... --approve 0

    # Rollback a specific patch by index:
    python scripts/run_evolve.py ... --rollback 2
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

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.evolving.experience_store import ExperienceStore
from src.evolving.strategy_evolver import StrategyEvolver

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def print_preferences(prefs: dict) -> None:
    stats = prefs.get("stats", {})
    recs = prefs.get("recommendations", {})
    print(f"\n=== Strategy Preferences ({len(stats)} question types) ===")
    for qt, strategies in stats.items():
        print(f"\n  [{qt}]")
        for sn, s in strategies.items():
            print(f"    {sn}: {s['correct']}/{s['total']} = {s['accuracy']:.0%}")
        rec = recs.get(qt, [])
        if isinstance(rec, list) and rec:
            print(f"    >> Recommended: {', '.join(rec)}")
        elif rec == "insufficient_data":
            print(f"    >> (insufficient data)")
        else:
            print(f"    >> (no strategy meets threshold)")


def print_failure_patterns(failures: dict) -> None:
    print(f"\n=== Failure Patterns ({len(failures)} question types) ===")
    for qt, data in failures.items():
        print(f"\n  [{qt}]")
        for f in data.get("top_failures", []):
            print(f"    {f['pattern']} ({f['count']}x): {f['typical_lesson'][:80]}")


def print_patches(patches: list[dict], label: str = "Generated") -> None:
    print(f"\n=== {label} Prompt Patches ({len(patches)}) ===")
    for i, p in enumerate(patches):
        approved = "APPROVED" if p.get("auto_approved") else "PENDING"
        applied = " APPLIED" if p.get("applied") else ""
        print(f"\n  [{i}] {p.get('question_type', '?')} [{approved}{applied}]")
        print(f"      Trigger: {p.get('trigger', '?')}")
        content = p.get("content", "")
        for line in content.split("\n"):
            print(f"      {line}")


async def _run(args) -> None:
    store = ExperienceStore(args.experience_file)
    store_stats = store.stats()
    print(
        f"Experience store: {store_stats['total']} total, "
        f"{store_stats['correct']} correct, {store_stats['incorrect']} incorrect"
    )

    evolver = StrategyEvolver(
        experience_store=store,
        preferences_file=args.preferences_file,
        prompt_overrides_file=args.overrides_file,
        min_samples=args.min_samples,
        failure_threshold=args.failure_threshold,
    )

    if args.approve is not None:
        evolver.approve_patch(args.approve)
        print(f"Approved patch #{args.approve}")
        return

    if args.rollback is not None:
        evolver.rollback_patch(args.rollback)
        print(f"Rolled back patch #{args.rollback}")
        return

    prefs = evolver.aggregate_strategy_preferences()
    print_preferences(prefs)

    failures = evolver.aggregate_failure_patterns()
    print_failure_patterns(failures)

    if args.generate_patches:
        from openai import AsyncOpenAI

        api_key = args.api_key or os.environ.get("OPENAI_API_KEY", "")
        base_url = args.base_url or os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1")
        llm_client = AsyncOpenAI(api_key=api_key, base_url=base_url)

        patches = await evolver.generate_prompt_patches(
            llm_client=llm_client,
            model=args.model,
            auto_approve=args.auto_approve,
        )
        if patches:
            print_patches(patches)
        else:
            print("\nNo prompt patches needed (no question types below failure threshold).")
    else:
        existing = evolver._load_all_overrides()
        if existing:
            print_patches(existing, label="Existing")


def main():
    parser = argparse.ArgumentParser(
        description="Run strategy evolution on existing experiences"
    )
    parser.add_argument(
        "--experience_file", default="../../data/experiences.jsonl",
        help="Path to experiences.jsonl",
    )
    parser.add_argument(
        "--preferences_file", default="../../data/strategy_preferences.json",
        help="Output path for strategy preferences JSON",
    )
    parser.add_argument(
        "--overrides_file", default="../../data/prompt_overrides.jsonl",
        help="Path for prompt overrides JSONL",
    )
    parser.add_argument("--model", default="", help="LLM model for patch generation")
    parser.add_argument("--api_key", default="", help="API key")
    parser.add_argument("--base_url", default="", help="Base URL")
    parser.add_argument("--min_samples", type=int, default=3,
                        help="Min samples for strategy recommendation")
    parser.add_argument("--failure_threshold", type=float, default=0.4,
                        help="Accuracy threshold for patch trigger")
    parser.add_argument("--generate-patches", action="store_true",
                        help="Generate prompt patches via LLM")
    parser.add_argument("--auto-approve", action="store_true",
                        help="Auto-approve generated patches")
    parser.add_argument("--approve", type=int, default=None, metavar="INDEX",
                        help="Approve a specific patch by index")
    parser.add_argument("--rollback", type=int, default=None, metavar="INDEX",
                        help="Rollback a specific patch by index")
    args = parser.parse_args()

    asyncio.run(_run(args))


if __name__ == "__main__":
    main()
