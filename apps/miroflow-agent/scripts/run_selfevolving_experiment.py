#!/usr/bin/env python
"""
Self-Evolving Experiment: Multi-round evaluation with interleaved reflection.

Workflow:
  Round 1: sample 50 questions (proportional by level) → evaluate → reflect + evolve
  Round 2-5: sample 30 questions each → evaluate → reflect + evolve
  Final: report accuracy trend across all rounds.

Usage:
    cd apps/miroflow-agent
    python scripts/run_selfevolving_experiment.py \
        --data_file ../../data/futurex/standardized_data_250924_250930.jsonl \
        --model gpt-5 \
        --rounds 5 \
        --first_round_size 50 \
        --later_round_size 30 \
        [--max_concurrent 3] \
        [--seed 42] \
        [--dry_run]
"""

import argparse
import asyncio
import json
import logging
import os
import random
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)
logger = logging.getLogger("selfevolving_experiment")

# ---------------------------------------------------------------------------
# Data loading & stratified sampling
# ---------------------------------------------------------------------------


def load_all_questions(data_file: str) -> list[dict]:
    """Load all questions from a JSONL file."""
    questions = []
    with open(data_file, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            questions.append(json.loads(line))
    logger.info(f"Loaded {len(questions)} questions from {data_file}")
    return questions


def stratified_sample(
    questions: list[dict],
    n: int,
    exclude_ids: set[str] | None = None,
    seed: int | None = None,
) -> list[dict]:
    """Sample n questions with proportional level distribution.

    Proportions are based on the distribution in the *full* question pool
    (not the remaining pool), so every round targets the same level mix.
    """
    if exclude_ids is None:
        exclude_ids = set()

    # Full-pool level distribution (for target proportions)
    full_level_counts = Counter(q.get("level", 2) for q in questions)
    total_full = len(questions)

    # Available pool
    available = [q for q in questions if q.get("task_id", "") not in exclude_ids]
    if len(available) < n:
        logger.warning(
            f"Only {len(available)} questions available (requested {n}), using all."
        )
        return available

    by_level: dict[int, list[dict]] = defaultdict(list)
    for q in available:
        by_level[q.get("level", 2)].append(q)

    rng = random.Random(seed)

    # Compute target count per level
    targets: dict[int, int] = {}
    allocated = 0
    levels_sorted = sorted(full_level_counts.keys())
    for i, lvl in enumerate(levels_sorted):
        if i == len(levels_sorted) - 1:
            targets[lvl] = n - allocated  # remainder goes to last level
        else:
            t = round(n * full_level_counts[lvl] / total_full)
            t = min(t, len(by_level.get(lvl, [])))
            targets[lvl] = t
            allocated += t

    sampled: list[dict] = []
    for lvl in levels_sorted:
        pool = by_level.get(lvl, [])
        take = min(targets.get(lvl, 0), len(pool))
        sampled.extend(rng.sample(pool, take))

    # If we're short (due to rounding or small pools), fill from remaining
    sampled_ids = {q["task_id"] for q in sampled}
    remaining = [q for q in available if q["task_id"] not in sampled_ids]
    rng.shuffle(remaining)
    while len(sampled) < n and remaining:
        sampled.append(remaining.pop())

    rng.shuffle(sampled)  # shuffle final order

    level_dist = Counter(q.get("level", 2) for q in sampled)
    logger.info(
        f"Sampled {len(sampled)} questions. Level distribution: "
        + ", ".join(f"L{k}={v}" for k, v in sorted(level_dist.items()))
    )
    return sampled


# ---------------------------------------------------------------------------
# Round execution: benchmark + evaluate + reflect + evolve
# ---------------------------------------------------------------------------


async def run_benchmark_round(
    round_num: int,
    questions: list[dict],
    cfg_overrides: dict,
    experiment_dir: Path,
    dry_run: bool = False,
) -> list[dict]:
    """Run one round of benchmark evaluation.

    Returns list of result dicts with at minimum:
        task_id, ground_truth, model_boxed_answer, is_correct, level
    """
    round_dir = experiment_dir / f"round_{round_num}"
    round_dir.mkdir(parents=True, exist_ok=True)

    # Write the round's question subset as a JSONL (so benchmark can load it)
    subset_file = round_dir / "subset.jsonl"
    with open(subset_file, "w", encoding="utf-8") as f:
        for q in questions:
            f.write(json.dumps(q, ensure_ascii=False) + "\n")

    results_file = round_dir / "results.jsonl"
    log_dir = round_dir / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)

    if dry_run:
        # Simulate results for testing the script flow
        results = []
        for q in questions:
            is_correct = random.random() < 0.35  # ~35% baseline
            results.append({
                "task_id": q["task_id"],
                "ground_truth": q.get("ground_truth", ""),
                "model_boxed_answer": q.get("ground_truth", "") if is_correct else "WRONG",
                "is_correct": is_correct,
                "level": q.get("level", 2),
                "status": "success",
            })
        # Save simulated results
        with open(results_file, "w", encoding="utf-8") as f:
            for r in results:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        logger.info(f"[DRY RUN] Round {round_num}: simulated {len(results)} results")
        return results

    # --- Real benchmark execution via Hydra + CommonBenchmark ---
    import hydra
    from omegaconf import OmegaConf

    # Load base config
    config_dir = Path(__file__).resolve().parent.parent / "conf"

    with hydra.initialize_config_dir(config_dir=str(config_dir), version_base=None):
        cfg = hydra.compose(
            config_name="config",
            overrides=[
                f"benchmark=futurex",
                f"hydra.run.dir={str(round_dir)}",
                f"benchmark.execution.max_concurrent={cfg_overrides.get('max_concurrent', 3)}",
                f"benchmark.execution.pass_at_k=1",
                f"benchmark.execution.format_error_retry_limit=1",
                f"evolving.enabled={cfg_overrides.get('evolving_enabled', 'true')}",
                f"evolving.experience_file={cfg_overrides.get('experience_file', '')}",
                f"evolving.strategy_preferences_file={cfg_overrides.get('preferences_file', '')}",
                f"evolving.prompt_overrides_file={cfg_overrides.get('overrides_file', '')}",
                f"evolving.auto_reflect=false",  # We reflect in batch after the round
            ] + cfg_overrides.get("extra_overrides", []),
        )

    from benchmarks.common_benchmark import BenchmarkTask, GenericEvaluator

    evaluator = GenericEvaluator(
        data_dir=str(round_dir),
        benchmark_name="futurex",
        cfg=cfg,
        metadata_file="subset.jsonl",
    )

    tasks = evaluator.load_tasks()
    logger.info(f"Round {round_num}: running {len(tasks)} tasks...")

    max_concurrent = cfg_overrides.get("max_concurrent", 3)
    eval_results = evaluator.run_parallel_inference(tasks, max_concurrent=max_concurrent)

    accuracy = evaluator.evaluate_accuracy()
    evaluator.save_results(str(results_file))

    # Convert to simple dicts
    results = []
    for r in eval_results:
        results.append({
            "task_id": r.task_id,
            "ground_truth": r.ground_truth,
            "model_boxed_answer": r.model_boxed_answer,
            "is_correct": r.pass_at_k_success,
            "level": next(
                (q.get("level", 2) for q in questions if q["task_id"] == r.task_id),
                2,
            ),
            "status": r.status,
            "log_file_path": r.log_file_path,
        })

    return results


