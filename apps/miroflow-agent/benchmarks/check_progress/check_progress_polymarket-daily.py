# Copyright (c) 2025 MiroMind
# This source code is licensed under the MIT License.

import argparse
import os

from common import GenericProgressChecker as ProgressChecker

# Benchmark configuration
FILENAME = os.path.basename(__file__)
BENCHMARK_NAME = "polymarket-daily"
BENCHMARK_NAME_STD = "Polymarket-Daily"
TASKS_PER_RUN = None  # Will be determined from data file
DATA_PATH = f"../../data/{BENCHMARK_NAME}/metadata.jsonl"
TASK_ID_PATTERN = r"polymarket_([^_]+(?:-[^_]+)*)"


def parse_args():
    parser = argparse.ArgumentParser(
        description=f"Check progress of {BENCHMARK_NAME_STD} benchmark runs."
    )
    parser.add_argument(
        "path", help=f"Path to {BENCHMARK_NAME_STD} benchmark directory"
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()

    try:
        # Determine tasks per run from data file if available
        tasks_per_run = TASKS_PER_RUN
        if tasks_per_run is None and os.path.exists(DATA_PATH):
            with open(DATA_PATH, "r", encoding="utf-8") as f:
                tasks_per_run = sum(1 for line in f if line.strip())
            print(f"Detected {tasks_per_run} tasks in data file")

        # Create progress checker and run analysis
        checker = ProgressChecker(
            args.path, task_per_run=tasks_per_run, data_path=DATA_PATH
        )
        summary = checker.run_analysis(
            benchmark_name_std=BENCHMARK_NAME_STD, task_id_pattern=TASK_ID_PATTERN
        )
        # Exit with appropriate code
        if summary.total_tasks == 0:
            print("No task files found in any run directories")
        elif summary.total_completed == 0:
            print("No tasks completed yet")

    except FileNotFoundError as e:
        print(f"Error: {e}")
    except PermissionError as e:
        print(f"Error: {e}")
    except ValueError as e:
        print(f"Error: {e}")
    except Exception as e:
        print(f"Unexpected error: {e}")
