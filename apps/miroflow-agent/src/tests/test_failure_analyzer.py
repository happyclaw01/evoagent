# Copyright (c) 2025 MiroMind
# Unit Tests for EA-106: Failure Pattern Analysis

import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))


def _make_result(strategy="breadth_first", task_id="t1", is_winner=False,
                 task_type="search", cost=0.01, turns=10, status="failed",
                 failure_reason="timeout", timestamp=None):
    from src.core.strategy_tracker import StrategyResult
    return StrategyResult(
        task_id=task_id, strategy_name=strategy, task_type=task_type,
        is_winner=is_winner, cost_usd=cost, turns_used=turns,
        status=status, failure_reason=failure_reason,
        input_tokens=500, output_tokens=200,
        timestamp=timestamp or time.time(),
    )


def _build_env(records):
    from src.core.strategy_tracker import StrategyRecordKeeper
    from src.core.failure_analyzer import FailureAnalyzer
    tmpdir = tempfile.mkdtemp()
    keeper = StrategyRecordKeeper(data_dir=f"{tmpdir}/results")
    for r in records:
        keeper.record(r)
    analyzer = FailureAnalyzer(record_keeper=keeper)
    return analyzer


class TestEmptyAnalysis(unittest.TestCase):
    """Test analysis with no data."""

    def test_no_records(self):
        analyzer = _build_env([])
        report = analyzer.analyze("breadth_first")
        self.assertEqual(report.total_runs, 0)
        self.assertEqual(report.failure_rate, 0.0)
        self.assertEqual(len(report.patterns), 0)

    def test_no_failures(self):
        records = [
            _make_result(task_id=f"t{i}", status="success", is_winner=True, failure_reason="")
            for i in range(5)
        ]
        analyzer = _build_env(records)
        report = analyzer.analyze("breadth_first")
        self.assertEqual(report.total_failures, 0)
        self.assertAlmostEqual(report.failure_rate, 0.0)


class TestRepeatedReasons(unittest.TestCase):
    """Test repeated failure reason detection."""

    def test_detects_repeated_reason(self):
        records = [
            _make_result(task_id=f"t{i}", failure_reason="rate_limit")
            for i in range(5)
        ]
        analyzer = _build_env(records)
        report = analyzer.analyze("breadth_first")
        repeated = [p for p in report.patterns if p.pattern_type == "repeated_reason"]
        self.assertTrue(len(repeated) > 0)
        self.assertIn("rate_limit", repeated[0].failure_reasons)

    def test_no_detection_below_threshold(self):
        records = [
            _make_result(task_id="t1", failure_reason="timeout"),
            _make_result(task_id="t2", failure_reason="timeout"),
        ]
        analyzer = _build_env(records)
        report = analyzer.analyze("breadth_first")
        repeated = [p for p in report.patterns if p.pattern_type == "repeated_reason"]
        self.assertEqual(len(repeated), 0)

    def test_multiple_reasons(self):
        records = []
        for i in range(4):
            records.append(_make_result(task_id=f"a{i}", failure_reason="timeout"))
        for i in range(4):
            records.append(_make_result(task_id=f"b{i}", failure_reason="rate_limit"))
        analyzer = _build_env(records)
        report = analyzer.analyze("breadth_first")
        repeated = [p for p in report.patterns if p.pattern_type == "repeated_reason"]
        self.assertEqual(len(repeated), 2)


class TestTaskTypeWeakness(unittest.TestCase):
    """Test task type weakness detection."""

    def test_detects_weakness(self):
        records = []
        for i in range(5):
            records.append(_make_result(task_id=f"s{i}", task_type="search",
                                         status="failed", failure_reason="no_results"))
        # Add some successes for overall context
        for i in range(5):
            records.append(_make_result(task_id=f"c{i}", task_type="compute",
                                         status="success", is_winner=True, failure_reason=""))
        analyzer = _build_env(records)
        report = analyzer.analyze("breadth_first")
        weaknesses = [p for p in report.patterns if p.pattern_type == "task_type_weakness"]
        self.assertTrue(len(weaknesses) > 0)
        self.assertIn("search", weaknesses[0].affected_task_types)

    def test_no_weakness_below_threshold(self):
        records = []
        for i in range(5):
            status = "failed" if i < 1 else "success"
            records.append(_make_result(task_id=f"t{i}", task_type="search",
                                         status=status, failure_reason="err" if i < 1 else ""))
        analyzer = _build_env(records)
        report = analyzer.analyze("breadth_first")
        weaknesses = [p for p in report.patterns if p.pattern_type == "task_type_weakness"]
        self.assertEqual(len(weaknesses), 0)


