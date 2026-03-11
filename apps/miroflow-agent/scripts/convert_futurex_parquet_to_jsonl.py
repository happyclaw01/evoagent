#!/usr/bin/env python
# Copyright (c) 2025 MiroMind
# This source code is licensed under the MIT License.

"""
Convert FutureX parquet (FutureX-Past / FutureX-Online) into miroflow-agent JSONL format.

Input parquet schema typically includes:
  - id (string)
  - prompt (string)
  - ground_truth (string)  # Past only; Online may not have
  - end_time, level, title, en_title, slug, ...

Output JSONL schema for common_benchmark.py (default field mapping):
  - task_id
  - task_question
  - ground_truth
  - ... (extra fields preserved as metadata)
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, Iterable, Optional


def _safe_str(x: Any) -> Optional[str]:
    if x is None:
        return None
    s = str(x)
    return s if s.strip() != "" else None


def _iter_records_from_parquet(parquet_path: Path) -> Iterable[Dict[str, Any]]:
    # Prefer pyarrow directly (datasets depends on it; avoids adding pandas).
    try:
        import pyarrow.parquet as pq  # type: ignore
    except Exception as e:  # pragma: no cover
        raise RuntimeError(
            "Missing dependency 'pyarrow'. Install it (or install 'datasets') and retry."
        ) from e

    table = pq.read_table(parquet_path)
    cols = set(table.column_names)

    # Convert to Python records. This is fine for <1k rows.
    as_dict = table.to_pydict()
    n = len(next(iter(as_dict.values()))) if as_dict else 0
    for i in range(n):
        yield {k: as_dict[k][i] for k in as_dict.keys()}


def convert(
    *,
    input_parquet: Path,
    output_jsonl: Path,
    limit: Optional[int] = None,
) -> int:
    input_parquet = input_parquet.resolve()
    output_jsonl.parent.mkdir(parents=True, exist_ok=True)

    written = 0
    with output_jsonl.open("w", encoding="utf-8") as f:
        for rec in _iter_records_from_parquet(input_parquet):
            if limit is not None and written >= limit:
                break

            out: Dict[str, Any] = {}
            # Required fields for default field mapping
            out["task_id"] = _safe_str(rec.get("id")) or _safe_str(rec.get("task_id"))
            out["task_question"] = _safe_str(rec.get("prompt")) or _safe_str(
                rec.get("task_question")
            )
            # Past has ground_truth; Online often doesn't.
            out["ground_truth"] = rec.get("ground_truth", rec.get("ground truth"))

            # Preserve other metadata (non-null) for debugging / analysis.
            for k, v in rec.items():
                if k in {"id", "task_id", "prompt", "task_question", "ground_truth", "ground truth"}:
                    continue
                if v is None:
                    continue
                out[k] = v

            if not out.get("task_id") or not out.get("task_question"):
                # Skip malformed rows
                continue

            f.write(json.dumps(out, ensure_ascii=False) + "\n")
            written += 1

    return written


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Convert FutureX parquet to JSONL for miroflow-agent benchmarks.")
    p.add_argument(
        "--input",
        required=True,
        help="Path to input parquet file (e.g. data/futurex/data/train-00000-of-00001.parquet).",
    )
    p.add_argument(
        "--output",
        required=True,
        help="Path to output JSONL file (e.g. data/futurex/standardized_data.jsonl).",
    )
    p.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Optional: only convert first N rows.",
    )
    return p


def main() -> int:
    args = build_arg_parser().parse_args()
    n = convert(
        input_parquet=Path(args.input),
        output_jsonl=Path(args.output),
        limit=args.limit,
    )
    print(f"Converted {n} row(s) -> {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

