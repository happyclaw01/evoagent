# Copyright (c) 2025 MiroMind
# Unit Tests for EA-105: Strategy Parameter Micro-Evolution

import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))


def _make_result(strategy="breadth_first", task_id="t1", is_winner=True,
                 task_type="search", cost=0.01, turns=10, timestamp=None,
                 status="success"):
    from src.core.strategy_tracker import StrategyResult
    return StrategyResult(
        task_id=task_id, strategy_name=strategy, task_type=task_type,
        is_winner=is_winner, cost_usd=cost, turns_used=turns,
        timestamp=timestamp or time.time(), status=status,
    )


def _build_env(records):
    from src.core.strategy_tracker import StrategyRecordKeeper, StrategyProfileEngine
    from src.core.strategy_tuner import StrategyTuner
    tmpdir = tempfile.mkdtemp()
    keeper = StrategyRecordKeeper(data_dir=f"{tmpdir}/results")
    for r in records:
        keeper.record(r)
    engine = StrategyProfileEngine(record_keeper=keeper, profile_dir=f"{tmpdir}/profiles")
    engine.build_profiles()
    tuner = StrategyTuner(
        record_keeper=keeper, profile_engine=engine,
        params_dir=f"{tmpdir}/params",
    )
    return tuner, tmpdir


class TestTuningRecommendation(unittest.TestCase):
    """Test TuningRecommendation."""

    def test_to_dict(self):
        from src.core.strategy_tuner import TuningRecommendation
        rec = TuningRecommendation(
            strategy_name="bf", parameter="max_turns",
            current_value=100, recommended_value=120,
            confidence=0.7, reason="test", sample_size=10,
        )
        d = rec.to_dict()
        self.assertEqual(d["strategy_name"], "bf")
        self.assertEqual(d["recommended_value"], 120)


class TestTunedParameters(unittest.TestCase):
    """Test TunedParameters."""

    def test_get_max_turns_default(self):
        from src.core.strategy_tuner import TunedParameters
        p = TunedParameters(strategy_name="bf", max_turns=100, temperature_hint="balanced")
        self.assertEqual(p.get_max_turns(), 100)

    def test_get_max_turns_override(self):
        from src.core.strategy_tuner import TunedParameters
        p = TunedParameters(
            strategy_name="bf", max_turns=100, temperature_hint="balanced",
            task_type_overrides={"search": {"max_turns": 80}},
        )
        self.assertEqual(p.get_max_turns("search"), 80)
        self.assertEqual(p.get_max_turns("compute"), 100)

    def test_roundtrip(self):
        from src.core.strategy_tuner import TunedParameters
        p = TunedParameters(strategy_name="bf", max_turns=100, temperature_hint="balanced")
        d = p.to_dict()
        p2 = TunedParameters.from_dict(d)
        self.assertEqual(p2.strategy_name, "bf")
        self.assertEqual(p2.max_turns, 100)


class TestAnalyzeTurns(unittest.TestCase):
    """Test turn analysis."""

    def test_no_recommendation_insufficient_data(self):
        records = [_make_result(task_id=f"t{i}") for i in range(2)]
        tuner, _ = _build_env(records)
        recs = tuner.analyze("breadth_first")
        self.assertEqual(len(recs), 0)

    def test_winners_use_more_turns_recommends_increase(self):
        records = []
        for i in range(5):
            records.append(_make_result(task_id=f"w{i}", is_winner=True, turns=80))
            records.append(_make_result(task_id=f"l{i}", is_winner=False, turns=30))
        tuner, _ = _build_env(records)
        recs = tuner.analyze("breadth_first")
        turns_recs = [r for r in recs if r.parameter == "max_turns" and r.task_type == "all"]
        self.assertTrue(len(turns_recs) > 0)
        rec = turns_recs[0]
        self.assertGreater(rec.recommended_value, rec.current_value)

    def test_winners_use_fewer_turns_recommends_decrease(self):
        records = []
        for i in range(5):
            records.append(_make_result(task_id=f"w{i}", is_winner=True, turns=20))
            records.append(_make_result(task_id=f"l{i}", is_winner=False, turns=80))
        tuner, _ = _build_env(records)
        recs = tuner.analyze("breadth_first")
        turns_recs = [r for r in recs if r.parameter == "max_turns" and r.task_type == "all"]
        self.assertTrue(len(turns_recs) > 0)
        rec = turns_recs[0]
        self.assertLess(rec.recommended_value, rec.current_value)


class TestApplyRecommendations(unittest.TestCase):
    """Test applying recommendations."""

    def test_apply_updates_params(self):
        records = []
        for i in range(5):
            records.append(_make_result(task_id=f"w{i}", is_winner=True, turns=80))
            records.append(_make_result(task_id=f"l{i}", is_winner=False, turns=30))
        tuner, _ = _build_env(records)
        params = tuner.apply_recommendations("breadth_first")
        self.assertNotEqual(params.max_turns, 100)  # Should have been adjusted

    def test_apply_with_min_confidence(self):
        records = []
        for i in range(5):
            records.append(_make_result(task_id=f"w{i}", is_winner=True, turns=80))
            records.append(_make_result(task_id=f"l{i}", is_winner=False, turns=30))
        tuner, _ = _build_env(records)
        params = tuner.apply_recommendations("breadth_first", min_confidence=0.99)
        # No recommendation should pass 0.99 confidence threshold
        self.assertEqual(params.max_turns, 100)


class TestGetTunedParams(unittest.TestCase):
    """Test get_tuned_params auto-analysis."""

    def test_returns_defaults_when_no_data(self):
        tuner, _ = _build_env([])
        params = tuner.get_tuned_params("breadth_first")
        self.assertEqual(params.max_turns, 100)
        self.assertEqual(params.temperature_hint, "balanced")

    def test_returns_tuned_when_data_exists(self):
        records = []
        for i in range(5):
            records.append(_make_result(task_id=f"w{i}", is_winner=True, turns=80))
            records.append(_make_result(task_id=f"l{i}", is_winner=False, turns=30))
        tuner, _ = _build_env(records)
        params = tuner.get_tuned_params("breadth_first")
        self.assertIsNotNone(params)


class TestPersistence(unittest.TestCase):
    """Test save/load."""

    def test_save_and_load(self):
        from src.core.strategy_tuner import StrategyTuner
        from src.core.strategy_tracker import StrategyRecordKeeper, StrategyProfileEngine
        
        tmpdir = tempfile.mkdtemp()
        keeper = StrategyRecordKeeper(data_dir=f"{tmpdir}/results")
        for i in range(5):
            keeper.record(_make_result(task_id=f"w{i}", is_winner=True, turns=80))
            keeper.record(_make_result(task_id=f"l{i}", is_winner=False, turns=30))
        engine = StrategyProfileEngine(record_keeper=keeper, profile_dir=f"{tmpdir}/profiles")
        engine.build_profiles()
        
        tuner = StrategyTuner(record_keeper=keeper, profile_engine=engine,
                              params_dir=f"{tmpdir}/params")
        tuner.apply_recommendations("breadth_first")
        saved = tuner.save()
        self.assertTrue(len(saved) > 0)
        
        # Load in fresh tuner
        tuner2 = StrategyTuner(record_keeper=keeper, profile_engine=engine,
                               params_dir=f"{tmpdir}/params")
        loaded = tuner2.load()
        self.assertIn("breadth_first", loaded)


if __name__ == "__main__":
    unittest.main(verbosity=2)
