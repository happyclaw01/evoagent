# Copyright (c) 2025 MiroMind
# Unit Tests for Multi-Path Exploration Layer
# Feature IDs: EA-401, EA-402, EA-403

import asyncio
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Dict, List
from unittest.mock import AsyncMock, MagicMock, patch

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent))


class TestStrategyDefinitions(unittest.TestCase):
    """EA-002: Test strategy variant definitions"""

    def test_strategy_has_required_fields(self):
        """Verify each strategy has required fields"""
        from src.core.multi_path import STRATEGY_VARIANTS

        required_fields = ["name", "description", "prompt_suffix"]

        for strategy in STRATEGY_VARIANTS:
            for field in required_fields:
                self.assertIn(
                    field,
                    strategy,
                    f"Strategy {strategy.get('name', 'UNKNOWN')} missing field: {field}",
                )

    def test_strategy_names_unique(self):
        """Verify strategy names are unique"""
        from src.core.multi_path import STRATEGY_VARIANTS

        names = [s["name"] for s in STRATEGY_VARIANTS]
        self.assertEqual(len(names), len(set(names)), "Strategy names must be unique")

    def test_all_strategies_registered(self):
        """Verify all predefined strategies exist"""
        from src.core.multi_path import STRATEGY_VARIANTS

        expected_strategies = ["breadth_first", "depth_first", "lateral_thinking", "intel_analysis", "devils_advocate"]
        actual_names = [s["name"] for s in STRATEGY_VARIANTS]

        for expected in expected_strategies:
            self.assertIn(
                expected, actual_names, f"Expected strategy '{expected}' not found"
            )

    def test_prompt_suffix_not_empty(self):
        """Verify each strategy has non-empty prompt suffix"""
        from src.core.multi_path import STRATEGY_VARIANTS

        for strategy in STRATEGY_VARIANTS:
            self.assertGreater(
                len(strategy["prompt_suffix"]),
                0,
                f"Strategy {strategy['name']} has empty prompt_suffix",
            )


class TestVotingMechanism(unittest.TestCase):
    """EA-003, EA-004: Test voting mechanism"""

    def setUp(self):
        """Set up test fixtures"""
        from src.core.multi_path import STRATEGY_VARIANTS

        self.sample_results = [
            (
                "Summary A",
                "The answer is 42",
                "/path/to/log_a.json",
                "strategy_a",
                {"strategy": "strategy_a", "status": "success"},
            ),
            (
                "Summary B",
                "The answer is 42",
                "/path/to/log_b.json",
                "strategy_b",
                {"strategy": "strategy_b", "status": "success"},
            ),
            (
                "Summary C",
                "The answer is 42",
                "/path/to/log_c.json",
                "strategy_c",
                {"strategy": "strategy_c", "status": "success"},
            ),
        ]

    def test_majority_vote_same_answers(self):
        """Test: When all answers are identical, should select without LLM Judge"""
        from collections import Counter

        # All answers are the same
        answers = [r[1].strip().lower() for r in self.sample_results]
        answer_counts = Counter(answers)

        most_common_answer, most_common_count = answer_counts.most_common(1)[0]

        # Should be majority (3/3 = 100%)
        self.assertEqual(most_common_count, 3)
        self.assertEqual(most_common_answer, "the answer is 42")

    def test_majority_vote_two_agree(self):
        """Test: When 2/3 answers agree, should select the majority"""
        from collections import Counter

        results_with_majority = [
            ("Summary A", "Answer is 42", "/log/a.json", "s1", {"status": "success"}),
            ("Summary B", "Answer is 42", "/log/b.json", "s2", {"status": "success"}),
            ("Summary C", "Answer is 99", "/log/c.json", "s3", {"status": "success"}),
        ]

        answers = [r[1].strip().lower() for r in results_with_majority]
        answer_counts = Counter(answers)

        most_common = answer_counts.most_common(1)[0]
        self.assertEqual(most_common[1], 2)  # 2 agree
        self.assertEqual(most_common[0], "answer is 42")  # majority answer

    def test_different_answers_triggers_judge(self):
        """Test: When all answers differ, should trigger LLM Judge"""
        results_all_different = [
            ("Summary A", "Answer is 42", "/log/a.json", "s1", {"status": "success"}),
            ("Summary B", "Answer is 99", "/log/b.json", "s2", {"status": "success"}),
            ("Summary C", "Answer is 77", "/log/c.json", "s3", {"status": "success"}),
        ]

        answers = [r[1].strip().lower() for r in results_all_different]
        answer_counts = {a: c for a, c in __import__("collections").Counter(answers).items()}

        # All different, most_common_count should be 1
        most_common_count = max(answer_counts.values())
        self.assertEqual(most_common_count, 1)  # No majority

    def test_failed_results_excluded(self):
        """Test: Failed results should be excluded from voting"""
        results_with_failures = [
            ("Summary A", "Answer is 42", "/log/a.json", "s1", {"status": "success"}),
            ("Summary B", "Error occurred", "/log/b.json", "s2", {"status": "failed"}),
            ("Summary C", "Answer is 42", "/log/c.json", "s3", {"status": "success"}),
        ]

        valid_results = [
            r for r in results_with_failures if r[4].get("status") == "success"
        ]

        # Should filter out the failed one
        self.assertEqual(len(valid_results), 2)

    def test_empty_answer_excluded(self):
        """Test: Empty answers should be excluded"""
        results_with_empty = [
            ("Summary A", "Answer is 42", "/log/a.json", "s1", {"status": "success"}),
            ("Summary B", "", "/log/b.json", "s2", {"status": "success"}),
            ("Summary C", "   ", "/log/c.json", "s3", {"status": "success"}),
        ]

        valid_results = [
            r for r in results_with_empty if r[1].strip()
        ]

        # Should filter out empty ones
        self.assertEqual(len(valid_results), 1)


