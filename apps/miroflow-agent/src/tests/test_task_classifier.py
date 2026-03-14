# Copyright (c) 2025 MiroMind
# Unit Tests for EA-103: Task Type Classifier

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))


class TestTaskType(unittest.TestCase):
    """Test TaskType enum."""

    def test_all_types(self):
        from src.core.task_classifier import TaskType
        expected = ["search", "compute", "creative", "verify", "multi-hop", "unknown"]
        for t in expected:
            self.assertIn(t, [tt.value for tt in TaskType])

    def test_string_value(self):
        from src.core.task_classifier import TaskType
        self.assertEqual(TaskType.SEARCH, "search")
        self.assertEqual(TaskType.COMPUTE, "compute")


class TestClassificationResult(unittest.TestCase):
    """Test ClassificationResult."""

    def test_to_dict(self):
        from src.core.task_classifier import ClassificationResult, TaskType
        r = ClassificationResult(
            task_type=TaskType.SEARCH,
            confidence=0.85,
            scores={"search": 0.85, "compute": 0.2},
            method="rule",
        )
        d = r.to_dict()
        self.assertEqual(d["task_type"], "search")
        self.assertEqual(d["confidence"], 0.85)


class TestComputeClassification(unittest.TestCase):
    """Test compute task classification."""

    def setUp(self):
        from src.core.task_classifier import TaskClassifier
        self.classifier = TaskClassifier()

    def test_calculate(self):
        r = self.classifier.classify("Calculate the average GDP growth rate")
        self.assertEqual(r.task_type.value, "compute")

    def test_how_much(self):
        r = self.classifier.classify("How much revenue did Apple generate in 2024?")
        self.assertEqual(r.task_type.value, "compute")

    def test_chinese_compute(self):
        r = self.classifier.classify("计算2024年中国GDP增长率是多少")
        self.assertEqual(r.task_type.value, "compute")

    def test_math_expression(self):
        r = self.classifier.classify("What is 125 * 3.14 + 200?")
        self.assertEqual(r.task_type.value, "compute")

    def test_financial_metric(self):
        r = self.classifier.classify("What is the P/E ratio of Tesla?")
        self.assertEqual(r.task_type.value, "compute")


class TestSearchClassification(unittest.TestCase):
    """Test search task classification."""

    def setUp(self):
        from src.core.task_classifier import TaskClassifier
        self.classifier = TaskClassifier()

    def test_who_is(self):
        r = self.classifier.classify("Who is the CEO of OpenAI?")
        self.assertEqual(r.task_type.value, "search")

    def test_when_did(self):
        r = self.classifier.classify("When did World War II end?")
        self.assertEqual(r.task_type.value, "search")

    def test_find(self):
        r = self.classifier.classify("Find the latest news about Bitcoin")
        self.assertEqual(r.task_type.value, "search")

    def test_chinese_search(self):
        r = self.classifier.classify("谁是中国的第一任总理")
        self.assertEqual(r.task_type.value, "search")

    def test_definition(self):
        r = self.classifier.classify("What does quantum entanglement mean?")
        self.assertEqual(r.task_type.value, "search")


class TestVerifyClassification(unittest.TestCase):
    """Test verify task classification."""

    def setUp(self):
        from src.core.task_classifier import TaskClassifier
        self.classifier = TaskClassifier()

    def test_is_it_true(self):
        r = self.classifier.classify("Is it true that the Earth is flat?")
        self.assertEqual(r.task_type.value, "verify")

    def test_fact_check(self):
        r = self.classifier.classify("Fact-check: Tesla sold 1 million cars in 2023")
        self.assertEqual(r.task_type.value, "verify")

    def test_chinese_verify(self):
        r = self.classifier.classify("验证一下这个说法是否正确")
        self.assertEqual(r.task_type.value, "verify")


