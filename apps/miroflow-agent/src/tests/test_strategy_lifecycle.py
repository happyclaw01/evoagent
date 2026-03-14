# Copyright (c) 2025 MiroMind
# Unit Tests for EA-107: Strategy Lifecycle Management

import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))


def _make_result(strategy="breadth_first", task_id="t1", is_winner=True,
                 task_type="search", cost=0.01, turns=10, status="success",
                 failure_reason="", timestamp=None):
    from src.core.strategy_tracker import StrategyResult
    return StrategyResult(
        task_id=task_id, strategy_name=strategy, task_type=task_type,
        is_winner=is_winner, cost_usd=cost, turns_used=turns,
        status=status, failure_reason=failure_reason,
        timestamp=timestamp or time.time(),
    )


def _build_env(records):
    from src.core.strategy_tracker import StrategyRecordKeeper, StrategyProfileEngine
    from src.core.failure_analyzer import FailureAnalyzer
    from src.core.strategy_lifecycle import StrategyLifecycleManager
    tmpdir = tempfile.mkdtemp()
    keeper = StrategyRecordKeeper(data_dir=f"{tmpdir}/results")
    for r in records:
        keeper.record(r)
    engine = StrategyProfileEngine(record_keeper=keeper, profile_dir=f"{tmpdir}/profiles")
    engine.build_profiles()
    analyzer = FailureAnalyzer(record_keeper=keeper)
    manager = StrategyLifecycleManager(
        profile_engine=engine, failure_analyzer=analyzer,
        state_dir=f"{tmpdir}/lifecycle",
    )
    return manager, tmpdir


class TestLifecycleStatus(unittest.TestCase):
    def test_enum_values(self):
        from src.core.strategy_lifecycle import LifecycleStatus
        self.assertEqual(LifecycleStatus.ACTIVE, "active")
        self.assertEqual(LifecycleStatus.RETIRED, "retired")


class TestLifecycleEvent(unittest.TestCase):
    def test_to_dict(self):
        from src.core.strategy_lifecycle import LifecycleEvent
        e = LifecycleEvent(
            strategy_name="bf", from_status="active",
            to_status="probation", reason="test",
        )
        d = e.to_dict()
        self.assertEqual(d["strategy_name"], "bf")

    def test_from_dict(self):
        from src.core.strategy_lifecycle import LifecycleEvent
        d = {"strategy_name": "bf", "from_status": "active",
             "to_status": "probation", "reason": "test", "timestamp": 1.0, "metrics": {}}
        e = LifecycleEvent.from_dict(d)
        self.assertEqual(e.strategy_name, "bf")


class TestStrategyState(unittest.TestCase):
    def test_roundtrip(self):
        from src.core.strategy_lifecycle import StrategyState, LifecycleStatus
        s = StrategyState(strategy_name="bf", status=LifecycleStatus.PROBATION)
        d = s.to_dict()
        s2 = StrategyState.from_dict(d)
        self.assertEqual(s2.status, LifecycleStatus.PROBATION)


class TestCandidateToActive(unittest.TestCase):
    def test_few_runs_stays_candidate(self):
        records = [_make_result(task_id=f"t{i}") for i in range(3)]
        manager, _ = _build_env(records)
        event = manager.evaluate("breadth_first")
        state = manager.get_state("breadth_first")
        self.assertEqual(state.status.value, "candidate")

    def test_enough_runs_becomes_active(self):
        from src.core.strategy_lifecycle import LifecycleStatus
        records = [_make_result(task_id=f"t{i}") for i in range(6)]
        manager, _ = _build_env(records)
        # Set to candidate first (as a new strategy would be)
        state = manager.get_state("breadth_first")
        state.status = LifecycleStatus.CANDIDATE
        event = manager.evaluate("breadth_first")
        self.assertIsNotNone(event)
        self.assertEqual(event.to_status, "active")


class TestActiveToProbation(unittest.TestCase):
    def test_low_win_rate_triggers_probation(self):
        from src.core.strategy_lifecycle import LifecycleStatus
        records = []
        for i in range(15):
            records.append(_make_result(task_id=f"t{i}", is_winner=(i < 2)))
        manager, _ = _build_env(records)
        # Set initial state to active
        state = manager.get_state("breadth_first")
        state.status = LifecycleStatus.ACTIVE
        event = manager.evaluate("breadth_first")
        self.assertIsNotNone(event)
        self.assertEqual(event.to_status, "probation")

    def test_good_win_rate_stays_active(self):
        from src.core.strategy_lifecycle import LifecycleStatus
        records = [_make_result(task_id=f"t{i}", is_winner=(i < 8)) for i in range(10)]
        manager, _ = _build_env(records)
        state = manager.get_state("breadth_first")
        state.status = LifecycleStatus.ACTIVE
        event = manager.evaluate("breadth_first")
        self.assertIsNone(event)