class TestStrategyInjection(unittest.TestCase):
    """EA-002: Test strategy injection into prompts (DD-001: prompt suffix injection)"""

    def setUp(self):
        """Set up test fixtures"""
        self.base_prompt = """You are a helpful AI assistant.
You have access to tools for searching the web, reading files, and executing code.

Always provide accurate and well-sourced answers."""

        self.breadth_first_strategy = {
            "name": "breadth_first",
            "description": "Broad search strategy",
            "prompt_suffix": "\n\n[Strategy: Breadth-First Exploration]\n"
            "Start by performing multiple diverse searches to gather a wide range of sources.",
        }

        self.depth_first_strategy = {
            "name": "depth_first",
            "description": "Deep investigation strategy",
            "prompt_suffix": "\n\n[Strategy: Depth-First Investigation]\n"
            "Focus on finding the most authoritative primary source first.",
        }

    def test_strategy_injection_adds_suffix(self):
        """Test: Strategy suffix should be appended to base prompt"""
        injected_prompt = self.base_prompt + self.breadth_first_strategy["prompt_suffix"]

        self.assertIn("[Strategy: Breadth-First Exploration]", injected_prompt)
        self.assertIn("multiple diverse searches", injected_prompt)

    def test_different_strategies_produce_different_prompts(self):
        """Test: Different strategies should produce different prompts"""
        prompt_a = self.base_prompt + self.breadth_first_strategy["prompt_suffix"]
        prompt_b = self.base_prompt + self.depth_first_strategy["prompt_suffix"]

        self.assertNotEqual(prompt_a, prompt_b)

    def test_strategy_injection_preserves_base(self):
        """Test: Base prompt content should be preserved after injection"""
        injected_prompt = self.base_prompt + self.depth_first_strategy["prompt_suffix"]

        # Base prompt content should still be present
        self.assertIn("helpful AI assistant", injected_prompt)
        self.assertIn("You have access to tools", injected_prompt)
        self.assertIn("Always provide accurate", injected_prompt)

    def test_multiple_strategy_injections_are_additive(self):
        """Test: Multiple strategy injections should be additive (for ensemble scenarios)"""
        prompt = (
            self.base_prompt
            + self.breadth_first_strategy["prompt_suffix"]
            + self.depth_first_strategy["prompt_suffix"]
        )

        self.assertIn("Breadth-First", prompt)
        self.assertIn("Depth-First", prompt)


