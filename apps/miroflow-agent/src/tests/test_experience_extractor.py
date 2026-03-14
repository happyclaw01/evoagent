# Copyright (c) 2025 MiroMind
# Unit Tests for EA-108: Experience Extractor

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
        input_tokens=500, output_tokens=200,
        timestamp=timestamp or time.time(),
    )


def _build_env(records):
    from src.core.strategy_tracker import StrategyRecordKeeper, StrategyProfileEngine
    from src.core.failure_analyzer import FailureAnalyzer
    from src.core.experience_extractor import ExperienceExtractor
    tmpdir = tempfile.mkdtemp()
    keeper = StrategyRecordKeeper(data_dir=f"{tmpdir}/results")
    for r in records:
        keeper.record(r)
    engine = StrategyProfileEngine(record_keeper=keeper, profile_dir=f"{tmpdir}/profiles")
    engine.build_profiles()
    analyzer = FailureAnalyzer(record_keeper=keeper)
    extractor = ExperienceExtractor(
        record_keeper=keeper, profile_engine=engine,
        failure_analyzer=analyzer, learnings_dir=f"{tmpdir}/learnings",
    )
    return extractor, tmpdir


class TestLearningEntry(unittest.TestCase):
    def test_to_dict(self):
        from src.core.experience_extractor import LearningEntry
        e = LearningEntry(
            entry_id="LRN-20260314-001",
            category="strategy_strength",
            summary="test summary",
        )
        d = e.to_dict()
        self.assertEqual(d["entry_id"], "LRN-20260314-001")

    def test_from_dict(self):
        from src.core.experience_extractor import LearningEntry
        d = {
            "entry_id": "LRN-001", "category": "cost_insight",
            "summary": "test", "detail": "detail",
            "priority": "high", "status": "pending",
            "task_type": "all", "strategy_name": "bf",
            "evidence": {}, "see_also": [],
            "timestamp": 1.0, "recurrence_count": 1,
        }
        e = LearningEntry.from_dict(d)
        self.assertEqual(e.category, "cost_insight")

    def test_to_markdown(self):
        from src.core.experience_extractor import LearningEntry
        e = LearningEntry(
            entry_id="LRN-001", category="strategy_strength",
            strategy_name="bf", summary="bf is great",
            detail="detailed explanation",
            evidence={"win_rate": 0.8},
        )
        md = e.to_markdown()
        self.assertIn("LRN-001", md)
        self.assertIn("bf is great", md)
        self.assertIn("win_rate", md)


class TestExtractStrengths(unittest.TestCase):
    def test_extracts_high_win_rate(self):
        records = [_make_result(task_id=f"t{i}", is_winner=(i < 8)) for i in range(10)]
        extractor, _ = _build_env(records)
        learnings = extractor.extract_all()
        strengths = [e for e in learnings if e.category == "strategy_strength"]
        self.assertTrue(len(strengths) > 0)

    def test_no_strength_for_low_win_rate(self):
        records = [_make_result(task_id=f"t{i}", is_winner=(i < 2)) for i in range(10)]
        extractor, _ = _build_env(records)
        learnings = extractor.extract_all()
        strengths = [e for e in learnings if e.category == "strategy_strength"]
        self.assertEqual(len(strengths), 0)


class TestExtractWeaknesses(unittest.TestCase):
    def test_extracts_low_win_rate(self):
        records = [_make_result(task_id=f"t{i}", is_winner=(i < 2)) for i in range(10)]
        extractor, _ = _build_env(records)
        learnings = extractor.extract_all()
        weaknesses = [e for e in learnings if e.category == "strategy_weakness"]
        self.assertTrue(len(weaknesses) > 0)


class TestExtractTaskFits(unittest.TestCase):
    def test_extracts_task_type_strength(self):
        records = []
        for i in range(5):
            records.append(_make_result(task_id=f"s{i}", task_type="search", is_winner=True))
        for i in range(5):
            records.append(_make_result(task_id=f"c{i}", task_type="compute", is_winner=False))
        extractor, _ = _build_env(records)
        learnings = extractor.extract_all()
        fits = [e for e in learnings if e.category == "task_strategy_fit"]
        self.assertTrue(len(fits) > 0)


