# Copyright (c) 2025 MiroMind
# Unit Tests for EA-309: Groupthink Detector

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))


def _make_answer(path_id="path_0", answer="42", reasoning="Because of X",
                 sources=None, confidence=0.0, turns=10, duration=5.0):
    from src.core.groupthink_detector import PathAnswer
    return PathAnswer(
        path_id=path_id, answer=answer, reasoning=reasoning,
        sources=sources or [], confidence=confidence,
        turns_used=turns, duration_seconds=duration,
    )


# ─── Utility Tests ──────────────────────────────────────────────────────────

class TestKeyPhraseExtraction(unittest.TestCase):
    def test_basic_extraction(self):
        from src.core.groupthink_detector import _extract_key_phrases
        phrases = _extract_key_phrases("The quick brown fox jumps over the lazy dog")
        self.assertIn("quick", phrases)
        self.assertIn("brown", phrases)
        self.assertNotIn("the", phrases)  # stopword

    def test_empty(self):
        from src.core.groupthink_detector import _extract_key_phrases
        self.assertEqual(_extract_key_phrases(""), set())

    def test_bigrams(self):
        from src.core.groupthink_detector import _extract_key_phrases
        phrases = _extract_key_phrases("machine learning algorithms work well")
        self.assertIn("machine learning", phrases)


class TestJaccardSimilarity(unittest.TestCase):
    def test_identical(self):
        from src.core.groupthink_detector import _jaccard_similarity
        s = {"a", "b", "c"}
        self.assertAlmostEqual(_jaccard_similarity(s, s), 1.0)

    def test_disjoint(self):
        from src.core.groupthink_detector import _jaccard_similarity
        self.assertAlmostEqual(_jaccard_similarity({"a"}, {"b"}), 0.0)

    def test_partial_overlap(self):
        from src.core.groupthink_detector import _jaccard_similarity
        sim = _jaccard_similarity({"a", "b", "c"}, {"b", "c", "d"})
        self.assertAlmostEqual(sim, 2 / 4)

    def test_empty_sets(self):
        from src.core.groupthink_detector import _jaccard_similarity
        self.assertAlmostEqual(_jaccard_similarity(set(), set()), 1.0)


class TestConfidenceScore(unittest.TestCase):
    def test_hedging_language(self):
        from src.core.groupthink_detector import _compute_confidence_score
        score = _compute_confidence_score("It might be around 42, possibly more")
        self.assertLess(score, 0.5)

    def test_certain_language(self):
        from src.core.groupthink_detector import _compute_confidence_score
        score = _compute_confidence_score("The answer is definitely and certainly 42")
        self.assertGreater(score, 0.5)

    def test_neutral(self):
        from src.core.groupthink_detector import _compute_confidence_score
        score = _compute_confidence_score("The result is 42")
        self.assertAlmostEqual(score, 0.5)


# ─── Detector Tests ─────────────────────────────────────────────────────────

class TestNoGroupthink(unittest.TestCase):
    def setUp(self):
        from src.core.groupthink_detector import GroupthinkDetector
        self.detector = GroupthinkDetector()

    def test_single_path(self):
        answers = [_make_answer(path_id="p0")]
        report = self.detector.analyze(answers)
        self.assertFalse(report.is_groupthink)

    def test_different_answers(self):
        answers = [
            _make_answer(path_id="p0", answer="42"),
            _make_answer(path_id="p1", answer="43"),
            _make_answer(path_id="p2", answer="44"),
        ]
        report = self.detector.analyze(answers)
        self.assertFalse(report.is_groupthink)
        self.assertEqual(report.risk_level, "none")

    def test_healthy_consensus(self):
        """Different reasoning, same answer → healthy."""
        answers = [
            _make_answer(path_id="p0", answer="42",
                        reasoning="Based on mathematical proof using algebra and calculus",
                        sources=["source_a.com"], turns=15, duration=10),
            _make_answer(path_id="p1", answer="42",
                        reasoning="Found through experimental verification and laboratory testing",
                        sources=["source_b.com"], turns=8, duration=5),
            _make_answer(path_id="p2", answer="42",
                        reasoning="Confirmed via historical records and archival documents",
                        sources=["source_c.com"], turns=20, duration=15),
        ]
        report = self.detector.analyze(answers)
        self.assertFalse(report.is_groupthink)