class TestTemporalClusters(unittest.TestCase):
    """Test temporal failure clustering."""

    def test_detects_cluster(self):
        base_time = time.time()
        records = [
            _make_result(task_id=f"t{i}", timestamp=base_time + i * 60)
            for i in range(5)  # 5 failures within 5 minutes
        ]
        analyzer = _build_env(records)
        report = analyzer.analyze("breadth_first")
        clusters = [p for p in report.patterns if p.pattern_type == "temporal_cluster"]
        self.assertTrue(len(clusters) > 0)

    def test_no_cluster_when_spread(self):
        base_time = time.time()
        records = [
            _make_result(task_id=f"t{i}", timestamp=base_time + i * 7200)
            for i in range(3)  # 3 failures spread over 6 hours
        ]
        analyzer = _build_env(records)
        report = analyzer.analyze("breadth_first")
        clusters = [p for p in report.patterns if p.pattern_type == "temporal_cluster"]
        self.assertEqual(len(clusters), 0)


class TestCostWaste(unittest.TestCase):
    """Test cost waste detection."""

    def test_detects_high_waste(self):
        records = []
        # 7 failures at $0.05 each = $0.35
        for i in range(7):
            records.append(_make_result(task_id=f"f{i}", cost=0.05))
        # 3 successes at $0.05 each = $0.15
        for i in range(3):
            records.append(_make_result(task_id=f"s{i}", status="success",
                                         is_winner=True, cost=0.05, failure_reason=""))
        # Total $0.50, wasted $0.35 = 70%
        analyzer = _build_env(records)
        report = analyzer.analyze("breadth_first")
        waste = [p for p in report.patterns if p.pattern_type == "cost_waste"]
        self.assertTrue(len(waste) > 0)
        self.assertEqual(waste[0].severity, "critical")

    def test_no_waste_when_low(self):
        records = []
        # 1 failure, 9 successes
        records.append(_make_result(task_id="f1", cost=0.05))
        for i in range(9):
            records.append(_make_result(task_id=f"s{i}", status="success",
                                         is_winner=True, cost=0.05, failure_reason=""))
        analyzer = _build_env(records)
        report = analyzer.analyze("breadth_first")
        waste = [p for p in report.patterns if p.pattern_type == "cost_waste"]
        self.assertEqual(len(waste), 0)


class TestFailureReport(unittest.TestCase):
    """Test FailureReport."""

    def test_to_dict(self):
        records = [_make_result(task_id=f"t{i}") for i in range(5)]
        analyzer = _build_env(records)
        report = analyzer.analyze("breadth_first")
        d = report.to_dict()
        self.assertIn("strategy_name", d)
        self.assertIn("patterns", d)

    def test_has_critical_patterns(self):
        records = []
        for i in range(5):
            records.append(_make_result(task_id=f"t{i}", task_type="search"))
        analyzer = _build_env(records)
        report = analyzer.analyze("breadth_first")
        # 100% failure rate on search → critical
        self.assertTrue(report.has_critical_patterns())

    def test_summary(self):
        records = [_make_result(task_id=f"t{i}") for i in range(5)]
        analyzer = _build_env(records)
        report = analyzer.analyze("breadth_first")
        summary = report.to_summary()
        self.assertIn("breadth_first", summary)
        self.assertIn("100%", summary)

    def test_top_failure_reasons(self):
        records = []
        for i in range(3):
            records.append(_make_result(task_id=f"a{i}", failure_reason="timeout"))
        for i in range(2):
            records.append(_make_result(task_id=f"b{i}", failure_reason="rate_limit"))
        analyzer = _build_env(records)
        report = analyzer.analyze("breadth_first")
        self.assertEqual(report.top_failure_reasons[0][0], "timeout")
        self.assertEqual(report.top_failure_reasons[0][1], 3)


class TestAnalyzeAll(unittest.TestCase):
    """Test cross-strategy analysis."""

    def test_analyze_all(self):
        records = [
            _make_result(strategy="bf", task_id="t1"),
            _make_result(strategy="df", task_id="t2"),
        ]
        analyzer = _build_env(records)
        reports = analyzer.analyze_all()
        self.assertIn("bf", reports)
        self.assertIn("df", reports)

    def test_strategies_needing_attention(self):
        records = []
        for i in range(10):
            records.append(_make_result(strategy="bf", task_id=f"bf{i}"))  # 100% failure
        for i in range(10):
            records.append(_make_result(strategy="df", task_id=f"df{i}",
                                         status="success", is_winner=True, failure_reason=""))
        analyzer = _build_env(records)
        attention = analyzer.get_strategies_needing_attention()
        self.assertIn("bf", attention)
        self.assertNotIn("df", attention)

    def test_failure_summary(self):
        records = [_make_result(task_id=f"t{i}") for i in range(5)]
        analyzer = _build_env(records)
        summary = analyzer.get_failure_summary()
        self.assertIn("breadth_first", summary)


if __name__ == "__main__":
    unittest.main(verbosity=2)
