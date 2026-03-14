# Copyright (c) 2025 MiroMind
# Unit Tests for EA-101: Strategy Record Keeper + EA-102: Strategy Profile Engine

import json
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))


def _make_result(strategy="breadth_first", task_id="task_001", is_winner=True,
                 task_type="search", turns=10, cost=0.01, status="success",
                 duration=5.0, input_tokens=1000, output_tokens=500,
                 timestamp=None, failure_reason=""):
    from src.core.strategy_tracker import StrategyResult
    return StrategyResult(
        task_id=task_id,
        strategy_name=strategy,
        task_type=task_type,
        is_winner=is_winner,
        turns_used=turns,
        cost_usd=cost,
        status=status,
        duration_seconds=duration,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        timestamp=timestamp or time.time(),
        failure_reason=failure_reason,
    )


# ─── EA-101 Tests ───────────────────────────────────────────────────────────


class TestStrategyResult(unittest.TestCase):
    """Test StrategyResult dataclass."""

    def test_create(self):
        r = _make_result()
        self.assertEqual(r.strategy_name, "breadth_first")
        self.assertTrue(r.is_winner)

    def test_to_dict(self):
        r = _make_result()
        d = r.to_dict()
        self.assertEqual(d["strategy_name"], "breadth_first")
        self.assertIn("timestamp", d)

    def test_from_dict(self):
        from src.core.strategy_tracker import StrategyResult
        r = _make_result()
        d = r.to_dict()
        r2 = StrategyResult.from_dict(d)
        self.assertEqual(r2.strategy_name, r.strategy_name)
        self.assertEqual(r2.is_winner, r.is_winner)

    def test_from_dict_extra_fields(self):
        from src.core.strategy_tracker import StrategyResult
        d = {"task_id": "t1", "strategy_name": "bf", "extra_field": "ignored"}
        r = StrategyResult.from_dict(d)
        self.assertEqual(r.strategy_name, "bf")


class TestStrategyRecordKeeper(unittest.TestCase):
    """Test EA-101 record keeping."""

    def test_record_single(self):
        from src.core.strategy_tracker import StrategyRecordKeeper
        with tempfile.TemporaryDirectory() as tmpdir:
            keeper = StrategyRecordKeeper(data_dir=tmpdir)
            r = _make_result()
            filepath = keeper.record(r)
            self.assertTrue(Path(filepath).exists())

    def test_record_and_load(self):
        from src.core.strategy_tracker import StrategyRecordKeeper
        with tempfile.TemporaryDirectory() as tmpdir:
            keeper = StrategyRecordKeeper(data_dir=tmpdir)
            keeper.record(_make_result(task_id="t1", strategy="breadth_first"))
            keeper.record(_make_result(task_id="t1", strategy="depth_first"))
            
            # Fresh keeper loads from disk
            keeper2 = StrategyRecordKeeper(data_dir=tmpdir)
            records = keeper2.load_all()
            self.assertEqual(len(records), 2)

    def test_record_batch(self):
        from src.core.strategy_tracker import StrategyRecordKeeper
        with tempfile.TemporaryDirectory() as tmpdir:
            keeper = StrategyRecordKeeper(data_dir=tmpdir)
            results = [
                _make_result(task_id="t1", strategy="bf"),
                _make_result(task_id="t1", strategy="df"),
                _make_result(task_id="t1", strategy="lt"),
            ]
            paths = keeper.record_batch(results)
            self.assertEqual(len(paths), 3)

    def test_get_records_for_strategy(self):
        from src.core.strategy_tracker import StrategyRecordKeeper
        with tempfile.TemporaryDirectory() as tmpdir:
            keeper = StrategyRecordKeeper(data_dir=tmpdir)
            keeper.record(_make_result(task_id="t1", strategy="bf"))
            keeper.record(_make_result(task_id="t2", strategy="df"))
            keeper.record(_make_result(task_id="t3", strategy="bf"))
            
            bf_records = keeper.get_records_for_strategy("bf")
            self.assertEqual(len(bf_records), 2)

    def test_get_records_for_task_type(self):
        from src.core.strategy_tracker import StrategyRecordKeeper
        with tempfile.TemporaryDirectory() as tmpdir:
            keeper = StrategyRecordKeeper(data_dir=tmpdir)
            keeper.record(_make_result(task_id="t1", task_type="search"))
            keeper.record(_make_result(task_id="t2", task_type="compute"))
            keeper.record(_make_result(task_id="t3", task_type="search"))
            
            search_records = keeper.get_records_for_task_type("search")
            self.assertEqual(len(search_records), 2)

    def test_get_recent_records(self):
        from src.core.strategy_tracker import StrategyRecordKeeper
        with tempfile.TemporaryDirectory() as tmpdir:
            keeper = StrategyRecordKeeper(data_dir=tmpdir)
            base_time = time.time()
            for i in range(5):
                keeper.record(_make_result(task_id=f"t{i}", timestamp=base_time + i))
            
            recent = keeper.get_recent_records(n=3)
            self.assertEqual(len(recent), 3)
            self.assertEqual(recent[0].task_id, "t4")  # Most recent

    def test_total_records(self):
        from src.core.strategy_tracker import StrategyRecordKeeper
        with tempfile.TemporaryDirectory() as tmpdir:
            keeper = StrategyRecordKeeper(data_dir=tmpdir)
            keeper.record(_make_result(task_id="t1"))
            keeper.record(_make_result(task_id="t2"))
            self.assertEqual(keeper.total_records, 2)

    def test_strategy_names(self):
        from src.core.strategy_tracker import StrategyRecordKeeper
        with tempfile.TemporaryDirectory() as tmpdir:
            keeper = StrategyRecordKeeper(data_dir=tmpdir)
            keeper.record(_make_result(strategy="bf"))
            keeper.record(_make_result(strategy="df"))
            keeper.record(_make_result(strategy="bf"))
            names = keeper.get_strategy_names()
            self.assertEqual(set(names), {"bf", "df"})

    def test_clear(self):
        from src.core.strategy_tracker import StrategyRecordKeeper
        with tempfile.TemporaryDirectory() as tmpdir:
            keeper = StrategyRecordKeeper(data_dir=tmpdir)
            keeper.record(_make_result())
            keeper.clear()
            # After clear, load_all reloads from disk
            self.assertEqual(keeper.total_records, 1)