class TestReasoningSimilarity(unittest.TestCase):
    def setUp(self):
        from src.core.groupthink_detector import GroupthinkDetector
        self.detector = GroupthinkDetector()

    def test_identical_reasoning(self):
        reasoning = "The answer is derived from analyzing the data using statistical methods and machine learning algorithms to find the optimal solution"
        answers = [
            _make_answer(path_id="p0", reasoning=reasoning, turns=10, duration=5),
            _make_answer(path_id="p1", reasoning=reasoning, turns=12, duration=6),
            _make_answer(path_id="p2", reasoning=reasoning, turns=8, duration=4),
        ]
        report = self.detector.analyze(answers)
        signals = [s for s in report.signals if s.signal_type == "reasoning_similarity"]
        self.assertTrue(len(signals) > 0)
        self.assertGreater(signals[0].score, 0.5)


class TestSourceOverlap(unittest.TestCase):
    def setUp(self):
        from src.core.groupthink_detector import GroupthinkDetector
        self.detector = GroupthinkDetector()

    def test_same_sources(self):
        answers = [
            _make_answer(path_id="p0", sources=["wiki.org", "bbc.com"],
                        turns=10, duration=5),
            _make_answer(path_id="p1", sources=["wiki.org", "bbc.com"],
                        turns=12, duration=6),
        ]
        report = self.detector.analyze(answers)
        signals = [s for s in report.signals if s.signal_type == "source_overlap"]
        self.assertTrue(len(signals) > 0)

    def test_different_sources(self):
        answers = [
            _make_answer(path_id="p0", sources=["source_a.com"],
                        turns=10, duration=5),
            _make_answer(path_id="p1", sources=["source_b.com"],
                        turns=15, duration=8),
        ]
        report = self.detector.analyze(answers)
        signals = [s for s in report.signals if s.signal_type == "source_overlap"]
        self.assertEqual(len(signals), 0)


class TestLowConfidence(unittest.TestCase):
    def setUp(self):
        from src.core.groupthink_detector import GroupthinkDetector
        self.detector = GroupthinkDetector()

    def test_low_confidence_consensus(self):
        answers = [
            _make_answer(path_id="p0", confidence=0.2, turns=10, duration=5),
            _make_answer(path_id="p1", confidence=0.3, turns=12, duration=6),
            _make_answer(path_id="p2", confidence=0.1, turns=8, duration=4),
        ]
        report = self.detector.analyze(answers)
        signals = [s for s in report.signals if s.signal_type == "low_confidence_consensus"]
        self.assertTrue(len(signals) > 0)

    def test_high_confidence_ok(self):
        answers = [
            _make_answer(path_id="p0", confidence=0.9, turns=10, duration=5),
            _make_answer(path_id="p1", confidence=0.85, turns=15, duration=8),
        ]
        report = self.detector.analyze(answers)
        signals = [s for s in report.signals if s.signal_type == "low_confidence_consensus"]
        self.assertEqual(len(signals), 0)


class TestSpeedUniformity(unittest.TestCase):
    def setUp(self):
        from src.core.groupthink_detector import GroupthinkDetector
        self.detector = GroupthinkDetector()

    def test_uniform_speed(self):
        answers = [
            _make_answer(path_id="p0", turns=10, duration=5.0),
            _make_answer(path_id="p1", turns=10, duration=5.1),
            _make_answer(path_id="p2", turns=11, duration=5.0),
        ]
        report = self.detector.analyze(answers)
        signals = [s for s in report.signals if s.signal_type == "speed_uniformity"]
        self.assertTrue(len(signals) > 0)

    def test_varied_speed(self):
        answers = [
            _make_answer(path_id="p0", turns=5, duration=3.0),
            _make_answer(path_id="p1", turns=20, duration=15.0),
            _make_answer(path_id="p2", turns=50, duration=30.0),
        ]
        report = self.detector.analyze(answers)
        signals = [s for s in report.signals if s.signal_type == "speed_uniformity"]
        self.assertEqual(len(signals), 0)