class TestCreativeClassification(unittest.TestCase):
    """Test creative task classification."""

    def setUp(self):
        from src.core.task_classifier import TaskClassifier
        self.classifier = TaskClassifier()

    def test_write(self):
        r = self.classifier.classify("Write a short story about a robot")
        self.assertEqual(r.task_type.value, "creative")

    def test_brainstorm(self):
        r = self.classifier.classify("Brainstorm ideas for a new mobile app")
        self.assertEqual(r.task_type.value, "creative")

    def test_chinese_creative(self):
        r = self.classifier.classify("写一篇关于人工智能的文章")
        self.assertEqual(r.task_type.value, "creative")

    def test_suggest(self):
        r = self.classifier.classify("Suggest 5 names for a coffee shop")
        self.assertEqual(r.task_type.value, "creative")


class TestMultiHopClassification(unittest.TestCase):
    """Test multi-hop task classification."""

    def setUp(self):
        from src.core.task_classifier import TaskClassifier
        self.classifier = TaskClassifier()

    def test_compare(self):
        r = self.classifier.classify("Compare the economic policies of USA and China")
        self.assertEqual(r.task_type.value, "multi-hop")

    def test_explain_why(self):
        r = self.classifier.classify("Explain why inflation affects stock markets")
        self.assertEqual(r.task_type.value, "multi-hop")

    def test_analyze(self):
        r = self.classifier.classify("Analyze the relationship between interest rates and housing prices")
        self.assertEqual(r.task_type.value, "multi-hop")

    def test_chinese_multi_hop(self):
        r = self.classifier.classify("比较中美两国的科技发展策略有什么区别")
        self.assertEqual(r.task_type.value, "multi-hop")


class TestEdgeCases(unittest.TestCase):
    """Test edge cases."""

    def setUp(self):
        from src.core.task_classifier import TaskClassifier, TaskType
        self.classifier = TaskClassifier()
        self.TaskType = TaskType

    def test_empty_input(self):
        r = self.classifier.classify("")
        self.assertEqual(r.task_type, self.TaskType.UNKNOWN)
        self.assertEqual(r.confidence, 0.0)

    def test_whitespace_only(self):
        r = self.classifier.classify("   ")
        self.assertEqual(r.task_type, self.TaskType.UNKNOWN)

    def test_gibberish(self):
        r = self.classifier.classify("asdfghjkl qwerty")
        self.assertEqual(r.task_type, self.TaskType.UNKNOWN)

    def test_confidence_range(self):
        r = self.classifier.classify("Calculate the sum of 1 + 2 + 3")
        self.assertGreaterEqual(r.confidence, 0.0)
        self.assertLessEqual(r.confidence, 1.0)

    def test_scores_populated(self):
        r = self.classifier.classify("Who is the president?")
        self.assertIn("search", r.scores)

    def test_method_is_rule(self):
        r = self.classifier.classify("What is AI?")
        self.assertEqual(r.method, "rule")


class TestHeuristics(unittest.TestCase):
    """Test additional heuristics."""

    def setUp(self):
        from src.core.task_classifier import TaskClassifier
        self.classifier = TaskClassifier()

    def test_math_expression_heuristic(self):
        r = self.classifier.classify("100 + 200 = ?")
        self.assertEqual(r.task_type.value, "compute")

    def test_compare_x_and_y_heuristic(self):
        r = self.classifier.classify("compare apple and google stock performance")
        self.assertEqual(r.task_type.value, "multi-hop")

    def test_url_boosts_search(self):
        r = self.classifier.classify("Find information from https://example.com")
        self.assertEqual(r.task_type.value, "search")


class TestBatchClassification(unittest.TestCase):
    """Test batch classification."""

    def setUp(self):
        from src.core.task_classifier import TaskClassifier
        self.classifier = TaskClassifier()

    def test_classify_batch(self):
        tasks = [
            "Calculate GDP",
            "Who is the CEO?",
            "Write a poem",
        ]
        results = self.classifier.classify_batch(tasks)
        self.assertEqual(len(results), 3)
        self.assertEqual(results[0].task_type.value, "compute")
        self.assertEqual(results[1].task_type.value, "search")
        self.assertEqual(results[2].task_type.value, "creative")

    def test_type_distribution(self):
        tasks = [
            "Calculate X",
            "Calculate Y",
            "Who is Z?",
            "Write something",
        ]
        dist = self.classifier.get_type_distribution(tasks)
        self.assertEqual(dist["compute"], 2)
        self.assertEqual(dist["search"], 1)
        self.assertEqual(dist["creative"], 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