async def run_reflection_round(
    round_num: int,
    results: list[dict],
    experiment_dir: Path,
    experience_file: str,
    model: str,
    dry_run: bool = False,
) -> int:
    """Run batch reflection on round results. Returns number of experiences generated."""
    if dry_run:
        # Simulate generating experiences
        from src.evolving.experience_store import ExperienceStore

        store = ExperienceStore(experience_file)
        for r in results:
            exp = {
                "task_id": r["task_id"],
                "question_type": "simulated",
                "level": r.get("level", 2),
                "question_summary": f"Task {r['task_id']}",
                "was_correct": r["is_correct"],
                "lesson": "Simulated lesson for dry run.",
                "failure_pattern": None if r["is_correct"] else "simulated_failure",
                "search_strategy": "simulated",
                "reasoning_type": "info_retrieval",
                "knowledge_domain": "other",
                "tools_used": ["web_search"],
                "strategy_name": "search_heavy",
            }
            store.add(exp)
        logger.info(f"[DRY RUN] Round {round_num}: generated {len(results)} simulated experiences")
        return len(results)

    # Real reflection using LLM
    round_dir = experiment_dir / f"round_{round_num}"
    log_dir = round_dir / "logs"

    from openai import AsyncOpenAI

    api_key = os.environ.get("OPENAI_API_KEY", "")
    base_url = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1")
    llm_client = AsyncOpenAI(api_key=api_key, base_url=base_url)

    from src.evolving.experience_store import ExperienceStore
    from src.evolving.reflector import reflect_on_batch

    store = ExperienceStore(experience_file)

    # Build ground_truth map from results
    gt_map = {r["task_id"]: r["ground_truth"] for r in results}

    # reflect_on_batch expects log_dir with .json files
    # The task logs should already be saved in log_dir by the benchmark
    experiences = await reflect_on_batch(
        log_dir=str(log_dir) if log_dir.exists() else str(round_dir),
        ground_truths=gt_map,
        experience_store=store,
        llm_client=llm_client,
        model=model,
    )

    correct = sum(1 for e in experiences if e.get("was_correct"))
    logger.info(
        f"Round {round_num} reflection: {len(experiences)} experiences "
        f"({correct} correct, {len(experiences) - correct} incorrect)"
    )
    return len(experiences)