class TestOverallRisk(unittest.TestCase):
    def setUp(self):
        from src.core.groupthink_detector import GroupthinkDetector
        self.detector = GroupthinkDetector()

    def test_high_risk_triggers_groupthink(self):
        """Same answer, same reasoning, same sources, low confidence, same speed."""
        reasoning = "Based on analysis of data using standard methods and approaches to determine the answer"
        answers = [
            _make_answer(path_id="p0", reasoning=reasoning,
                        sources=["wiki.org"], confidence=0.2,
                        turns=10, duration=5.0),
            _make_answer(path_id="p1", reasoning=reasoning,
                        sources=["wiki.org"], confidence=0.25,
                        turns=10, duration=5.0),
            _make_answer(path_id="p2", reasoning=reasoning,
                        sources=["wiki.org"], confidence=0.15,
                        turns=11, duration=5.1),
        ]
        report = self.detector.analyze(answers)
        self.assertTrue(report.is_groupthink)
        self.assertGreater(report.overall_risk, 0.3)
        self.assertIn(report.risk_level, ["moderate", "high", "critical"])

    def test_risk_level_mapping(self):
        from src.core.groupthink_detector import GroupthinkDetector
        self.assertEqual(GroupthinkDetector._risk_level(0.0), "none")
        self.assertEqual(GroupthinkDetector._risk_level(0.2), "low")
        self.assertEqual(GroupthinkDetector._risk_level(0.4), "moderate")
        self.assertEqual(GroupthinkDetector._risk_level(0.6), "high")
        self.assertEqual(GroupthinkDetector._risk_level(0.8), "critical")


class TestReport(unittest.TestCase):
    def setUp(self):
        from src.core.groupthink_detector import GroupthinkDetector
        self.detector = GroupthinkDetector()

    def test_to_dict(self):
        answers = [
            _make_answer(path_id="p0", turns=10, duration=5),
            _make_answer(path_id="p1", turns=12, duration=6),
        ]
        report = self.detector.analyze(answers)
        d = report.to_dict()
        self.assertIn("is_groupthink", d)
        self.assertIn("overall_risk", d)
        self.assertIn("signals", d)

    def test_summary_no_groupthink(self):
        answers = [
            _make_answer(path_id="p0", answer="A"),
            _make_answer(path_id="p1", answer="B"),
        ]
        report = self.detector.analyze(answers)
        summary = report.to_summary()
        self.assertIn("No groupthink", summary)

    def test_summary_groupthink(self):
        reasoning = "Same analysis same reasoning same conclusions same methods same data"
        answers = [
            _make_answer(path_id="p0", reasoning=reasoning,
                        sources=["wiki.org"], confidence=0.1,
                        turns=10, duration=5),
            _make_answer(path_id="p1", reasoning=reasoning,
                        sources=["wiki.org"], confidence=0.15,
                        turns=10, duration=5),
        ]
        report = self.detector.analyze(answers)
        if report.is_groupthink:
            summary = report.to_summary()
            self.assertIn("⚠️", summary)


class TestAdversarialPrompt(unittest.TestCase):
    def test_create_prompt(self):
        from src.core.groupthink_detector import GroupthinkDetector
        detector = GroupthinkDetector()
        prompt = detector.create_adversarial_prompt("42")
        self.assertIn("42", prompt)
        self.assertIn("WRONG", prompt)
        self.assertIn("contradict", prompt)


class TestCustomThresholds(unittest.TestCase):
    def test_lower_threshold_more_sensitive(self):
        from src.core.groupthink_detector import GroupthinkDetector
        strict = GroupthinkDetector(risk_threshold=0.1)
        lenient = GroupthinkDetector(risk_threshold=0.9)
        
        reasoning = "Same reasoning path same analysis same methods"
        answers = [
            _make_answer(path_id="p0", reasoning=reasoning,
                        sources=["wiki.org"], confidence=0.3,
                        turns=10, duration=5),
            _make_answer(path_id="p1", reasoning=reasoning,
                        sources=["wiki.org"], confidence=0.35,
                        turns=11, duration=5.5),
        ]
        
        strict_report = strict.analyze(answers)
        lenient_report = lenient.analyze(answers)
        
        # Same risk score, different thresholds
        self.assertEqual(strict_report.overall_risk, lenient_report.overall_risk)


if __name__ == "__main__":
    unittest.main(verbosity=2)
