# Copyright (c) 2025 MiroMind
# Unit Tests for EA-304: Cost Tracker

import sys
import tempfile
import unittest
from pathlib import Path
from typing import Dict

sys.path.insert(0, str(Path(__file__).parent.parent))


class TestCostCalculation(unittest.TestCase):
    """Test cost calculation logic"""

    def test_calculate_cost_for_qwen(self):
        """Test cost calculation for Qwen3-8B model"""
        from src.core.cost_tracker import CostTracker
        
        tracker = CostTracker()
        
        # Qwen3-8B: $0.07/1M input, $0.14/1M output
        # 1000 input + 1000 output = 1K each
        cost = tracker._calculate_cost("qwen/qwen3-8b", 1000, 1000)
        
        expected = (1000 / 1_000_000 * 0.07) + (1000 / 1_000_000 * 0.14)
        self.assertAlmostEqual(cost, expected, places=6)
    
    def test_calculate_cost_for_claude(self):
        """Test cost calculation for Claude"""
        from src.core.cost_tracker import CostTracker
        
        tracker = CostTracker()
        
        # Claude Opus: $15/1M input, $75/1M output
        cost = tracker._calculate_cost("anthropic/claude-opus-4-6", 1000, 1000)
        
        expected = (1000 / 1_000_000 * 15) + (1000 / 1_000_000 * 75)
        self.assertAlmostEqual(cost, expected, places=6)
    
    def test_calculate_cost_unknown_model(self):
        """Test cost calculation for unknown model uses default pricing"""
        from src.core.cost_tracker import CostTracker
        
        tracker = CostTracker()
        
        cost = tracker._calculate_cost("unknown/model-xyz", 1000, 1000)
        
        # Default: $1.00 input, $3.00 output
        expected = (1000 / 1_000_000 * 1.0) + (1000 / 1_000_000 * 3.0)
        self.assertAlmostEqual(cost, expected, places=6)
    
    def test_calculate_cost_partial_match(self):
        """Test cost calculation with partial model name match"""
        from src.core.cost_tracker import CostTracker
        
        tracker = CostTracker()
        
        # Should match "qwen3-8b" from "qwen/qwen3-8b"
        cost = tracker._calculate_cost("qwen3-8b", 1000, 1000)
        
        expected = (1000 / 1_000_000 * 0.07) + (1000 / 1_000_000 * 0.14)
        self.assertAlmostEqual(cost, expected, places=6)


class TestPathCost(unittest.TestCase):
    """Test PathCost dataclass"""

    def test_total_tokens(self):
        """Test total_tokens property"""
        from src.core.cost_tracker import PathCost
        
        pc = PathCost(
            path_id="test",
            strategy_name="test",
            model_name="test",
            input_tokens=5000,
            output_tokens=3000,
        )
        
        self.assertEqual(pc.total_tokens, 8000)
    
    def test_to_dict(self):
        """Test to_dict conversion"""
        from src.core.cost_tracker import PathCost
        
        pc = PathCost(
            path_id="test_1",
            strategy_name="breadth_first",
            model_name="qwen/qwen3-8b",
            input_tokens=1000,
            output_tokens=500,
            cost_usd=0.000105,
        )
        
        d = pc.to_dict()
        
        self.assertEqual(d["path_id"], "test_1")
        # Note: total_tokens is a property, not stored in dict
        self.assertEqual(d["input_tokens"], 1000)
        self.assertEqual(d["output_tokens"], 500)


class TestCostTrackerRecord(unittest.TestCase):
    """Test CostTracker recording functionality"""

    def test_record_path_cost(self):
        """Test recording cost for a path"""
        from src.core.cost_tracker import CostTracker
        
        tracker = CostTracker()
        
        result = tracker.record_path_cost(
            path_id="path_0",
            strategy_name="breadth_first",
            model_name="qwen/qwen3-8b",
            input_tokens=5000,
            output_tokens=2000,
            num_turns=5,
            num_tool_calls=10,
            duration_seconds=30.0,
            status="success",
        )
        
        self.assertEqual(result.path_id, "path_0")
        self.assertEqual(result.cost_usd, 
            (5000/1_000_000*0.07) + (2000/1_000_000*0.14))
        self.assertEqual(result.status, "success")