async def run_evolution(
    round_num: int,
    experience_file: str,
    preferences_file: str,
    overrides_file: str,
    model: str,
    dry_run: bool = False,
) -> None:
    """Run strategy evolution: aggregate preferences + generate prompt patches."""
    from src.evolving.experience_store import ExperienceStore
    from src.evolving.strategy_evolver import StrategyEvolver

    store = ExperienceStore(experience_file)
    evolver = StrategyEvolver(
        experience_store=store,
        preferences_file=preferences_file,
        prompt_overrides_file=overrides_file,
    )

    prefs = evolver.aggregate_strategy_preferences()
    failures = evolver.aggregate_failure_patterns()

    logger.info(
        f"Round {round_num} evolution: "
        f"{len(prefs.get('stats', {}))} question types, "
        f"{len(failures)} types with failures"
    )

    if dry_run:
        logger.info(f"[DRY RUN] Skipping prompt patch generation")
        return

    from openai import AsyncOpenAI

    api_key = os.environ.get("OPENAI_API_KEY", "")
    base_url = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1")
    llm_client = AsyncOpenAI(api_key=api_key, base_url=base_url)

    patches = await evolver.generate_prompt_patches(
        llm_client=llm_client,
        model=model,
        auto_approve=True,  # auto-approve for experiments
    )
    if patches:
        logger.info(f"Generated {len(patches)} prompt patches (auto-approved)")
    else:
        logger.info("No prompt patches needed this round.")


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------


def compute_round_stats(results: list[dict]) -> dict:
    """Compute accuracy stats for a single round."""
    total = len(results)
    correct = sum(1 for r in results if r.get("is_correct"))
    by_level: dict[int, dict] = defaultdict(lambda: {"total": 0, "correct": 0})
    for r in results:
        lvl = r.get("level", 2)
        by_level[lvl]["total"] += 1
        if r.get("is_correct"):
            by_level[lvl]["correct"] += 1

    level_acc = {}
    for lvl, counts in sorted(by_level.items()):
        acc = counts["correct"] / counts["total"] if counts["total"] > 0 else 0
        level_acc[f"L{lvl}"] = {
            "correct": counts["correct"],
            "total": counts["total"],
            "accuracy": round(acc, 4),
        }

    return {
        "total": total,
        "correct": correct,
        "accuracy": round(correct / total, 4) if total > 0 else 0,
        "by_level": level_acc,
    }