# ─── EA-102 Tests ───────────────────────────────────────────────────────────


class TestStrategyProfile(unittest.TestCase):
    """Test StrategyProfile dataclass."""

    def test_to_summary(self):
        from src.core.strategy_tracker import StrategyProfile
        p = StrategyProfile(
            strategy_name="breadth_first",
            total_runs=20,
            wins=14,
            win_rate=0.7,
            avg_cost_usd=0.015,
            status="active",
            trend="improving",
        )
        s = p.to_summary()
        self.assertIn("breadth_first", s)
        self.assertIn("70%", s)
        self.assertIn("active", s)

    def test_to_dict_and_back(self):
        from src.core.strategy_tracker import StrategyProfile
        p = StrategyProfile(
            strategy_name="depth_first",
            total_runs=10,
            wins=7,
            win_rate=0.7,
            task_type_win_rates={"search": 0.8, "compute": 0.6},
        )
        d = p.to_dict()
        p2 = StrategyProfile.from_dict(d)
        self.assertEqual(p2.strategy_name, "depth_first")
        self.assertEqual(p2.task_type_win_rates["search"], 0.8)


class TestProfileEngineBasic(unittest.TestCase):
    """Test basic profile building."""

    def _setup(self, records):
        from src.core.strategy_tracker import StrategyRecordKeeper, StrategyProfileEngine
        tmpdir = tempfile.mkdtemp()
        keeper = StrategyRecordKeeper(data_dir=f"{tmpdir}/results")
        for r in records:
            keeper.record(r)
        engine = StrategyProfileEngine(
            record_keeper=keeper,
            profile_dir=f"{tmpdir}/profiles",
        )
        return engine, tmpdir

    def test_build_empty(self):
        engine, _ = self._setup([])
        profiles = engine.build_profiles()
        self.assertEqual(len(profiles), 0)

    def test_build_single_strategy(self):
        records = [
            _make_result(task_id=f"t{i}", strategy="bf", is_winner=(i % 2 == 0))
            for i in range(10)
        ]
        engine, _ = self._setup(records)
        profiles = engine.build_profiles()
        
        self.assertIn("bf", profiles)
        p = profiles["bf"]
        self.assertEqual(p.total_runs, 10)
        self.assertEqual(p.wins, 5)
        self.assertAlmostEqual(p.win_rate, 0.5)

    def test_build_multiple_strategies(self):
        records = [
            _make_result(task_id="t1", strategy="bf", is_winner=True),
            _make_result(task_id="t1", strategy="df", is_winner=False),
            _make_result(task_id="t2", strategy="bf", is_winner=True),
            _make_result(task_id="t2", strategy="df", is_winner=False),
        ]
        engine, _ = self._setup(records)
        profiles = engine.build_profiles()
        
        self.assertEqual(profiles["bf"].win_rate, 1.0)
        self.assertEqual(profiles["df"].win_rate, 0.0)

    def test_cost_averages(self):
        records = [
            _make_result(task_id="t1", cost=0.01, turns=10, duration=5.0),
            _make_result(task_id="t2", cost=0.02, turns=20, duration=10.0),
        ]
        engine, _ = self._setup(records)
        profiles = engine.build_profiles()
        p = profiles["breadth_first"]
        self.assertAlmostEqual(p.avg_cost_usd, 0.015)
        self.assertAlmostEqual(p.avg_turns, 15.0)
        self.assertAlmostEqual(p.avg_duration_seconds, 7.5)

    def test_failure_counting(self):
        records = [
            _make_result(task_id="t1", status="success", is_winner=True),
            _make_result(task_id="t2", status="failed", is_winner=False, failure_reason="timeout"),
            _make_result(task_id="t3", status="cancelled", is_winner=False),
        ]
        engine, _ = self._setup(records)
        profiles = engine.build_profiles()
        p = profiles["breadth_first"]
        self.assertEqual(p.failures, 1)
        self.assertEqual(p.cancellations, 1)