class TestCostSummary(unittest.TestCase):
    """Test CostSummary generation"""

    def test_empty_tracker(self):
        """Test summary from empty tracker"""
        from src.core.cost_tracker import CostTracker
        
        tracker = CostTracker()
        summary = tracker.get_summary()
        
        self.assertEqual(summary.total_paths, 0)
        self.assertEqual(summary.total_cost_usd, 0.0)
        self.assertIn("No path data", summary.recommendations[0])

    def test_summary_with_data(self):
        """Test summary with multiple paths"""
        from src.core.cost_tracker import CostTracker
        
        tracker = CostTracker()
        
        # Record 3 paths
        tracker.record_path_cost("p1", "s1", "qwen/qwen3-8b", 1000, 500, status="success")
        tracker.record_path_cost("p2", "s2", "qwen/qwen3-8b", 1500, 800, status="success")
        tracker.record_path_cost("p3", "s3", "qwen/qwen3-8b", 500, 200, status="failed")
        
        summary = tracker.get_summary()
        
        self.assertEqual(summary.total_paths, 3)
        self.assertEqual(summary.successful_paths, 2)
        self.assertEqual(summary.failed_paths, 1)
        self.assertEqual(summary.total_input_tokens, 3000)
        self.assertEqual(summary.total_output_tokens, 1500)
        self.assertEqual(summary.total_tokens, 4500)
        
        # Check averages
        self.assertAlmostEqual(
            summary.avg_cost_per_path, 
            summary.total_cost_usd / 3
        )
        self.assertAlmostEqual(
            summary.avg_cost_per_successful_path,
            summary.total_cost_usd / 2
        )


class TestRecommendations(unittest.TestCase):
    """Test recommendation generation"""

    def test_low_success_rate(self):
        """Test recommendation for low success rate"""
        from src.core.cost_tracker import CostTracker
        
        tracker = CostTracker()
        
        # 1 success out of 5 = 20%
        for i in range(4):
            tracker.record_path_cost(f"p{i}", "s", "qwen/qwen3-8b", 100, 50, status="failed")
        tracker.record_path_cost("p4", "s", "qwen/qwen3-8b", 100, 50, status="success")
        
        summary = tracker.get_summary()
        
        self.assertTrue(any("success rate" in r.lower() for r in summary.recommendations))

    def test_high_cost(self):
        """Test recommendation for high total cost"""
        from src.core.cost_tracker import CostTracker
        
        tracker = CostTracker()
        
        # High cost paths (using expensive model)
        for i in range(3):
            tracker.record_path_cost(
                f"p{i}", "s", "anthropic/claude-opus-4-6", 
                100000, 50000, status="success"
            )
        
        summary = tracker.get_summary()
        
        # Should trigger high cost warning (>$1)
        self.assertTrue(any("$" in r and "high" in r.lower() for r in summary.recommendations))

    def test_early_stopping_recommendation(self):
        """Test recommendation for early stopping"""
        from src.core.cost_tracker import CostTracker
        
        tracker = CostTracker()
        
        # 1 success out of 3 - suggests early stopping could help
        tracker.record_path_cost("p0", "s", "qwen/qwen3-8b", 100, 50, status="success")
        tracker.record_path_cost("p1", "s", "qwen/qwen3-8b", 100, 50, status="failed")
        tracker.record_path_cost("p2", "s", "qwen/qwen3-8b", 100, 50, status="failed")
        
        summary = tracker.get_summary()
        
        self.assertTrue(any("early stopping" in r.lower() for r in summary.recommendations))


class TestCostReportFormatting(unittest.TestCase):
    """Test cost report formatting"""

    def test_format_cost_report(self):
        """Test human-readable cost report"""
        from src.core.cost_tracker import CostTracker, format_cost_report
        
        tracker = CostTracker()
        tracker.record_path_cost("p1", "breadth", "qwen/qwen3-8b", 1000, 500, status="success")
        
        summary = tracker.get_summary()
        report = format_cost_report(summary)
        
        self.assertIn("EvoAgent Cost Report", report)
        self.assertIn("Total Paths:", report)
        self.assertIn("Total Cost:", report)
        self.assertIn("Recommendations:", report)


class TestSaveLoad(unittest.TestCase):
    """Test saving and loading cost data"""

    def test_save_to_file(self):
        """Test saving cost data to JSON file"""
        from src.core.cost_tracker import CostTracker
        
        with tempfile.TemporaryDirectory() as tmpdir:
            tracker = CostTracker(log_dir=tmpdir)
            tracker.record_path_cost("p1", "s", "qwen/qwen3-8b", 1000, 500, status="success")
            
            filepath = tracker.save_to_file()
            
            self.assertTrue(Path(filepath).exists())
            
            # Verify content
            import json
            with open(filepath) as f:
                data = json.load(f)
            
            self.assertEqual(data["total_paths"], 1)
            # 1000 input + 500 output = 1500 total
            # Cost: 0.00007 + 0.00007 = 0.00014
            self.assertAlmostEqual(data["total_cost_usd"], 0.00014, places=5)


if __name__ == "__main__":
    unittest.main(verbosity=2)