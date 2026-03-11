#!/usr/bin/env python
# Copyright (c) 2025 MiroMind
# This source code is licensed under the MIT License.

"""
Polymarket Daily evaluation runner.

This script is designed to be called by:
  scripts/run_evaluate_multiple_runs_polymarket-daily-pipeline.sh

Key behavior (when MIROFLOW_DECISION_MODE=polymarket_local):
- Ensures the main agent is guided by the local-only "decision predictor" prompts
  (implemented in src/utils/prompt_utils.py).
- Builds a structured JSON block per task containing `market_features` so the agent
  can make a decision without web access.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import hydra
from hydra import compose, initialize_config_dir
from omegaconf import OmegaConf

# Ensure project root is importable even if cwd differs
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from benchmarks.common_benchmark import BenchmarkTask, GenericEvaluator  # noqa: E402


def _is_decision_mode() -> bool:
    return os.getenv("MIROFLOW_DECISION_MODE", "").strip().lower() == "polymarket_local"


def _safe_float(x: Any) -> Optional[float]:
    try:
        if x is None:
            return None
        if isinstance(x, (int, float)):
            return float(x)
        s = str(x).strip()
        if s == "":
            return None
        return float(s)
    except Exception:
        return None


def _resolve_path(base: Path, maybe_rel: str) -> str:
    p = Path(maybe_rel)
    if p.is_absolute():
        return str(p)
    return str((base / p).resolve())


def _pick_yes_index(options: Any) -> int:
    if not isinstance(options, list) or not options:
        return 0
    for i, opt in enumerate(options):
        if str(opt).strip().lower() == "yes":
            return i
    return 0


def _extract_best_prices(orderbook: Dict[str, Any]) -> Tuple[Optional[float], Optional[float]]:
    bids = orderbook.get("bids") or []
    asks = orderbook.get("asks") or []
    best_bid = None
    best_ask = None
    for b in bids:
        bp = _safe_float(b.get("price"))
        if bp is None:
            continue
        best_bid = bp if best_bid is None else max(best_bid, bp)
    for a in asks:
        ap = _safe_float(a.get("price"))
        if ap is None:
            continue
        best_ask = ap if best_ask is None else min(best_ask, ap)
    return best_bid, best_ask


def _depth_top_k(orderbook: Dict[str, Any], k: int = 5) -> Optional[float]:
    bids = orderbook.get("bids") or []
    asks = orderbook.get("asks") or []

    bid_lvls: List[Tuple[float, float]] = []
    for b in bids:
        p = _safe_float(b.get("price"))
        s = _safe_float(b.get("size"))
        if p is None or s is None:
            continue
        bid_lvls.append((p, s))
    bid_lvls.sort(key=lambda x: x[0], reverse=True)

    ask_lvls: List[Tuple[float, float]] = []
    for a in asks:
        p = _safe_float(a.get("price"))
        s = _safe_float(a.get("size"))
        if p is None or s is None:
            continue
        ask_lvls.append((p, s))
    ask_lvls.sort(key=lambda x: x[0])

    if not bid_lvls and not ask_lvls:
        return None
    return float(sum(s for _, s in bid_lvls[:k]) + sum(s for _, s in ask_lvls[:k]))


def _twap_from_price_history(price_history: Dict[str, Any], n: int = 24) -> Optional[float]:
    # Expected shape: {"history": {"history": [{"t":..., "p":...}, ...]}}
    hist = (price_history.get("history") or {}).get("history") if isinstance(price_history, dict) else None
    if not isinstance(hist, list) or not hist:
        return None
    ps: List[float] = []
    for item in hist[-n:]:
        p = _safe_float(item.get("p")) if isinstance(item, dict) else None
        if p is not None:
            ps.append(p)
    if not ps:
        return None
    return float(sum(ps) / len(ps))


class PolymarketDailyEvaluator(GenericEvaluator):
    """
    Custom evaluator that injects a structured JSON block into task_description.

    NOTE: We run sequentially in-process to ensure this custom prepare_task_description
    is used (the generic multiprocessing worker currently reconstructs GenericEvaluator).
    """

    def __init__(
        self,
        *args,
        orderbook_top_n: int = 20,
        price_history_tail_n: int = 120,
        max_extra_chars: int = 6000,
        **kwargs,
    ):
        super().__init__(*args, **kwargs)
        self.orderbook_top_n = int(orderbook_top_n)
        self.price_history_tail_n = int(price_history_tail_n)
        self.max_extra_chars = int(max_extra_chars)

        self._orderbook_by_market_token: Dict[str, Dict[str, Dict[str, Any]]] = {}
        self._price_history_by_market_token: Dict[str, Dict[str, Dict[str, Any]]] = {}

        # Preload additional data (orderbook, price_history) if configured
        self._load_polymarket_additional_data()

    def _load_polymarket_additional_data(self) -> None:
        data_dir = Path(self.data_dir)
        orderbook_file = self.additional_data_files.get("orderbook")
        price_history_file = self.additional_data_files.get("price_history")

        if orderbook_file:
            p = data_dir / orderbook_file
            if p.exists():
                by_market: Dict[str, Dict[str, Dict[str, Any]]] = {}
                with open(p, "r", encoding="utf-8") as f:
                    for line in f:
                        if not line.strip():
                            continue
                        try:
                            rec = json.loads(line)
                        except Exception:
                            continue
                        market_id = str(rec.get("market_id") or "").strip()
                        token_id = str(rec.get("token_id") or "").strip()
                        if not market_id or not token_id:
                            continue
                        by_market.setdefault(market_id, {})[token_id] = rec
                self._orderbook_by_market_token = by_market

        if price_history_file:
            p = data_dir / price_history_file
            if p.exists():
                by_market = {}
                with open(p, "r", encoding="utf-8") as f:
                    for line in f:
                        if not line.strip():
                            continue
                        try:
                            rec = json.loads(line)
                        except Exception:
                            continue
                        market_id = str(rec.get("market_id") or "").strip()
                        token_id = str(rec.get("token_id") or "").strip()
                        if not market_id or not token_id:
                            continue
                        by_market.setdefault(market_id, {})[token_id] = rec
                self._price_history_by_market_token = by_market

    def load_tasks(self, limit: Optional[int] = None) -> List[BenchmarkTask]:
        # Override to treat empty ground_truth as None and to store market metadata cleanly.
        if not self.metadata_file.exists():
            raise FileNotFoundError(f"Metadata file not found: {self.metadata_file}")

        tasks: List[BenchmarkTask] = []
        with open(self.metadata_file, "r", encoding="utf-8") as f:
            for i, line in enumerate(f):
                if limit and i >= limit:
                    break
                if not line.strip():
                    continue
                try:
                    data = json.loads(line)
                except Exception:
                    continue

                task_id = str(data.get(self.task_id_field, "")).strip()
                task_question = str(data.get(self.question_field, "")).strip()
                gt = data.get(self.ground_truth_field, None)
                ground_truth = gt if (gt is not None and str(gt).strip() != "") else None

                market_meta = data.get("metadata") or {}
                market_id = str(market_meta.get("market_id") or "").strip()
                metadata: Dict[str, Any] = {
                    "market_id": market_id,
                    "market": market_meta,
                }

                tasks.append(
                    BenchmarkTask(
                        task_id=task_id,
                        task_question=task_question,
                        ground_truth=ground_truth,
                        file_path=None,
                        metadata=metadata,
                    )
                )

        self.tasks = tasks
        return tasks

    def prepare_task_description(self, task: BenchmarkTask) -> Tuple[str, Optional[str]]:
        market_meta = (task.metadata or {}).get("market") or {}
        market_id = str((task.metadata or {}).get("market_id") or "").strip()

        options = market_meta.get("options")
        probs = market_meta.get("probabilities")
        yes_idx = _pick_yes_index(options)

        p_final = None
        if isinstance(probs, list) and len(probs) > yes_idx:
            p_final = _safe_float(probs[yes_idx])

        clob_token_ids = market_meta.get("clobTokenIds") or []
        yes_token_id = None
        if isinstance(clob_token_ids, list) and len(clob_token_ids) > yes_idx:
            yes_token_id = str(clob_token_ids[yes_idx])

        orderbook_rec = None
        price_hist_rec = None
        if market_id:
            if yes_token_id:
                orderbook_rec = self._orderbook_by_market_token.get(market_id, {}).get(yes_token_id)
                price_hist_rec = self._price_history_by_market_token.get(market_id, {}).get(yes_token_id)
            # fallback: pick any token record
            if orderbook_rec is None:
                m = self._orderbook_by_market_token.get(market_id, {})
                orderbook_rec = next(iter(m.values()), None) if isinstance(m, dict) else None
            if price_hist_rec is None:
                m = self._price_history_by_market_token.get(market_id, {})
                price_hist_rec = next(iter(m.values()), None) if isinstance(m, dict) else None

        best_bid = best_ask = None
        p_mid = None
        spread = None
        depth_5 = None
        bid1_size = None
        ask1_size = None
        if isinstance(orderbook_rec, dict):
            best_bid, best_ask = _extract_best_prices(orderbook_rec)
            if best_bid is not None and best_ask is not None:
                p_mid = (best_bid + best_ask) / 2.0
                spread = best_ask - best_bid
            depth_5 = _depth_top_k(orderbook_rec, k=5)

            # "level-1" sizes for evidence (best price level)
            bids = orderbook_rec.get("bids") or []
            asks = orderbook_rec.get("asks") or []
            if isinstance(bids, list) and bids:
                # max-price bid
                bb = max(
                    (b for b in bids if _safe_float(b.get("price")) is not None),
                    key=lambda b: _safe_float(b.get("price")),
                    default=None,
                )
                bid1_size = _safe_float(bb.get("size")) if isinstance(bb, dict) else None
            if isinstance(asks, list) and asks:
                # min-price ask
                ba = min(
                    (a for a in asks if _safe_float(a.get("price")) is not None),
                    key=lambda a: _safe_float(a.get("price")),
                    default=None,
                )
                ask1_size = _safe_float(ba.get("size")) if isinstance(ba, dict) else None

        twap_24h = _twap_from_price_history(price_hist_rec or {}, n=24) if isinstance(price_hist_rec, dict) else None

        vol_total = _safe_float(market_meta.get("volume"))
        vol_24h = _safe_float(market_meta.get("vol_24h"))  # may not exist; keep None

        market_features: Dict[str, Any] = {
            "p_final": p_final,
            "p_mid": p_mid,
            "twap_24h": twap_24h,
            "spread": spread,
            "depth_5": depth_5,
            "vol_24h": vol_24h,
            "vol_total": vol_total,
            "best_bid": best_bid,
            "best_ask": best_ask,
            "bid1_size": bid1_size,
            "ask1_size": ask1_size,
        }

        payload: Dict[str, Any] = {
            "question": task.task_question,
            "market_id": market_id or None,
            "slug": market_meta.get("slug"),
            "created_at": market_meta.get("created_at"),
            "resolved_at": market_meta.get("resolved_at"),
            "snapshot_time": market_meta.get("snapshot_time"),
            "options": options,
            "probabilities": probs,
            "market_features": market_features,
        }

        # Optional: include trimmed raw data if it fits the configured budget
        if isinstance(orderbook_rec, dict):
            bids = orderbook_rec.get("bids") or []
            asks = orderbook_rec.get("asks") or []
            payload["orderbook_top"] = {
                "token_id": orderbook_rec.get("token_id"),
                "bids": bids[: self.orderbook_top_n] if isinstance(bids, list) else [],
                "asks": asks[: self.orderbook_top_n] if isinstance(asks, list) else [],
            }
        if isinstance(price_hist_rec, dict):
            hist = ((price_hist_rec.get("history") or {}).get("history") or [])
            payload["price_history_tail"] = {
                "token_id": price_hist_rec.get("token_id"),
                "interval": price_hist_rec.get("interval"),
                "history": hist[-self.price_history_tail_n :] if isinstance(hist, list) else [],
            }

        json_block = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        if self.max_extra_chars and len(json_block) > self.max_extra_chars:
            payload.pop("orderbook_top", None)
            payload.pop("price_history_tail", None)
            json_block = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))

        task_description = (
            f"{task.task_question}\n\n"
            "下面提供的是本地结构化数据 JSON（只允许使用这些信息做 Yes/No 决策；禁止上网/禁止外部事实）。\n"
            "```json\n"
            f"{json_block}\n"
            "```\n"
        )

        return task_description, None


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Evaluate Polymarket Daily benchmark (local JSON features).")
    p.add_argument("--benchmark", default="polymarket-daily")
    p.add_argument("--agent", default="single_agent_keep5")
    p.add_argument("--llm-provider", default="openai", choices=["openai", "anthropic", "qwen"])
    p.add_argument("--model-name", default=None)
    p.add_argument("--base-url", default=None)
    p.add_argument("--temperature", type=float, default=None)
    p.add_argument("--max-context-length", type=int, default=None)
    p.add_argument("--max-tasks", type=int, default=None)
    p.add_argument("--orderbook-top-n", type=int, default=20)
    p.add_argument("--price-history-tail-n", type=int, default=120)
    p.add_argument("--max-extra-chars", type=int, default=6000)
    p.add_argument("--out-dir", required=True)
    p.add_argument("--dry-run", action="store_true", help="Print 1 task_description and exit (no LLM calls).")
    return p


def _pick_llm_group(llm_provider: str) -> str:
    # Map provider to an available Hydra config group name.
    if llm_provider == "openai":
        return "openai"
    if llm_provider == "qwen":
        return "qwen-3"
    # anthropic
    return "default"


def main() -> int:
    args = build_arg_parser().parse_args()

    out_dir = Path(args.out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    conf_dir = (PROJECT_ROOT / "conf").resolve()
    llm_group = _pick_llm_group(args.llm_provider)

    overrides: List[str] = [
        f"benchmark={args.benchmark}",
        f"agent={args.agent}",
        f"llm={llm_group}",
        f"hydra.run.dir={str(out_dir)}",
        "benchmark.execution.max_concurrent=1",  # run in-process to preserve custom task_description
    ]

    if args.max_tasks is not None:
        overrides.append(f"benchmark.execution.max_tasks={args.max_tasks}")

    if args.model_name:
        overrides.append(f"llm.model_name={args.model_name}")
    if args.base_url:
        overrides.append(f"llm.base_url={args.base_url}")
    if args.temperature is not None:
        overrides.append(f"llm.temperature={args.temperature}")
    if args.max_context_length is not None:
        overrides.append(f"llm.max_context_length={args.max_context_length}")

    with initialize_config_dir(config_dir=str(conf_dir), version_base=None):
        cfg = compose(config_name="config", overrides=overrides)

    # Resolve benchmark data_dir to an absolute path (robust to cwd).
    OmegaConf.set_struct(cfg, False)
    cfg.benchmark.data.data_dir = _resolve_path(PROJECT_ROOT, cfg.benchmark.data.data_dir)
    cfg.debug_dir = str(out_dir)

    # In decision mode, proactively remove network tools from the main agent tool list.
    if _is_decision_mode():
        allowed = {"tool-python", "tool-reader", "tool-reading"}
        if getattr(cfg.agent, "main_agent", None) and getattr(cfg.agent.main_agent, "tools", None):
            cfg.agent.main_agent.tools = [t for t in list(cfg.agent.main_agent.tools) if t in allowed]

    evaluator = PolymarketDailyEvaluator(
        data_dir=cfg.benchmark.data.data_dir,
        benchmark_name=cfg.benchmark.name,
        cfg=cfg,
        metadata_file=cfg.benchmark.data.metadata_file,
        task_id_field=cfg.benchmark.data.field_mapping.task_id_field,
        question_field=cfg.benchmark.data.field_mapping.task_question_field,
        ground_truth_field=cfg.benchmark.data.field_mapping.ground_truth_field,
        file_name_field=None,
        additional_data_files=dict(cfg.benchmark.data.additional_data_files),
        orderbook_top_n=args.orderbook_top_n,
        price_history_tail_n=args.price_history_tail_n,
        max_extra_chars=args.max_extra_chars,
    )
    evaluator._log_dir = str(out_dir)  # Ensure log dir works without HydraConfig

    tasks = evaluator.load_tasks(limit=cfg.benchmark.execution.max_tasks)
    if not tasks:
        print("No tasks loaded.")
        return 0

    if args.dry_run:
        td, _ = evaluator.prepare_task_description(tasks[0])
        print(td)
        return 0

    # IMPORTANT: run sequentially to avoid multiprocessing re-constructing GenericEvaluator.
    evaluator.run_sequential_inference(tasks)

    # Save benchmark results JSONL
    results_path = out_dir / "benchmark_results.jsonl"
    with open(results_path, "w", encoding="utf-8") as f:
        for r in evaluator.results:
            f.write(json.dumps(asdict(r), ensure_ascii=False) + "\n")

    print(f"Saved results to {results_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