def print_experiment_report(all_round_stats: list[dict], experiment_dir: Path) -> None:
    """Print final experiment report and save to file."""
    lines = []
    lines.append("=" * 70)
    lines.append("  SELF-EVOLVING EXPERIMENT REPORT")
    lines.append("=" * 70)
    lines.append("")

    for i, stats in enumerate(all_round_stats):
        round_num = i + 1
        evolving_label = "baseline (no experiences)" if round_num == 1 else f"with {round_num - 1} rounds of self-evolving"
        lines.append(f"Round {round_num} ({evolving_label}):")
        lines.append(f"  Overall: {stats['correct']}/{stats['total']} = {stats['accuracy']:.2%}")
        for lvl_key, lvl_data in stats["by_level"].items():
            lines.append(
                f"  {lvl_key}: {lvl_data['correct']}/{lvl_data['total']} = {lvl_data['accuracy']:.2%}"
            )
        lines.append("")

    # Trend summary
    lines.append("-" * 70)
    lines.append("Accuracy Trend:")
    accuracies = [s["accuracy"] for s in all_round_stats]
    for i, acc in enumerate(accuracies):
        bar = "#" * int(acc * 50)
        delta = ""
        if i > 0:
            diff = acc - accuracies[0]
            delta = f"  ({'+' if diff >= 0 else ''}{diff:.2%} vs baseline)"
        lines.append(f"  Round {i+1}: {acc:.2%} |{bar}|{delta}")

    lines.append("")
    if len(accuracies) >= 2:
        improvement = accuracies[-1] - accuracies[0]
        lines.append(
            f"Net improvement: {'+' if improvement >= 0 else ''}{improvement:.2%} "
            f"({accuracies[0]:.2%} → {accuracies[-1]:.2%})"
        )
    lines.append("=" * 70)

    report_text = "\n".join(lines)
    print(report_text)

    # Save report
    report_file = experiment_dir / "experiment_report.txt"
    with open(report_file, "w", encoding="utf-8") as f:
        f.write(report_text)
    logger.info(f"Report saved to {report_file}")

    # Save structured results as JSON
    summary_file = experiment_dir / "experiment_summary.json"
    with open(summary_file, "w", encoding="utf-8") as f:
        json.dump(
            {
                "rounds": all_round_stats,
                "accuracy_trend": accuracies,
                "net_improvement": accuracies[-1] - accuracies[0] if len(accuracies) >= 2 else 0,
            },
            f,
            indent=2,
            ensure_ascii=False,
        )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