class TestProbationTransitions(unittest.TestCase):
    def test_recovery(self):
        from src.core.strategy_lifecycle import LifecycleStatus
        records = [_make_result(task_id=f"t{i}", is_winner=(i < 7)) for i in range(10)]
        manager, _ = _build_env(records)
        state = manager.get_state("breadth_first")
        state.status = LifecycleStatus.PROBATION
        state.probation_since = time.time() - 1000
        event = manager.evaluate("breadth_first")
        self.assertIsNotNone(event)
        self.assertEqual(event.to_status, "active")

    def test_retirement(self):
        from src.core.strategy_lifecycle import LifecycleStatus
        records = [_make_result(task_id=f"t{i}", is_winner=(i < 1)) for i in range(25)]
        manager, _ = _build_env(records)
        state = manager.get_state("breadth_first")
        state.status = LifecycleStatus.PROBATION
        state.probation_since = time.time() - 1000
        event = manager.evaluate("breadth_first")
        self.assertIsNotNone(event)
        self.assertEqual(event.to_status, "retired")


class TestResurrection(unittest.TestCase):
    def test_resurrect_retired(self):
        from src.core.strategy_lifecycle import LifecycleStatus
        manager, _ = _build_env([])
        state = manager.get_state("bf")
        state.status = LifecycleStatus.RETIRED
        event = manager.resurrect("bf", "Testing resurrection")
        self.assertIsNotNone(event)
        self.assertEqual(event.to_status, "probation")
        self.assertEqual(state.resurrection_count, 1)

    def test_max_resurrections(self):
        from src.core.strategy_lifecycle import LifecycleStatus
        manager, _ = _build_env([])
        state = manager.get_state("bf")
        state.status = LifecycleStatus.RETIRED
        state.resurrection_count = 3  # MAX
        event = manager.resurrect("bf")
        self.assertIsNone(event)

    def test_cannot_resurrect_active(self):
        manager, _ = _build_env([])
        event = manager.resurrect("bf")
        self.assertIsNone(event)


class TestEvaluateAll(unittest.TestCase):
    def test_evaluate_all(self):
        records = []
        for i in range(10):
            records.append(_make_result(strategy="bf", task_id=f"bf{i}", is_winner=True))
            records.append(_make_result(strategy="df", task_id=f"df{i}", is_winner=True))
        manager, _ = _build_env(records)
        events = manager.evaluate_all()
        self.assertIsInstance(events, list)


class TestGetStrategies(unittest.TestCase):
    def test_get_active(self):
        records = [_make_result(strategy="bf", task_id=f"t{i}") for i in range(10)]
        manager, _ = _build_env(records)
        manager.evaluate_all()
        active = manager.get_active_strategies()
        self.assertIn("bf", active)

    def test_get_retired(self):
        from src.core.strategy_lifecycle import LifecycleStatus
        manager, _ = _build_env([])
        state = manager.get_state("bf")
        state.status = LifecycleStatus.RETIRED
        retired = manager.get_retired_strategies()
        self.assertIn("bf", retired)


class TestPersistence(unittest.TestCase):
    def test_save_and_load(self):
        from src.core.strategy_lifecycle import StrategyLifecycleManager, LifecycleStatus
        records = [_make_result(task_id=f"t{i}") for i in range(10)]
        manager, tmpdir = _build_env(records)
        manager.evaluate("breadth_first")
        saved = manager.save()
        self.assertTrue(len(saved) > 0)

        from src.core.strategy_tracker import StrategyRecordKeeper, StrategyProfileEngine
        from src.core.failure_analyzer import FailureAnalyzer
        keeper2 = StrategyRecordKeeper(data_dir=f"{tmpdir}/results")
        engine2 = StrategyProfileEngine(record_keeper=keeper2, profile_dir=f"{tmpdir}/profiles")
        analyzer2 = FailureAnalyzer(record_keeper=keeper2)
        manager2 = StrategyLifecycleManager(
            profile_engine=engine2, failure_analyzer=analyzer2,
            state_dir=f"{tmpdir}/lifecycle",
        )
        loaded = manager2.load()
        self.assertIn("breadth_first", loaded)


class TestSummary(unittest.TestCase):
    def test_empty_summary(self):
        manager, _ = _build_env([])
        self.assertEqual(manager.get_summary(), "No lifecycle data yet.")

    def test_summary_content(self):
        from src.core.strategy_lifecycle import LifecycleStatus
        manager, _ = _build_env([])
        state = manager.get_state("bf")
        state.status = LifecycleStatus.ACTIVE
        summary = manager.get_summary()
        self.assertIn("bf", summary)
        self.assertIn("active", summary)


if __name__ == "__main__":
    unittest.main(verbosity=2)
