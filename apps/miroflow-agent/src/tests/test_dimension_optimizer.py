# Copyright (c) 2025 MiroMind
# Unit Tests for EA-203: Cross-Dimension Adaptive Optimizer

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))


class TestDimensionConfig(unittest.TestCase):
    def test_to_dict(self):
        from src.core.dimension_optimizer import DimensionConfig
        c = DimensionConfig(num_paths=3, max_turns=150, diversity=0.5)
        d = c.to_dict()
        self.assertEqual(d["num_paths"], 3)

    def test_from_dict(self):
        from src.core.dimension_optimizer import DimensionConfig
        c = DimensionConfig.from_dict({"num_paths": 4, "max_turns": 200, "diversity": 0.7})
        self.assertEqual(c.num_paths, 4)

    def test_to_key(self):
        from src.core.dimension_optimizer import DimensionConfig
        c = DimensionConfig(num_paths=3, max_turns=150, diversity=0.5)
        self.assertEqual(c.to_key(), "p3_d150_v0.5")


class TestDimensionRecommendation(unittest.TestCase):
    def test_to_dict(self):
        from src.core.dimension_optimizer import DimensionRecommendation, DimensionConfig
        r = DimensionRecommendation(
            task_type="search",
            recommended=DimensionConfig(3, 150, 0.5),
            confidence=0.7,
            reason="test",
        )
        d = r.to_dict()
        self.assertEqual(d["task_type"], "search")
        self.assertEqual(d["recommended"]["num_paths"], 3)


class TestRecordAndQuery(unittest.TestCase):
    def setUp(self):
        from src.core.strategy_tracker import StrategyRecordKeeper
        from src.core.dimension_optimizer import DimensionOptimizer, DimensionConfig
        tmpdir = tempfile.mkdtemp()
        keeper = StrategyRecordKeeper(data_dir=f"{tmpdir}/results")
        self.optimizer = DimensionOptimizer(
            record_keeper=keeper, data_dir=f"{tmpdir}/dim",
        )
        self.DimensionConfig = DimensionConfig

    def test_record_and_get(self):
        config = self.DimensionConfig(3, 150, 0.5)
        self.optimizer.record_run(config, "search", won=True, cost=0.02, duration=10)
        self.optimizer.record_run(config, "search", won=False, cost=0.03, duration=15)
        
        result = self.optimizer.get_results(config, "search")
        self.assertIsNotNone(result)
        self.assertEqual(result.sample_count, 2)
        self.assertAlmostEqual(result.win_rate, 0.5)

    def test_get_results_nonexistent(self):
        config = self.DimensionConfig(5, 300, 1.0)
        result = self.optimizer.get_results(config, "search")
        self.assertIsNone(result)

    def test_all_task_type_tracked(self):
        config = self.DimensionConfig(3, 150, 0.5)
        self.optimizer.record_run(config, "search", won=True, cost=0.02)
        
        result_all = self.optimizer.get_results(config, "all")
        self.assertIsNotNone(result_all)
        self.assertEqual(result_all.sample_count, 1)


class TestRecommendation(unittest.TestCase):
    def setUp(self):
        from src.core.strategy_tracker import StrategyRecordKeeper
        from src.core.dimension_optimizer import DimensionOptimizer, DimensionConfig
        tmpdir = tempfile.mkdtemp()
        keeper = StrategyRecordKeeper(data_dir=f"{tmpdir}/results")
        self.optimizer = DimensionOptimizer(
            record_keeper=keeper, data_dir=f"{tmpdir}/dim",
        )
        self.DimensionConfig = DimensionConfig

    def test_default_recommendation_no_data(self):
        rec = self.optimizer.recommend("search")
        self.assertEqual(rec.confidence, 0.0)
        self.assertEqual(rec.recommended.num_paths, 3)

    def test_recommendation_with_data(self):
        # Config A: 80% win rate, low cost
        config_a = self.DimensionConfig(2, 100, 0.5)
        for i in range(5):
            self.optimizer.record_run(config_a, "search", won=(i < 4), cost=0.01)
        
        # Config B: 40% win rate, high cost
        config_b = self.DimensionConfig(4, 200, 0.7)
        for i in range(5):
            self.optimizer.record_run(config_b, "search", won=(i < 2), cost=0.05)
        
        rec = self.optimizer.recommend("search")
        # Config A should win (higher efficiency)
        self.assertEqual(rec.recommended.num_paths, 2)

    def test_recommend_all_task_types(self):
        config = self.DimensionConfig(3, 150, 0.5)
        for i in range(5):
            self.optimizer.record_run(config, "search", won=True, cost=0.02)
            self.optimizer.record_run(config, "compute", won=False, cost=0.03)
        
        recs = self.optimizer.recommend_all_task_types()
        self.assertIn("all", recs)
        self.assertIn("search", recs)
        self.assertIn("compute", recs)