async def main_async(args):
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    experiment_dir = Path(args.experiment_dir) / f"selfevolving_{timestamp}"
    experiment_dir.mkdir(parents=True, exist_ok=True)

    # Experience / evolution file paths for this experiment
    experience_file = str(experiment_dir / "experiences.jsonl")
    preferences_file = str(experiment_dir / "strategy_preferences.json")
    overrides_file = str(experiment_dir / "prompt_overrides.jsonl")

    logger.info(f"Experiment directory: {experiment_dir}")
    logger.info(f"Data file: {args.data_file}")
    logger.info(f"Rounds: {args.rounds}, first={args.first_round_size}, later={args.later_round_size}")

    # Load all questions
    all_questions = load_all_questions(args.data_file)

    all_round_stats = []
    all_used_ids: set[str] = set()
    seed_base = args.seed

    cfg_overrides = {
        "max_concurrent": args.max_concurrent,
        "experience_file": experience_file,
        "preferences_file": preferences_file,
        "overrides_file": overrides_file,
        "extra_overrides": args.extra_overrides if args.extra_overrides else [],
    }

    for round_num in range(1, args.rounds + 1):
        round_start = time.time()
        n = args.first_round_size if round_num == 1 else args.later_round_size
        seed = seed_base + round_num if seed_base is not None else None

        logger.info(f"\n{'='*60}")
        logger.info(f"ROUND {round_num}/{args.rounds} — sampling {n} questions")
        logger.info(f"{'='*60}")

        # For round 1: no evolving (baseline). For later rounds: enable evolving.
        cfg_overrides["evolving_enabled"] = "true" if round_num > 1 else "false"

        # Sample questions (allow re-sampling across rounds for variety)
        # But avoid exact duplicates within the same experiment
        questions = stratified_sample(
            all_questions,
            n,
            exclude_ids=all_used_ids if args.no_repeat else None,
            seed=seed,
        )
        all_used_ids.update(q["task_id"] for q in questions)

        # --- Step 1: Evaluate ---
        logger.info(f"Step 1: Running benchmark evaluation...")
        results = await run_benchmark_round(
            round_num=round_num,
            questions=questions,
            cfg_overrides=cfg_overrides,
            experiment_dir=experiment_dir,
            dry_run=args.dry_run,
        )

        stats = compute_round_stats(results)
        all_round_stats.append(stats)
        logger.info(
            f"Round {round_num} accuracy: {stats['correct']}/{stats['total']} = {stats['accuracy']:.2%}"
        )

        # --- Step 2: Reflect ---
        logger.info(f"Step 2: Running reflection...")
        n_exp = await run_reflection_round(
            round_num=round_num,
            results=results,
            experiment_dir=experiment_dir,
            experience_file=experience_file,
            model=args.reflection_model or args.model,
            dry_run=args.dry_run,
        )

        # --- Step 3: Evolve (aggregate strategies + generate patches) ---
        logger.info(f"Step 3: Running strategy evolution...")
        await run_evolution(
            round_num=round_num,
            experience_file=experience_file,
            preferences_file=preferences_file,
            overrides_file=overrides_file,
            model=args.model,
            dry_run=args.dry_run,
        )

        elapsed = time.time() - round_start
        logger.info(f"Round {round_num} completed in {elapsed:.0f}s")

        # Save intermediate report
        print_experiment_report(all_round_stats, experiment_dir)

    # Final report
    print("\n\n")
    print_experiment_report(all_round_stats, experiment_dir)


def main():
    parser = argparse.ArgumentParser(
        description="Self-Evolving Experiment: multi-round evaluation with reflection"
    )
    parser.add_argument(
        "--data_file",
        default="../../data/futurex/standardized_data_250924_250930.jsonl",
        help="Path to the full question JSONL file",
    )
    parser.add_argument("--model", default="gpt-5", help="Main LLM model for evaluation")
    parser.add_argument("--reflection_model", default="", help="Model for reflection (default: same as --model)")
    parser.add_argument("--rounds", type=int, default=5, help="Number of experiment rounds")
    parser.add_argument("--first_round_size", type=int, default=50, help="Questions in round 1")
    parser.add_argument("--later_round_size", type=int, default=30, help="Questions in rounds 2+")
    parser.add_argument("--max_concurrent", type=int, default=3, help="Max concurrent tasks")
    parser.add_argument("--seed", type=int, default=42, help="Random seed for sampling")
    parser.add_argument("--no_repeat", action="store_true", help="Avoid repeating questions across rounds")
    parser.add_argument("--dry_run", action="store_true", help="Simulate without LLM calls (for testing)")
    parser.add_argument(
        "--experiment_dir",
        default="../../logs/experiments",
        help="Base directory for experiment outputs",
    )
    parser.add_argument(
        "--extra_overrides",
        nargs="*",
        default=[],
        help="Additional Hydra config overrides (e.g. llm=gpt-5)",
    )

    args = parser.parse_args()
    asyncio.run(main_async(args))


if __name__ == "__main__":
    main()