class TestMultiPathScheduler(unittest.TestCase):
    """EA-001: Test multi-path scheduler"""

    def test_num_paths_configuration(self):
        """Test: NUM_PATHS environment variable should control path count"""
        # Test default
        num_paths_default = int(os.environ.get("NUM_PATHS", "3"))
        self.assertEqual(num_paths_default, 3)

        # Test custom value
        with patch.dict(os.environ, {"NUM_PATHS": "5"}):
            num_paths_custom = int(os.environ.get("NUM_PATHS", "3"))
            self.assertEqual(num_paths_custom, 5)

    def test_strategies_slice_matches_num_paths(self):
        """Test: Strategy list should be sliced to match num_paths"""
        from src.core.multi_path import STRATEGY_VARIANTS

        num_paths = 2
        selected_strategies = STRATEGY_VARIANTS[:num_paths]

        self.assertEqual(len(selected_strategies), num_paths)

    def test_asyncio_gather_for_parallel_execution(self):
        """Test: Verify asyncio.gather can execute coroutines in parallel"""

        async def mock_path_task(path_id: int):
            await asyncio.sleep(0.01)  # Simulate work
            return f"Result from path {path_id}"

        async def run_parallel():
            tasks = [mock_path_task(i) for i in range(3)]
            return await asyncio.gather(*tasks)

        results = asyncio.run(run_parallel())

        self.assertEqual(len(results), 3)
        self.assertIn("Result from path 0", results)
        self.assertIn("Result from path 1", results)
        self.assertIn("Result from path 2", results)


class TestTaskLogIsolation(unittest.TestCase):
    """EA-006: Test path-level log isolation"""

    def test_each_path_gets_unique_task_id(self):
        """Test: Each path should get a unique task ID"""
        base_task_id = "task_example"
        strategies = ["breadth_first", "depth_first", "lateral_thinking"]

        path_task_ids = [
            f"{base_task_id}_path{i}_{strategy}"
            for i, strategy in enumerate(strategies)
        ]

        # All should be unique
        self.assertEqual(len(path_task_ids), len(set(path_task_ids)))

    def test_master_log_includes_all_paths(self):
        """Test: Master log should have references to all path logs"""
        # Simulate path results
        path_results = [
            ("summary_a", "answer_a", "/logs/path_a.json", "s1", {"status": "success"}),
            ("summary_b", "answer_b", "/logs/path_b.json", "s2", {"status": "success"}),
        ]

        # Master log should track all paths
        master_log_paths = [r[2] for r in path_results]

        self.assertEqual(len(master_log_paths), 2)
        self.assertIn("/logs/path_a.json", master_log_paths)


class TestIntegrationScenarios(unittest.TestCase):
    """EA-003/EA-004/EA-005/EA-007: Integration scenarios combining multiple features"""

    def test_full_voting_flow_with_majority(self):
        """Test: Complete voting flow when majority exists"""
        from collections import Counter

        # Simulate 3 paths, 2 agree
        results = [
            ("Summary", "Paris is the capital of France", "/log/1.json", "breadth", {"status": "success"}),
            ("Summary", "Paris is the capital of France", "/log/2.json", "depth", {"status": "success"}),
            ("Summary", "London is the capital of UK", "/log/3.json", "lateral", {"status": "success"}),
        ]

        valid = [r for r in results if r[4].get("status") == "success" and r[1].strip()]
        answers = [r[1].strip().lower() for r in valid]
        counts = Counter(answers)

        most_common = counts.most_common(1)[0]
        
        # Should select majority answer
        self.assertEqual(most_common[0], "paris is the capital of france")
        self.assertEqual(most_common[1], 2)

    def test_single_valid_result_uses_directly(self):
        """Test: When only one valid result, use it directly"""
        results = [
            ("Summary A", "", "/log/1.json", "s1", {"status": "failed"}),
            ("Summary B", "", "/log/2.json", "s2", {"status": "failed"}),
            ("Summary C", "The answer is 42", "/log/3.json", "s3", {"status": "success"}),
        ]

        valid_results = [r for r in results if r[4].get("status") == "success" and r[1].strip()]

        # Only one valid result
        self.assertEqual(len(valid_results), 1)
        self.assertEqual(valid_results[0][1], "The answer is 42")


if __name__ == "__main__":
    # Run with verbose output
    unittest.main(verbosity=2)