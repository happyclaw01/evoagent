# Copyright (c) 2025 MiroMind
# Unit Tests for EA-202: Strategy Code Evolution

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))


class TestStrategyCode(unittest.TestCase):
    def test_to_dict(self):
        from src.core.strategy_code_evolver import StrategyCode
        s = StrategyCode(name="test", description="d", prompt_suffix="p")
        d = s.to_dict()
        self.assertEqual(d["name"], "test")

    def test_from_dict(self):
        from src.core.strategy_code_evolver import StrategyCode
        s = StrategyCode(name="test", description="d", prompt_suffix="p",
                        search_breadth=5, verification_rounds=3)
        d = s.to_dict()
        s2 = StrategyCode.from_dict(d)
        self.assertEqual(s2.search_breadth, 5)
        self.assertEqual(s2.verification_rounds, 3)

    def test_enhanced_prompt_suffix(self):
        from src.core.strategy_code_evolver import StrategyCode
        s = StrategyCode(
            name="test", description="d", prompt_suffix="Base prompt.",
            tool_priority=["search", "scrape"],
            search_breadth=3,
            verification_rounds=2,
            pre_actions=["Plan first"],
            post_actions=["Verify all"],
        )
        prompt = s.get_enhanced_prompt_suffix()
        self.assertIn("Base prompt", prompt)
        self.assertIn("search, scrape", prompt)
        self.assertIn("3 different phrasings", prompt)
        self.assertIn("2 times", prompt)
        self.assertIn("Plan first", prompt)
        self.assertIn("Verify all", prompt)

    def test_no_backtrack_prompt(self):
        from src.core.strategy_code_evolver import StrategyCode
        s = StrategyCode(name="t", description="d", prompt_suffix="p",
                        backtrack_on_failure=False)
        prompt = s.get_enhanced_prompt_suffix()
        self.assertNotIn("restart", prompt)


class TestCodePatterns(unittest.TestCase):
    def test_all_builtin_patterns_exist(self):
        from src.core.strategy_code_evolver import CODE_PATTERNS
        expected = ["exhaustive_search", "hypothesis_driven", "divide_and_conquer",
                    "adversarial_search", "cost_efficient"]
        for name in expected:
            self.assertIn(name, CODE_PATTERNS)

    def test_builtin_have_descriptions(self):
        from src.core.strategy_code_evolver import CODE_PATTERNS
        for name, pattern in CODE_PATTERNS.items():
            self.assertTrue(len(pattern.description) > 0, f"{name} has no description")
            self.assertTrue(len(pattern.prompt_suffix) > 0, f"{name} has no prompt_suffix")


class TestStrategyCodeEvolver(unittest.TestCase):
    def setUp(self):
        from src.core.strategy_code_evolver import StrategyCodeEvolver
        self.evolver = StrategyCodeEvolver(patterns_dir=tempfile.mkdtemp())

    def test_get_pattern(self):
        pattern = self.evolver.get_pattern("hypothesis_driven")
        self.assertIsNotNone(pattern)
        self.assertEqual(pattern.name, "hypothesis_driven")

    def test_get_unknown_pattern(self):
        pattern = self.evolver.get_pattern("nonexistent")
        self.assertIsNone(pattern)

    def test_list_patterns(self):
        patterns = self.evolver.list_patterns()
        self.assertIn("exhaustive_search", patterns)
        self.assertIn("cost_efficient", patterns)

    def test_create_variant(self):
        variant = self.evolver.create_variant(
            "hypothesis_driven",
            variant_name="hypo_v2",
            search_breadth=5,
            verification_rounds=4,
        )
        self.assertEqual(variant.name, "hypo_v2")
        self.assertEqual(variant.search_breadth, 5)
        self.assertEqual(variant.verification_rounds, 4)
        self.assertEqual(variant.parent, "hypothesis_driven")
        self.assertEqual(variant.origin, "code_evolved")

    def test_create_variant_unknown_base(self):
        with self.assertRaises(ValueError):
            self.evolver.create_variant("nonexistent")

    def test_variant_appears_in_list(self):
        self.evolver.create_variant("cost_efficient", variant_name="cheap_v2")
        patterns = self.evolver.list_patterns()
        self.assertIn("cheap_v2", patterns)

    def test_evolve_high_win_rate(self):
        code = self.evolver.evolve_from_profile(
            "exhaustive_search", win_rate=0.8, avg_turns=200,
            strengths=["search"], weaknesses=[],
        )
        # High win rate + many turns → should reduce
        self.assertLess(code.max_turns, 200)

    def test_evolve_low_win_rate(self):
        code = self.evolver.evolve_from_profile(
            "cost_efficient", win_rate=0.2, avg_turns=60,
            strengths=[], weaknesses=["verify"],
        )
        # Low win rate → more verification
        self.assertGreater(code.verification_rounds, 1)
        self.assertTrue(code.backtrack_on_failure)

    def test_evolve_unknown_base(self):
        code = self.evolver.evolve_from_profile(
            "unknown_strategy", win_rate=0.5, avg_turns=100,
            strengths=[], weaknesses=[],
        )
        self.assertIn("unknown_strategy", code.name)


class TestPersistence(unittest.TestCase):
    def test_save_and_load(self):
        from src.core.strategy_code_evolver import StrategyCodeEvolver
        tmpdir = tempfile.mkdtemp()
        evolver = StrategyCodeEvolver(patterns_dir=tmpdir)
        evolver.create_variant("hypothesis_driven", variant_name="custom_v1",
                              search_breadth=7)
        saved = evolver.save()
        self.assertEqual(len(saved), 1)

        evolver2 = StrategyCodeEvolver(patterns_dir=tmpdir)
        loaded = evolver2.load()
        self.assertIn("custom_v1", loaded)
        self.assertEqual(loaded["custom_v1"].search_breadth, 7)


class TestSummary(unittest.TestCase):
    def test_summary(self):
        from src.core.strategy_code_evolver import StrategyCodeEvolver
        evolver = StrategyCodeEvolver(patterns_dir=tempfile.mkdtemp())
        summary = evolver.get_summary()
        self.assertIn("builtin", summary)
        self.assertIn("exhaustive_search", summary)


if __name__ == "__main__":
    unittest.main(verbosity=2)
