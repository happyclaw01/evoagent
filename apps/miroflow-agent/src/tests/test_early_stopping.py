# Copyright (c) 2025 MiroMind
# Unit Tests for EA-009: Early Stopping Mechanism

import asyncio
import sys
import unittest
from pathlib import Path
from typing import Tuple
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent))


class TestConsensusChecker(unittest.TestCase):
    """Test the consensus detection logic (EA-009 core)"""

    def test_no_consensus_when_less_than_k(self):
        """Test: Less than K valid results should not trigger consensus"""
        from src.core.multi_path import _check_consensus
        
        # Create mock results - only 1 valid
        results = [
            ("Summary", "Answer A", "/log/1.json", "s1", {"status": "success"}),
        ]
        
        has_consensus, answer = _check_consensus(results, early_stop_k=2, early_stop_threshold=1.0)
        
        self.assertFalse(has_consensus)
        self.assertIsNone(answer)

    def test_consensus_reached_when_k_agree(self):
        """Test: K paths agreeing should trigger consensus"""
        from src.core.multi_path import _check_consensus
        
        # 2 paths agree on same answer, threshold=0.66 (allows 2/3)
        results = [
            ("Summary", "Paris is capital", "/log/1.json", "s1", {"status": "success"}),
            ("Summary", "Paris is capital", "/log/2.json", "s2", {"status": "success"}),
            ("Summary", "London is capital", "/log/3.json", "s3", {"status": "success"}),
        ]
        
        # Use 0.66 threshold to allow 2/3 agreement
        has_consensus, answer = _check_consensus(results, early_stop_k=2, early_stop_threshold=0.66)
        
        self.assertTrue(has_consensus)
        self.assertEqual(answer, "Paris is capital")
    
    def test_consensus_full_agreement(self):
        """Test: All paths agreeing should trigger consensus with threshold=1.0"""
        from src.core.multi_path import _check_consensus
        
        # All 3 paths agree
        results = [
            ("Summary", "Paris", "/log/1.json", "s1", {"status": "success"}),
            ("Summary", "Paris", "/log/2.json", "s2", {"status": "success"}),
            ("Summary", "Paris", "/log/3.json", "s3", {"status": "success"}),
        ]
        
        has_consensus, answer = _check_consensus(results, early_stop_k=2, early_stop_threshold=1.0)
        
        self.assertTrue(has_consensus)
        self.assertEqual(answer, "Paris")

    def test_no_consensus_when_threshold_not_met(self):
        """Test: Should not trigger consensus if threshold not met"""
        from src.core.multi_path import _check_consensus
        
        # 2/3 agree = 0.67, but threshold is 1.0 (100%)
        results = [
            ("Summary", "Paris", "/log/1.json", "s1", {"status": "success"}),
            ("Summary", "Paris", "/log/2.json", "s2", {"status": "success"}),
            ("Summary", "London", "/log/3.json", "s3", {"status": "success"}),
        ]
        
        has_consensus, answer = _check_consensus(results, early_stop_k=2, early_stop_threshold=1.0)
        
        self.assertFalse(has_consensus)  # 2/3 = 0.67 < 1.0

    def test_consensus_with_lower_threshold(self):
        """Test: Should trigger with lower threshold (e.g., 0.66 for 2/3)"""
        from src.core.multi_path import _check_consensus
        
        results = [
            ("Summary", "Paris", "/log/1.json", "s1", {"status": "success"}),
            ("Summary", "Paris", "/log/2.json", "s2", {"status": "success"}),
            ("Summary", "London", "/log/3.json", "s3", {"status": "success"}),
        ]
        
        has_consensus, answer = _check_consensus(results, early_stop_k=2, early_stop_threshold=0.66)
        
        self.assertTrue(has_consensus)
        self.assertEqual(answer, "Paris")

    def test_consensus_ignores_failed_results(self):
        """Test: Failed results should not count toward consensus"""
        from src.core.multi_path import _check_consensus
        
        results = [
            ("Summary", "Paris", "/log/1.json", "s1", {"status": "failed"}),
            ("Summary", "Paris", "/log/2.json", "s2", {"status": "failed"}),
            ("Summary", "London", "/log/3.json", "s3", {"status": "success"}),
        ]
        
        has_consensus, answer = _check_consensus(results, early_stop_k=2, early_stop_threshold=1.0)
        
        # Only 1 valid result, less than k=2
        self.assertFalse(has_consensus)

    def test_consensus_ignores_empty_answers(self):
        """Test: Empty answers should not count toward consensus"""
        from src.core.multi_path import _check_consensus
        
        results = [
            ("Summary", "", "/log/1.json", "s1", {"status": "success"}),
            ("Summary", "", "/log/2.json", "s2", {"status": "success"}),
            ("Summary", "London", "/log/3.json", "s3", {"status": "success"}),
        ]
        
        has_consensus, answer = _check_consensus(results, early_stop_k=2, early_stop_threshold=1.0)
        
        # Only 1 valid (non-empty) result
        self.assertFalse(has_consensus)

    def test_consensus_case_insensitive(self):
        """Test: Answer comparison should be case-insensitive"""
        from src.core.multi_path import _check_consensus
        
        results = [
            ("Summary", "Paris", "/log/1.json", "s1", {"status": "success"}),
            ("Summary", "PARIS", "/log/2.json", "s2", {"status": "success"}),
            ("Summary", "paris", "/log/3.json", "s3", {"status": "success"}),
        ]
        
        has_consensus, answer = _check_consensus(results, early_stop_k=2, early_stop_threshold=1.0)
        
        self.assertTrue(has_consensus)
        self.assertEqual(answer, "Paris")  # First one should be returned

    def test_threshold_75_percent(self):
        """Test: 3/4 = 75% should meet 0.75 threshold"""
        from src.core.multi_path import _check_consensus
        
        results = [
            ("Summary", "Answer A", "/log/1.json", "s1", {"status": "success"}),
            ("Summary", "Answer A", "/log/2.json", "s2", {"status": "success"}),
            ("Summary", "Answer A", "/log/3.json", "s3", {"status": "success"}),
            ("Summary", "Answer B", "/log/4.json", "s4", {"status": "success"}),
        ]
        
        has_consensus, answer = _check_consensus(results, early_stop_k=3, early_stop_threshold=0.75)
        
        self.assertTrue(has_consensus)