class TestExtractCostInsights(unittest.TestCase):
    def test_extracts_expensive_strategy(self):
        records = []
        for i in range(5):
            records.append(_make_result(strategy="bf", task_id=f"bf{i}", cost=0.10))
        for i in range(5):
            records.append(_make_result(strategy="df", task_id=f"df{i}", cost=0.01))
        extractor, _ = _build_env(records)
        learnings = extractor.extract_all()
        costs = [e for e in learnings if e.category == "cost_insight"]
        self.assertTrue(len(costs) > 0)


class TestExtractTrends(unittest.TestCase):
    def test_extracts_declining_trend(self):
        records = []
        base = time.time()
        # Old: mostly wins
        for i in range(10):
            records.append(_make_result(task_id=f"old{i}", is_winner=True, timestamp=base + i))
        # Recent: mostly losses
        for i in range(10):
            records.append(_make_result(task_id=f"new{i}", is_winner=False, timestamp=base + 100 + i))
        extractor, _ = _build_env(records)
        learnings = extractor.extract_all()
        trends = [e for e in learnings if e.category == "performance_trend"]
        self.assertTrue(len(trends) > 0)


class TestExtractFailureLearnings(unittest.TestCase):
    def test_extracts_from_failure_patterns(self):
        records = [
            _make_result(task_id=f"t{i}", status="failed", failure_reason="timeout",
                         is_winner=False)
            for i in range(5)
        ]
        extractor, _ = _build_env(records)
        learnings = extractor.extract_all()
        failures = [e for e in learnings if e.category == "failure_pattern"]
        self.assertTrue(len(failures) > 0)


class TestExtractAll(unittest.TestCase):
    def test_empty_data(self):
        extractor, _ = _build_env([])
        learnings = extractor.extract_all()
        self.assertEqual(len(learnings), 0)

    def test_sorted_by_priority(self):
        records = []
        for i in range(10):
            records.append(_make_result(task_id=f"t{i}", is_winner=(i < 8)))
        extractor, _ = _build_env(records)
        learnings = extractor.extract_all()
        if len(learnings) >= 2:
            priorities = {"critical": 0, "high": 1, "medium": 2, "low": 3}
            for i in range(len(learnings) - 1):
                self.assertLessEqual(
                    priorities.get(learnings[i].priority, 4),
                    priorities.get(learnings[i + 1].priority, 4),
                )


class TestPersistence(unittest.TestCase):
    def test_save_learnings(self):
        records = [_make_result(task_id=f"t{i}", is_winner=(i < 8)) for i in range(10)]
        extractor, tmpdir = _build_env(records)
        md_path = extractor.save_learnings()
        self.assertTrue(Path(md_path).exists())
        json_path = Path(tmpdir) / "learnings" / "learnings.json"
        self.assertTrue(json_path.exists())

    def test_load_learnings(self):
        records = [_make_result(task_id=f"t{i}", is_winner=(i < 8)) for i in range(10)]
        extractor, _ = _build_env(records)
        extractor.save_learnings()
        loaded = extractor.load_learnings()
        self.assertTrue(len(loaded) > 0)


class TestQueryMethods(unittest.TestCase):
    def test_get_learnings_for_strategy(self):
        records = [_make_result(task_id=f"t{i}", is_winner=(i < 8)) for i in range(10)]
        extractor, _ = _build_env(records)
        learnings = extractor.get_learnings_for_strategy("breadth_first")
        for e in learnings:
            self.assertEqual(e.strategy_name, "breadth_first")

    def test_get_high_priority(self):
        records = [_make_result(task_id=f"t{i}", is_winner=(i < 8)) for i in range(10)]
        extractor, _ = _build_env(records)
        high = extractor.get_high_priority_learnings()
        for e in high:
            self.assertIn(e.priority, ("high", "critical"))


class TestSummary(unittest.TestCase):
    def test_empty_summary(self):
        extractor, _ = _build_env([])
        summary = extractor.get_summary()
        self.assertIn("No learnings", summary)

    def test_summary_with_data(self):
        records = [_make_result(task_id=f"t{i}", is_winner=(i < 8)) for i in range(10)]
        extractor, _ = _build_env(records)
        summary = extractor.get_summary()
        self.assertIn("Total:", summary)


if __name__ == "__main__":
    unittest.main(verbosity=2)