class TestExploration(unittest.TestCase):
    def test_suggest_untried(self):
        from src.core.strategy_tracker import StrategyRecordKeeper
        from src.core.dimension_optimizer import DimensionOptimizer, DEFAULT_CONFIGS
        tmpdir = tempfile.mkdtemp()
        keeper = StrategyRecordKeeper(data_dir=f"{tmpdir}/results")
        optimizer = DimensionOptimizer(record_keeper=keeper, data_dir=f"{tmpdir}/dim")
        
        suggestions = optimizer.suggest_exploration()
        # All defaults should be suggested since nothing was tried
        self.assertEqual(len(suggestions), len(DEFAULT_CONFIGS))

    def test_fewer_suggestions_after_data(self):
        from src.core.strategy_tracker import StrategyRecordKeeper
        from src.core.dimension_optimizer import DimensionOptimizer, DEFAULT_CONFIGS
        tmpdir = tempfile.mkdtemp()
        keeper = StrategyRecordKeeper(data_dir=f"{tmpdir}/results")
        optimizer = DimensionOptimizer(record_keeper=keeper, data_dir=f"{tmpdir}/dim")
        
        # Run one config enough times
        config = DEFAULT_CONFIGS[0]
        for i in range(10):
            optimizer.record_run(config, "search", won=True, cost=0.01)
        
        suggestions = optimizer.suggest_exploration()
        self.assertLess(len(suggestions), len(DEFAULT_CONFIGS))


class TestHeatmapData(unittest.TestCase):
    def test_heatmap(self):
        from src.core.strategy_tracker import StrategyRecordKeeper
        from src.core.dimension_optimizer import DimensionOptimizer, DimensionConfig
        tmpdir = tempfile.mkdtemp()
        keeper = StrategyRecordKeeper(data_dir=f"{tmpdir}/results")
        optimizer = DimensionOptimizer(record_keeper=keeper, data_dir=f"{tmpdir}/dim")
        
        config = DimensionConfig(3, 150, 0.5)
        for i in range(3):
            optimizer.record_run(config, "all", won=True, cost=0.02)
        
        data = optimizer.get_heatmap_data()
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["paths"], 3)
        self.assertAlmostEqual(data[0]["win_rate"], 1.0)


class TestPersistence(unittest.TestCase):
    def test_save_and_load(self):
        from src.core.strategy_tracker import StrategyRecordKeeper
        from src.core.dimension_optimizer import DimensionOptimizer, DimensionConfig
        tmpdir = tempfile.mkdtemp()
        keeper = StrategyRecordKeeper(data_dir=f"{tmpdir}/results")
        optimizer = DimensionOptimizer(record_keeper=keeper, data_dir=f"{tmpdir}/dim")
        
        config = DimensionConfig(3, 150, 0.5)
        for i in range(3):
            optimizer.record_run(config, "search", won=True, cost=0.02)
        
        optimizer.save()
        
        optimizer2 = DimensionOptimizer(record_keeper=keeper, data_dir=f"{tmpdir}/dim")
        optimizer2.load()
        
        result = optimizer2.get_results(config, "search")
        self.assertIsNotNone(result)
        self.assertEqual(result.sample_count, 3)


class TestSummary(unittest.TestCase):
    def test_empty_summary(self):
        from src.core.strategy_tracker import StrategyRecordKeeper
        from src.core.dimension_optimizer import DimensionOptimizer
        tmpdir = tempfile.mkdtemp()
        keeper = StrategyRecordKeeper(data_dir=f"{tmpdir}/results")
        optimizer = DimensionOptimizer(record_keeper=keeper, data_dir=f"{tmpdir}/dim")
        summary = optimizer.get_summary()
        self.assertIn("No dimension", summary)

    def test_summary_with_data(self):
        from src.core.strategy_tracker import StrategyRecordKeeper
        from src.core.dimension_optimizer import DimensionOptimizer, DimensionConfig
        tmpdir = tempfile.mkdtemp()
        keeper = StrategyRecordKeeper(data_dir=f"{tmpdir}/results")
        optimizer = DimensionOptimizer(record_keeper=keeper, data_dir=f"{tmpdir}/dim")
        
        config = DimensionConfig(3, 150, 0.5)
        for i in range(5):
            optimizer.record_run(config, "search", won=True, cost=0.02)
        
        summary = optimizer.get_summary()
        self.assertIn("1", summary)  # 1 config tested


if __name__ == "__main__":
    unittest.main(verbosity=2)