class TestProfileEngineTaskType(unittest.TestCase):
    """Test task type analysis."""

    def _setup_with_types(self):
        from src.core.strategy_tracker import StrategyRecordKeeper, StrategyProfileEngine
        tmpdir = tempfile.mkdtemp()
        keeper = StrategyRecordKeeper(data_dir=f"{tmpdir}/results")
        
        # bf wins at search, loses at compute
        for i in range(5):
            keeper.record(_make_result(task_id=f"s{i}", strategy="bf", task_type="search", is_winner=True))
        for i in range(5):
            keeper.record(_make_result(task_id=f"c{i}", strategy="bf", task_type="compute", is_winner=False))
        
        engine = StrategyProfileEngine(
            record_keeper=keeper,
            profile_dir=f"{tmpdir}/profiles",
        )
        return engine

    def test_task_type_win_rates(self):
        engine = self._setup_with_types()
        profiles = engine.build_profiles()
        p = profiles["bf"]
        self.assertAlmostEqual(p.task_type_win_rates["search"], 1.0)
        self.assertAlmostEqual(p.task_type_win_rates["compute"], 0.0)

    def test_strengths_weaknesses(self):
        engine = self._setup_with_types()
        profiles = engine.build_profiles()
        p = profiles["bf"]
        self.assertIn("search", p.strengths)
        self.assertIn("compute", p.weaknesses)

    def test_best_strategy_for(self):
        from src.core.strategy_tracker import StrategyRecordKeeper, StrategyProfileEngine
        tmpdir = tempfile.mkdtemp()
        keeper = StrategyRecordKeeper(data_dir=f"{tmpdir}/results")
        
        # bf: 80% on search, df: 40% on search
        for i in range(5):
            keeper.record(_make_result(task_id=f"s{i}a", strategy="bf", task_type="search",
                                        is_winner=(i < 4)))  # 4/5 = 80%
            keeper.record(_make_result(task_id=f"s{i}b", strategy="df", task_type="search",
                                        is_winner=(i < 2)))  # 2/5 = 40%
        
        engine = StrategyProfileEngine(record_keeper=keeper, profile_dir=f"{tmpdir}/profiles")
        best = engine.get_best_strategy_for("search")
        self.assertEqual(best, "bf")