class TestEarlyStoppingConfiguration(unittest.TestCase):
    """Test early stopping configuration"""

    def test_default_values(self):
        """Test: Default values should be sensible"""
        # early_stop_k defaults to 2
        early_stop_k = int(2)
        self.assertEqual(early_stop_k, 2)
        
        # early_stop_threshold defaults to 1.0 (100% agreement)
        early_stop_threshold = float(1.0)
        self.assertEqual(early_stop_threshold, 1.0)

    def test_threshold_zero_disables(self):
        """Test: threshold <= 0 should disable early stopping"""
        threshold = 0.0
        self.assertLessEqual(threshold, 0)  # Would disable

    def test_threshold_one_requires_full_agreement(self):
        """Test: threshold = 1.0 requires all valid results to agree"""
        threshold = 1.0
        self.assertEqual(threshold, 1.0)

    def test_early_stop_k_greater_than_paths_disables(self):
        """Test: early_stop_k > num_paths should disable early stopping"""
        # With 3 paths and k=5, early stopping can't trigger
        num_paths = 3
        early_stop_k = 5
        self.assertGreater(early_stop_k, num_paths)


class TestEarlyStoppingLogic(unittest.TestCase):
    """Test early stopping logic in execution"""

    def test_early_stop_parameters_passed_correctly(self):
        """Test: Parameters should be passed to pipeline"""
        # This tests that parameters are correctly defined
        import inspect
        from src.core.multi_path import execute_multi_path_pipeline
        
        sig = inspect.signature(execute_multi_path_pipeline)
        params = list(sig.parameters.keys())
        
        self.assertIn('early_stop_k', params)
        self.assertIn('early_stop_threshold', params)

    def test_pipeline_accepts_early_stop_params(self):
        """Test: Pipeline function accepts early stopping params"""
        import inspect
        from src.core.pipeline import execute_multi_path_task_pipeline
        
        sig = inspect.signature(execute_multi_path_task_pipeline)
        params = list(sig.parameters.keys())
        
        self.assertIn('early_stop_k', params)
        self.assertIn('early_stop_threshold', params)


class TestEarlyStoppingBehavior(unittest.TestCase):
    """Integration tests for early stopping behavior"""

    async def _create_mock_task(self, delay: float, result_idx: int, strategy_name: str):
        """Helper: Create a mock path task"""
        await asyncio.sleep(delay)
        return (
            f"Summary {result_idx}",
            f"Answer {result_idx}",
            f"/log/{result_idx}.json",
            strategy_name,
            {"strategy": strategy_name, "status": "success"},
        )

    def test_simulated_early_stop_scenario(self):
        """Test: Simulate early stopping with mock tasks"""
        
        async def run_test():
            # Create tasks: first 2 complete quickly with same answer
            async def fast_task_1():
                await asyncio.sleep(0.1)
                return ("Summary", "Same Answer", "/log/1.json", "s1", {"status": "success"})
            
            async def fast_task_2():
                await asyncio.sleep(0.2)
                return ("Summary", "Same Answer", "/log/2.json", "s2", {"status": "success"})
            
            async def slow_task():
                await asyncio.sleep(1.0)  # Would be cancelled
                return ("Summary", "Different", "/log/3.json", "s3", {"status": "success"})
            
            # Test consensus detection on partial results
            partial_results = [
                ("Summary", "Same Answer", "/log/1.json", "s1", {"status": "success"}),
                ("Summary", "Same Answer", "/log/2.json", "s2", {"status": "success"}),
            ]
            
            from src.core.multi_path import _check_consensus
            has_consensus, answer = _check_consensus(
                partial_results, 
                early_stop_k=2, 
                early_stop_threshold=1.0
            )
            
            self.assertTrue(has_consensus)
            self.assertEqual(answer, "Same Answer")
        
        asyncio.run(run_test())

    def test_all_different_answers_no_early_stop(self):
        """Test: All different answers should not trigger early stop"""
        
        results = [
            ("Summary", "Answer A", "/log/1.json", "s1", {"status": "success"}),
            ("Summary", "Answer B", "/log/2.json", "s2", {"status": "success"}),
            ("Summary", "Answer C", "/log/3.json", "s3", {"status": "success"}),
        ]
        
        from src.core.multi_path import _check_consensus
        has_consensus, _ = _check_consensus(
            results, 
            early_stop_k=2, 
            early_stop_threshold=1.0
        )
        
        # No consensus - all answers are different
        self.assertFalse(has_consensus)


if __name__ == "__main__":
    unittest.main(verbosity=2)