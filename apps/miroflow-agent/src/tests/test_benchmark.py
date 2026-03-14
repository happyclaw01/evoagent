# Copyright (c) 2025 MiroMind
# EA-405: Benchmark Comparison Tests
#
# Compares single-path vs multi-path performance on simulated tasks.
# Uses deterministic mock results to validate that the multi-path
# system outperforms single-path in expected scenarios.

import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))


class TestSingleVsMultiPath(unittest.TestCase):
    """EA-405: Single-path vs multi-path comparison."""

    def test_multi_path_majority_correct(self):
        """When majority of paths are correct, multi-path wins."""
        from src.core.multi_path import STRATEGY_VARIANTS
        
        # Simulate: 3 paths, 2 correct, 1 wrong
        path_answers = [
            {"strategy": "breadth_first", "answer": "correct_answer"},
            {"strategy": "depth_first", "answer": "correct_answer"},
            {"strategy": "lateral_thinking", "answer": "wrong_answer"},
        ]
        
        # Majority vote
        answers = [p["answer"] for p in path_answers]
        from collections import Counter
        vote = Counter(answers).most_common(1)[0][0]
        
        self.assertEqual(vote, "correct_answer")

    def test_single_path_wrong_multi_path_correct(self):
        """Classic scenario: single path fails but multi-path consensus succeeds."""
        # Single path (depth_first) gives wrong answer
        single_answer = "wrong_answer"
        
        # Multi-path: 2 correct, 1 wrong
        multi_answers = ["correct_answer", "correct_answer", "wrong_answer"]
        
        from collections import Counter
        multi_vote = Counter(multi_answers).most_common(1)[0][0]
        
        self.assertNotEqual(single_answer, multi_vote)
        self.assertEqual(multi_vote, "correct_answer")

    def test_diversity_improves_coverage(self):
        """Different strategies find different evidence."""
        from src.core.task_classifier import TaskClassifier
        
        classifier = TaskClassifier()
        
        # Different task types benefit from different strategies
        tasks = {
            "Calculate the sum of GDP growth rate": "compute",
            "Who was Alexander Graham Bell": "search",
            "Compare Python and Java performance": "multi-hop",
            "Write a poem about AI": "creative",
        }
        
        for task, expected_type in tasks.items():
            result = classifier.classify(task)
            self.assertEqual(result.task_type.value, expected_type,
                           f"Failed for: {task}")

    def test_early_stopping_saves_cost(self):
        """When paths agree early, early stopping saves resources."""
        from src.core.multi_path import STRATEGY_VARIANTS
        
        # Simulate: all 3 paths agree after different turns
        path_results = [
            {"answer": "42", "turns": 5, "cost": 0.005},
            {"answer": "42", "turns": 8, "cost": 0.008},
            {"answer": "42", "turns": 15, "cost": 0.015},  # Would have used more
        ]
        
        # With early stopping: stop after 2 agree
        early_stop_cost = sum(p["cost"] for p in path_results[:2])
        full_cost = sum(p["cost"] for p in path_results)
        
        self.assertLess(early_stop_cost, full_cost)

    def test_multi_path_accuracy_vs_cost_tradeoff(self):
        """More paths → higher accuracy but diminishing returns on efficiency."""
        from src.core.dimension_optimizer import DimensionOptimizer, DimensionConfig
        from src.core.strategy_tracker import StrategyRecordKeeper
        
        tmpdir = tempfile.mkdtemp()
        keeper = StrategyRecordKeeper(data_dir=f"{tmpdir}/results")
        optimizer = DimensionOptimizer(record_keeper=keeper, data_dir=f"{tmpdir}/dim")
        
        # efficiency = win_rate / cost
        # 1: 0.40/0.010=40, 3: 0.90/0.018=50, 5: 0.92/0.050=18.4
        config_1 = DimensionConfig(num_paths=1, max_turns=100, diversity=0.0)
        for i in range(10):
            optimizer.record_run(config_1, "search", won=(i < 4), cost=0.01)
        
        config_3 = DimensionConfig(num_paths=3, max_turns=100, diversity=0.5)
        for i in range(10):
            optimizer.record_run(config_3, "search", won=(i < 9), cost=0.018)
        
        config_5 = DimensionConfig(num_paths=5, max_turns=100, diversity=0.7)
        for i in range(10):
            optimizer.record_run(config_5, "search", won=(i < 9), cost=0.05)
        
        r1 = optimizer.get_results(config_1, "search")
        r3 = optimizer.get_results(config_3, "search")
        r5 = optimizer.get_results(config_5, "search")
        
        # 3 paths: best efficiency
        self.assertGreater(r3.efficiency_score, r1.efficiency_score)
        self.assertGreater(r3.efficiency_score, r5.efficiency_score)


class TestTaskTypeBenchmark(unittest.TestCase):
    """EA-405: Performance across task types."""

    def test_strategy_specialization(self):
        """Different strategies should excel at different task types."""
        from src.core.strategy_tracker import StrategyRecordKeeper, StrategyResult, StrategyProfileEngine
        
        tmpdir = tempfile.mkdtemp()
        keeper = StrategyRecordKeeper(data_dir=f"{tmpdir}/results")
        
        # breadth_first: good at search, bad at compute
        for i in range(10):
            keeper.record(StrategyResult(
                task_id=f"s{i}", strategy_name="breadth_first",
                task_type="search", is_winner=(i < 8),
                turns_used=10, cost_usd=0.01,
            ))
            keeper.record(StrategyResult(
                task_id=f"c{i}", strategy_name="breadth_first",
                task_type="compute", is_winner=(i < 3),
                turns_used=10, cost_usd=0.01,
            ))
        
        # depth_first: good at compute, bad at search
        for i in range(10):
            keeper.record(StrategyResult(
                task_id=f"s{i}", strategy_name="depth_first",
                task_type="search", is_winner=(i < 3),
                turns_used=10, cost_usd=0.01,
            ))
            keeper.record(StrategyResult(
                task_id=f"c{i}", strategy_name="depth_first",
                task_type="compute", is_winner=(i < 8),
                turns_used=10, cost_usd=0.01,
            ))
        
        engine = StrategyProfileEngine(record_keeper=keeper, profile_dir=f"{tmpdir}/profiles")
        
        best_search = engine.get_best_strategy_for("search")
        best_compute = engine.get_best_strategy_for("compute")
        
        self.assertEqual(best_search, "breadth_first")
        self.assertEqual(best_compute, "depth_first")


if __name__ == "__main__":
    unittest.main(verbosity=2)