class TestProfileEngineTrend(unittest.TestCase):
    """Test trend detection."""

    def test_improving_trend(self):
        from src.core.strategy_tracker import StrategyRecordKeeper, StrategyProfileEngine
        tmpdir = tempfile.mkdtemp()
        keeper = StrategyRecordKeeper(data_dir=f"{tmpdir}/results")
        
        base_time = time.time()
        # Old: mostly losses
        for i in range(10):
            keeper.record(_make_result(task_id=f"old{i}", is_winner=(i > 7),
                                        timestamp=base_time + i))
        # Recent: mostly wins
        for i in range(10):
            keeper.record(_make_result(task_id=f"new{i}", is_winner=(i < 8),
                                        timestamp=base_time + 100 + i))
        
        engine = StrategyProfileEngine(record_keeper=keeper, profile_dir=f"{tmpdir}/profiles")
        profiles = engine.build_profiles()
        p = profiles["breadth_first"]
        self.assertEqual(p.trend, "improving")

    def test_stable_trend_few_samples(self):
        from src.core.strategy_tracker import StrategyRecordKeeper, StrategyProfileEngine
        tmpdir = tempfile.mkdtemp()
        keeper = StrategyRecordKeeper(data_dir=f"{tmpdir}/results")
        keeper.record(_make_result(task_id="t1"))
        keeper.record(_make_result(task_id="t2"))
        
        engine = StrategyProfileEngine(record_keeper=keeper, profile_dir=f"{tmpdir}/profiles")
        profiles = engine.build_profiles()
        self.assertEqual(profiles["breadth_first"].trend, "stable")


class TestProfileEngineLifecycle(unittest.TestCase):
    """Test strategy lifecycle status."""

    def test_active_status(self):
        from src.core.strategy_tracker import StrategyRecordKeeper, StrategyProfileEngine
        tmpdir = tempfile.mkdtemp()
        keeper = StrategyRecordKeeper(data_dir=f"{tmpdir}/results")
        for i in range(10):
            keeper.record(_make_result(task_id=f"t{i}", is_winner=(i % 2 == 0)))
        
        engine = StrategyProfileEngine(record_keeper=keeper, profile_dir=f"{tmpdir}/profiles")
        profiles = engine.build_profiles()
        self.assertEqual(profiles["breadth_first"].status, "active")

    def test_probation_status(self):
        from src.core.strategy_tracker import StrategyRecordKeeper, StrategyProfileEngine
        tmpdir = tempfile.mkdtemp()
        keeper = StrategyRecordKeeper(data_dir=f"{tmpdir}/results")
        # Win rate 1/10 = 10% < 25% probation threshold, but < 20 samples so not retired
        for i in range(10):
            keeper.record(_make_result(task_id=f"t{i}", is_winner=(i == 0)))
        
        engine = StrategyProfileEngine(record_keeper=keeper, profile_dir=f"{tmpdir}/profiles")
        profiles = engine.build_profiles()
        self.assertEqual(profiles["breadth_first"].status, "probation")

    def test_retired_status(self):
        from src.core.strategy_tracker import StrategyRecordKeeper, StrategyProfileEngine
        tmpdir = tempfile.mkdtemp()
        keeper = StrategyRecordKeeper(data_dir=f"{tmpdir}/results")
        # Win rate 2/25 = 8% < 15% + samples >= 20 → retired
        for i in range(25):
            keeper.record(_make_result(task_id=f"t{i}", is_winner=(i < 2)))
        
        engine = StrategyProfileEngine(record_keeper=keeper, profile_dir=f"{tmpdir}/profiles")
        profiles = engine.build_profiles()
        self.assertEqual(profiles["breadth_first"].status, "retired")


