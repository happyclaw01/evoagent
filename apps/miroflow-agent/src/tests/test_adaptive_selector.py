# Copyright (c) 2025 MiroMind
# Unit Tests for EA-104: Adaptive Strategy Selection

import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))


def _make_result(strategy="breadth_first", task_id="t1", is_winner=True,
                 task_type="search", cost=0.01, turns=10, timestamp=None):
    from src.core.strategy_tracker import StrategyResult
    return StrategyResult(
        task_id=task_id, strategy_name=strategy, task_type=task_type,
        is_winner=is_winner, cost_usd=cost, turns_used=turns,
        timestamp=timestamp or time.time(),
    )


def _build_env(records):
    from src.core.strategy_tracker import StrategyRecordKeeper, StrategyProfileEngine
    from src.core.task_classifier import TaskClassifier
    from src.core.adaptive_selector import AdaptiveSelector
    tmpdir = tempfile.mkdtemp()
    keeper = StrategyRecordKeeper(data_dir=f"{tmpdir}/results")
    for r in records:
        keeper.record(r)
    engine = StrategyProfileEngine(record_keeper=keeper, profile_dir=f"{tmpdir}/profiles")
    engine.build_profiles()
    classifier = TaskClassifier()
    selector = AdaptiveSelector(profile_engine=engine, classifier=classifier)
    return selector


class TestSlotCounts(unittest.TestCase):
    """Test exploit/explore slot allocation."""

    def test_1_path(self):
        from src.core.adaptive_selector import AdaptiveSelector
        self.assertEqual(AdaptiveSelector._get_slot_counts(1), (1, 0))

    def test_2_paths(self):
        from src.core.adaptive_selector import AdaptiveSelector
        self.assertEqual(AdaptiveSelector._get_slot_counts(2), (1, 1))

    def test_3_paths(self):
        from src.core.adaptive_selector import AdaptiveSelector
        self.assertEqual(AdaptiveSelector._get_slot_counts(3), (2, 1))

    def test_4_paths(self):
        from src.core.adaptive_selector import AdaptiveSelector
        self.assertEqual(AdaptiveSelector._get_slot_counts(4), (2, 2))

    def test_5_paths(self):
        from src.core.adaptive_selector import AdaptiveSelector
        self.assertEqual(AdaptiveSelector._get_slot_counts(5), (3, 2))


class TestColdStart(unittest.TestCase):
    """Test cold start (no historical data)."""

    def test_cold_start_returns_defaults(self):
        selector = _build_env([])
        result = selector.select("Who is the CEO?", num_paths=3)
        self.assertEqual(result.method, "cold_start")
        self.assertEqual(len(result.strategies), 3)
        self.assertTrue(all(r == "explore" for r in result.roles))

    def test_cold_start_respects_num_paths(self):
        selector = _build_env([])
        result = selector.select("Calculate X", num_paths=2)
        self.assertEqual(len(result.strategies), 2)


