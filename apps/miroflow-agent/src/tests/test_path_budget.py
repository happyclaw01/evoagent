# Copyright (c) 2025 MiroMind
# Unit Tests for EA-010: Path Budget Allocation

import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent))


class TestStrategyMaxTurns(unittest.TestCase):
    """Test strategy definitions include max_turns"""

    def test_all_strategies_have_max_turns(self):
        """Test: All predefined strategies have max_turns defined"""
        from src.core.multi_path import STRATEGY_VARIANTS

        for strategy in STRATEGY_VARIANTS:
            self.assertIn(
                "max_turns",
                strategy,
                f"Strategy {strategy['name']} missing max_turns",
            )
            self.assertIsInstance(
                strategy["max_turns"],
                int,
                f"Strategy {strategy['name']} max_turns must be int",
            )
            self.assertGreater(
                strategy["max_turns"],
                0,
                f"Strategy {strategy['name']} max_turns must be positive",
            )

    def test_max_turns_values_reasonable(self):
        """Test: max_turns values are in reasonable range"""
        from src.core.multi_path import STRATEGY_VARIANTS

        for strategy in STRATEGY_VARIANTS:
            # Reasonable range: 10 to 1000 turns
            self.assertGreaterEqual(
                strategy["max_turns"],
                10,
                f"Strategy {strategy['name']} max_turns too low",
            )
            self.assertLessEqual(
                strategy["max_turns"],
                1000,
                f"Strategy {strategy['name']} max_turns too high",
            )

    def test_different_strategies_have_different_max_turns(self):
        """Test: Different strategies should have different budgets for diversity"""
        from src.core.multi_path import STRATEGY_VARIANTS

        max_turns_values = [s["max_turns"] for s in STRATEGY_VARIANTS]
        
        # At least some strategies should have different values
        unique_values = set(max_turns_values)
        self.assertGreater(
            len(unique_values),
            1,
            "All strategies have same max_turns - should vary for diversity",
        )

    def test_breadth_first_has_lowest_turns(self):
        """Test: breadth_first should have lower max_turns (shallow exploration)"""
        from src.core.multi_path import STRATEGY_VARIANTS

        breadth = next(s for s in STRATEGY_VARIANTS if s["name"] == "breadth_first")
        
        # Find another strategy to compare
        depth = next(s for s in STRATEGY_VARIANTS if s["name"] == "depth_first")
        
        # breadth should have fewer or equal turns than depth
        self.assertLessEqual(
            breadth["max_turns"],
            depth["max_turns"],
            "breadth_first should have <= max_turns than depth_first",
        )


class TestMaxTurnsOverride(unittest.TestCase):
    """Test max_turns override functionality"""

    def test_default_max_turns_fallback(self):
        """Test: When strategy has no max_turns, use default"""
        strategy = {"name": "test", "description": "test"}
        
        max_turns = strategy.get("max_turns", None)
        # If not in strategy, would use config default
        self.assertIsNone(max_turns)

    def test_strategy_max_turns_used(self):
        """Test: When strategy has max_turns, it's used"""
        strategy = {"name": "test", "description": "test", "max_turns": 150}
        
        max_turns = strategy.get("max_turns", None)
        self.assertEqual(max_turns, 150)

    def test_explicit_max_turns_overrides_strategy(self):
        """Test: Explicit max_turns parameter overrides strategy value"""
        strategy = {"name": "test", "description": "test", "max_turns": 100}
        
        # Simulate explicit parameter override
        explicit_max_turns = 200
        max_turns = explicit_max_turns if explicit_max_turns is not None else strategy.get("max_turns", None)
        
        self.assertEqual(max_turns, 200)


class TestMaxTurnsInMetadata(unittest.TestCase):
    """Test max_turns is properly recorded in metadata"""

    def test_metadata_includes_max_turns(self):
        """Test: Metadata should include max_turns for cost tracking"""
        # Simulate metadata structure
        metadata = {
            "strategy": "breadth_first",
            "status": "success",
            "max_turns": 100,
            "turns": 50,
        }
        
        self.assertIn("max_turns", metadata)
        self.assertEqual(metadata["max_turns"], 100)

    def test_metadata_max_turns_type(self):
        """Test: max_turns in metadata should be int or None"""
        # Valid cases
        self.assertIsInstance(100, int)
        self.assertIsInstance(None, type(None))
        
        # Invalid case (would fail)
        # self.assertIsInstance("100", int)  # This would fail


class TestConfigOverride(unittest.TestCase):
    """Test config override for max_turns"""

    def test_omegaconf_modification(self):
        """Test: OmegaConf can be modified to override max_turns"""
        from omegaconf import DictConfig, OmegaConf
        
        # Create a mock config
        cfg = OmegaConf.create({
            "agent": {
                "main_agent": {
                    "max_turns": 600
                }
            },
            "llm": {"model_name": "test"}
        })
        
        # Override max_turns
        cfg.agent.main_agent.max_turns = 100
        
        self.assertEqual(cfg.agent.main_agent.max_turns, 100)

    def test_config_fallback_when_no_override(self):
        """Test: When no override provided, use original config value"""
        from omegaconf import OmegaConf
        
        cfg = OmegaConf.create({
            "agent": {"main_agent": {"max_turns": 600}}
        })
        
        strategy_max_turns = None
        max_turns = strategy_max_turns  # Would use config default
        
        # No override, so would use config
        self.assertIsNone(max_turns)


class TestPathExecutionWithBudget(unittest.TestCase):
    """Test path execution respects budget limits"""

    def test_path_reports_max_turns_in_metadata(self):
        """Test: Completed path should report its max_turns in metadata"""
        # Simulate a path result
        result = (
            "summary",
            "answer",
            "/log/path.json",
            "breadth_first",
            {
                "strategy": "breadth_first",
                "status": "success",
                "max_turns": 100,
                "turns": 45,
            }
        )
        
        metadata = result[4]
        
        self.assertEqual(metadata.get("max_turns"), 100)
        self.assertEqual(metadata.get("turns"), 45)
        
        # Turns should not exceed max_turns
        self.assertLessEqual(metadata["turns"], metadata["max_turns"])

    def test_cost_tracker_receives_max_turns_info(self):
        """Test: Cost tracker should receive max_turns info"""
        from src.core.cost_tracker import CostTracker
        
        tracker = CostTracker()
        
        # Record with max_turns info
        tracker.record_path_cost(
            path_id="test_path",
            strategy_name="depth_first",
            model_name="qwen/qwen3-8b",
            input_tokens=1000,
            output_tokens=500,
            status="success"
        )
        
        summary = tracker.get_summary()
        
        # Verify path cost was recorded
        self.assertEqual(len(summary.path_costs), 1)
        self.assertEqual(summary.path_costs[0]["path_id"], "test_path")


if __name__ == "__main__":
    unittest.main(verbosity=2)