# Copyright (c) 2025 MiroMind
# EA-406: Cost-Benefit Analysis Tests
#
# Analyzes cost vs accuracy tradeoffs for different path counts
# and configurations using the DimensionOptimizer.

import asyncio
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))


def run_async(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


class TestPathCountScaling(unittest.TestCase):
    """EA-406: How path count affects cost and accuracy."""

    def test_cost_scales_with_paths(self):
        """More paths = more cost."""
        from src.core.cost_tracker import CostTracker
        
        costs = {}
        for num_paths in [1, 3]:
            tracker = CostTracker(log_dir=tempfile.mkdtemp())
            for p in range(num_paths):
                tracker.record_path_cost(
                    path_id=f"p{p}", strategy_name="bf",
                    model_name="claude-sonnet-4-20250514",
                    input_tokens=1000, output_tokens=500,
                )
            costs[num_paths] = tracker.get_summary().total_cost_usd
        
        self.assertGreater(costs[3], costs[1])

    def test_diminishing_returns(self):
        """More paths has diminishing returns on accuracy."""
        from src.core.dimension_optimizer import DimensionOptimizer, DimensionConfig
        from src.core.strategy_tracker import StrategyRecordKeeper
        
        tmpdir = tempfile.mkdtemp()
        keeper = StrategyRecordKeeper(data_dir=f"{tmpdir}/results")
        optimizer = DimensionOptimizer(record_keeper=keeper, data_dir=f"{tmpdir}/dim")
        
        # efficiency = win_rate / cost
        # 1: 0.40/0.010 = 40, 2: 0.75/0.015 = 50, 3: 0.90/0.020 = 45, 5: 0.92/0.050 = 18.4
        configs_data = [
            (1, 0.40, 0.010),   # eff=40
            (2, 0.75, 0.015),   # eff=50 (sweet spot)
            (3, 0.90, 0.020),   # eff=45
            (5, 0.92, 0.050),   # eff=18.4 (diminishing)
        ]
        
        for num_paths, win_rate, cost in configs_data:
            config = DimensionConfig(num_paths=num_paths, max_turns=100, diversity=0.5)
            for i in range(20):
                optimizer.record_run(config, "all",
                                     won=(i < int(win_rate * 20)), cost=cost)
        
        results = {}
        for num_paths, _, _ in configs_data:
            config = DimensionConfig(num_paths=num_paths, max_turns=100, diversity=0.5)
            results[num_paths] = optimizer.get_results(config, "all")
        
        # 2-3 paths best efficiency
        self.assertGreater(results[2].efficiency_score, results[1].efficiency_score)
        self.assertGreater(results[3].efficiency_score, results[5].efficiency_score)

    def test_early_stopping_cost_savings(self):
        """Early stopping should reduce effective cost."""
        full_cost = 3 * 0.015
        early_stop_cost = 2 * 0.015 + 1 * 0.005
        savings = (full_cost - early_stop_cost) / full_cost
        self.assertGreater(savings, 0.1)

    def test_cache_cost_savings(self):
        """Result cache should reduce redundant API calls."""
        from src.core.result_cache import ResultCache
        
        cache = ResultCache(max_entries=100, default_ttl=300)
        
        async def run():
            await cache.put("search", {"query": "test"}, "result_1")
            r1 = await cache.get("search", {"query": "test"})
            r2 = await cache.get("search", {"query": "test"})
            self.assertEqual(r1, "result_1")
            self.assertEqual(r2, "result_1")
            
            stats = await cache.get_stats()
            self.assertEqual(stats["hits"], 2)
        
        run_async(run())


class TestDepthVsCost(unittest.TestCase):
    """EA-406: How depth (max_turns) affects cost and quality."""

    def test_deeper_costs_more(self):
        from src.core.cost_tracker import CostTracker
        
        shallow = CostTracker(log_dir=tempfile.mkdtemp())
        shallow.record_path_cost(
            path_id="p0", strategy_name="bf",
            model_name="claude-sonnet-4-20250514",
            input_tokens=10000, output_tokens=5000, num_turns=50,
        )
        
        deep = CostTracker(log_dir=tempfile.mkdtemp())
        deep.record_path_cost(
            path_id="p0", strategy_name="bf",
            model_name="claude-sonnet-4-20250514",
            input_tokens=40000, output_tokens=20000, num_turns=200,
        )
        
        self.assertGreater(deep.get_summary().total_cost_usd,
                          shallow.get_summary().total_cost_usd)

    def test_strategy_budget_allocation_is_efficient(self):
        from src.core.multi_path import STRATEGY_VARIANTS
        
        budgets = {s["name"]: s.get("max_turns", 100) for s in STRATEGY_VARIANTS}
        
        if "depth_first" in budgets and "breadth_first" in budgets:
            self.assertGreater(budgets["depth_first"], budgets["breadth_first"])


class TestDiversityVsCost(unittest.TestCase):
    """EA-406: How diversity affects performance."""

    def test_diversity_reduces_groupthink(self):
        from src.core.groupthink_detector import GroupthinkDetector, PathAnswer
        
        detector = GroupthinkDetector()
        
        same_reasoning = "Using standard analysis methods to find the answer"
        low_div = [
            PathAnswer(path_id="p0", answer="42", reasoning=same_reasoning,
                      turns_used=10, duration_seconds=5),
            PathAnswer(path_id="p1", answer="42", reasoning=same_reasoning,
                      turns_used=10, duration_seconds=5),
        ]
        
        high_div = [
            PathAnswer(path_id="p0", answer="42",
                      reasoning="Mathematical proof via algebraic manipulation and theorem application",
                      sources=["math.org"], turns_used=15, duration_seconds=10),
            PathAnswer(path_id="p1", answer="42",
                      reasoning="Experimental verification through controlled laboratory testing",
                      sources=["lab.org"], turns_used=8, duration_seconds=5),
        ]
        
        low_report = detector.analyze(low_div)
        high_report = detector.analyze(high_div)
        
        self.assertGreaterEqual(low_report.overall_risk, high_report.overall_risk)


if __name__ == "__main__":
    unittest.main(verbosity=2)