class TestAdaptiveSelection(unittest.TestCase):
    """Test adaptive selection with historical data."""

    def test_best_strategy_gets_exploit(self):
        records = []
        # All 4 strategies have data, breadth_first wins most
        for i in range(15):
            records.append(_make_result(strategy="breadth_first", task_id=f"t{i}a", is_winner=True))
            records.append(_make_result(strategy="depth_first", task_id=f"t{i}b", is_winner=False))
            records.append(_make_result(strategy="lateral_thinking", task_id=f"t{i}c", is_winner=False))
            records.append(_make_result(strategy="verification_heavy", task_id=f"t{i}d", is_winner=False))
        selector = _build_env(records)
        result = selector.select("Find information about X", num_paths=2)
        # breadth_first should be exploit (highest win rate, enough samples)
        self.assertIn("breadth_first", result.strategies)
        idx = result.strategies.index("breadth_first")
        self.assertEqual(result.roles[idx], "exploit")

    def test_selection_has_both_roles(self):
        records = []
        for i in range(10):
            records.append(_make_result(strategy="breadth_first", task_id=f"t{i}a", is_winner=(i < 8)))
            records.append(_make_result(strategy="depth_first", task_id=f"t{i}b", is_winner=(i < 3)))
            records.append(_make_result(strategy="lateral_thinking", task_id=f"t{i}c", is_winner=(i < 5)))
        selector = _build_env(records)
        result = selector.select("Search for Y", num_paths=3)
        self.assertIn("exploit", result.roles)
        self.assertIn("explore", result.roles)

    def test_exclude_strategy(self):
        records = [_make_result(strategy="breadth_first", task_id=f"t{i}", is_winner=True) for i in range(5)]
        selector = _build_env(records)
        result = selector.select("Find X", num_paths=2, exclude=["breadth_first"])
        self.assertNotIn("breadth_first", result.strategies)

    def test_force_explore(self):
        records = [_make_result(strategy="breadth_first", task_id=f"t{i}", is_winner=True) for i in range(5)]
        selector = _build_env(records)
        result = selector.select("Find X", num_paths=2, force_explore=["lateral_thinking"])
        self.assertIn("lateral_thinking", result.strategies)
        idx = result.strategies.index("lateral_thinking")
        self.assertEqual(result.roles[idx], "explore")

    def test_no_duplicate_strategies(self):
        records = []
        for i in range(10):
            for s in ["breadth_first", "depth_first", "lateral_thinking", "verification_heavy"]:
                records.append(_make_result(strategy=s, task_id=f"t{i}", is_winner=(s == "breadth_first")))
        selector = _build_env(records)
        result = selector.select("Test", num_paths=4)
        self.assertEqual(len(result.strategies), len(set(result.strategies)))


class TestUCBScores(unittest.TestCase):
    """Test UCB score computation."""

    def test_unseen_strategy_gets_bonus(self):
        # Only breadth_first has records
        records = [_make_result(strategy="breadth_first", task_id=f"t{i}") for i in range(5)]
        selector = _build_env(records)
        result = selector.select("Test", num_paths=4)
        # Unseen strategies should have high scores (exploration bonus)
        for s in ["depth_first", "lateral_thinking", "verification_heavy"]:
            self.assertGreater(result.scores.get(s, 0), 0)

    def test_scores_populated(self):
        records = [_make_result(strategy="breadth_first", task_id=f"t{i}") for i in range(5)]
        selector = _build_env(records)
        result = selector.select("Test", num_paths=2)
        self.assertTrue(len(result.scores) > 0)


class TestSelectionResult(unittest.TestCase):
    """Test StrategySelection."""

    def test_to_dict(self):
        selector = _build_env([])
        result = selector.select("Test", num_paths=2)
        d = result.to_dict()
        self.assertIn("strategies", d)
        self.assertIn("roles", d)
        self.assertIn("task_type", d)
        self.assertIn("method", d)

    def test_task_type_set(self):
        selector = _build_env([])
        result = selector.select("Calculate the sum of 1+2", num_paths=2)
        self.assertEqual(result.task_type, "compute")

    def test_num_paths_capped(self):
        selector = _build_env([])
        result = selector.select("Test", num_paths=10)
        self.assertLessEqual(len(result.strategies), 4)  # Only 4 defaults


class TestExplorationRate(unittest.TestCase):
    """Test exploration rate monitoring."""

    def test_full_exploration_cold_start(self):
        selector = _build_env([])
        self.assertEqual(selector.get_exploration_rate(), 1.0)

    def test_exploration_decreases_with_data(self):
        records = []
        for i in range(30):
            for s in ["breadth_first", "depth_first", "lateral_thinking", "verification_heavy"]:
                records.append(_make_result(strategy=s, task_id=f"t{i}{s}", is_winner=(s == "breadth_first")))
        selector = _build_env(records)
        rate = selector.get_exploration_rate()
        self.assertLess(rate, 1.0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