class TestProfileEngineRankings(unittest.TestCase):
    """Test strategy rankings."""

    def test_rankings(self):
        from src.core.strategy_tracker import StrategyRecordKeeper, StrategyProfileEngine
        tmpdir = tempfile.mkdtemp()
        keeper = StrategyRecordKeeper(data_dir=f"{tmpdir}/results")
        
        for i in range(10):
            keeper.record(_make_result(task_id=f"t{i}a", strategy="bf", is_winner=(i < 8)))  # 80%
            keeper.record(_make_result(task_id=f"t{i}b", strategy="df", is_winner=(i < 5)))  # 50%
            keeper.record(_make_result(task_id=f"t{i}c", strategy="lt", is_winner=(i < 3)))  # 30%
        
        engine = StrategyProfileEngine(record_keeper=keeper, profile_dir=f"{tmpdir}/profiles")
        engine.build_profiles()
        rankings = engine.get_rankings()
        
        self.assertEqual(rankings[0][0], "bf")
        self.assertEqual(rankings[1][0], "df")

    def test_rankings_exclude_retired(self):
        from src.core.strategy_tracker import StrategyRecordKeeper, StrategyProfileEngine
        tmpdir = tempfile.mkdtemp()
        keeper = StrategyRecordKeeper(data_dir=f"{tmpdir}/results")
        
        # bf: 80%, df: retired (2/25 = 8%)
        for i in range(10):
            keeper.record(_make_result(task_id=f"t{i}", strategy="bf", is_winner=(i < 8)))
        for i in range(25):
            keeper.record(_make_result(task_id=f"r{i}", strategy="df", is_winner=(i < 2)))
        
        engine = StrategyProfileEngine(record_keeper=keeper, profile_dir=f"{tmpdir}/profiles")
        engine.build_profiles()
        rankings = engine.get_rankings()
        
        strategy_names = [r[0] for r in rankings]
        self.assertNotIn("df", strategy_names)


class TestProfileEnginePersistence(unittest.TestCase):
    """Test save/load profiles."""

    def test_save_and_load(self):
        from src.core.strategy_tracker import StrategyRecordKeeper, StrategyProfileEngine
        tmpdir = tempfile.mkdtemp()
        keeper = StrategyRecordKeeper(data_dir=f"{tmpdir}/results")
        for i in range(5):
            keeper.record(_make_result(task_id=f"t{i}", strategy="bf", is_winner=(i < 3)))
            keeper.record(_make_result(task_id=f"t{i}", strategy="df", is_winner=(i < 4)))
        
        engine = StrategyProfileEngine(record_keeper=keeper, profile_dir=f"{tmpdir}/profiles")
        engine.build_profiles()
        saved = engine.save_profiles()
        self.assertTrue(len(saved) > 0)
        
        # Load from fresh engine
        engine2 = StrategyProfileEngine(record_keeper=keeper, profile_dir=f"{tmpdir}/profiles")
        loaded = engine2.load_profiles()
        self.assertIn("bf", loaded)
        self.assertIn("df", loaded)
        self.assertEqual(loaded["bf"].total_runs, 5)

    def test_l0_summary_saved(self):
        from src.core.strategy_tracker import StrategyRecordKeeper, StrategyProfileEngine
        tmpdir = tempfile.mkdtemp()
        keeper = StrategyRecordKeeper(data_dir=f"{tmpdir}/results")
        keeper.record(_make_result(task_id="t1", strategy="bf"))
        
        engine = StrategyProfileEngine(record_keeper=keeper, profile_dir=f"{tmpdir}/profiles")
        engine.build_profiles()
        engine.save_profiles()
        
        abstract_path = Path(f"{tmpdir}/profiles/.abstract")
        self.assertTrue(abstract_path.exists())
        content = abstract_path.read_text()
        self.assertIn("bf", content)


class TestL0Summary(unittest.TestCase):
    """Test L0 summary generation."""

    def test_empty_summary(self):
        from src.core.strategy_tracker import StrategyRecordKeeper, StrategyProfileEngine
        tmpdir = tempfile.mkdtemp()
        keeper = StrategyRecordKeeper(data_dir=f"{tmpdir}/results")
        engine = StrategyProfileEngine(record_keeper=keeper, profile_dir=f"{tmpdir}/profiles")
        summary = engine.get_l0_summary()
        self.assertEqual(summary, "No strategy data yet.")

    def test_summary_content(self):
        from src.core.strategy_tracker import StrategyRecordKeeper, StrategyProfileEngine
        tmpdir = tempfile.mkdtemp()
        keeper = StrategyRecordKeeper(data_dir=f"{tmpdir}/results")
        for i in range(5):
            keeper.record(_make_result(task_id=f"t{i}", strategy="bf", is_winner=(i < 4)))
        
        engine = StrategyProfileEngine(record_keeper=keeper, profile_dir=f"{tmpdir}/profiles")
        engine.build_profiles()
        summary = engine.get_l0_summary()
        self.assertIn("bf", summary)
        self.assertIn("80%", summary)
        self.assertIn("active", summary)


if __name__ == "__main__":
    unittest.main(verbosity=2)
