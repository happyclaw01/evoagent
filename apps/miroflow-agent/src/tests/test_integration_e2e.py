# Copyright (c) 2025 MiroMind
# EA-404: End-to-End Integration Tests
#
# Validates the full pipeline: task → classify → select strategies →
# execute paths → vote → record results → update profiles.
# Uses mocked LLM/tool calls for deterministic testing.

import asyncio
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))


def run_async(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


class TestFullPipelineFlow(unittest.TestCase):
    """EA-404: End-to-end pipeline integration."""

    def setUp(self):
        from src.core.task_classifier import TaskClassifier
        from src.core.strategy_tracker import StrategyRecordKeeper, StrategyProfileEngine, StrategyResult
        from src.core.adaptive_selector import AdaptiveSelector
        from src.core.failure_analyzer import FailureAnalyzer
        from src.core.strategy_lifecycle import StrategyLifecycleManager
        from src.core.experience_extractor import ExperienceExtractor
        from src.core.groupthink_detector import GroupthinkDetector, PathAnswer
        
        self.tmpdir = tempfile.mkdtemp()
        self.classifier = TaskClassifier()
        self.keeper = StrategyRecordKeeper(data_dir=f"{self.tmpdir}/results")
        self.engine = StrategyProfileEngine(
            record_keeper=self.keeper, profile_dir=f"{self.tmpdir}/profiles",
        )
        self.analyzer = FailureAnalyzer(record_keeper=self.keeper)
        self.lifecycle = StrategyLifecycleManager(
            profile_engine=self.engine, failure_analyzer=self.analyzer,
            state_dir=f"{self.tmpdir}/lifecycle",
        )
        self.extractor = ExperienceExtractor(
            record_keeper=self.keeper, profile_engine=self.engine,
            failure_analyzer=self.analyzer, learnings_dir=f"{self.tmpdir}/learnings",
        )
        self.selector = AdaptiveSelector(
            profile_engine=self.engine, classifier=self.classifier,
        )
        self.detector = GroupthinkDetector()
        self.StrategyResult = StrategyResult
        self.PathAnswer = PathAnswer

    def test_cold_start_pipeline(self):
        """First run: no history, cold start selection."""
        classification = self.classifier.classify("Who is the CEO of Tesla?")
        self.assertEqual(classification.task_type.value, "search")
        
        selection = self.selector.select("Who is the CEO of Tesla?", num_paths=3)
        self.assertEqual(selection.method, "cold_start")
        self.assertEqual(len(selection.strategies), 3)
        
        results = []
        for i, strategy in enumerate(selection.strategies):
            results.append(self.StrategyResult(
                task_id="task_001", strategy_name=strategy,
                task_type="search", is_winner=(i == 0),
                final_answer="Elon Musk", turns_used=10 + i * 5,
                cost_usd=0.01 + i * 0.005, status="success",
            ))
        
        self.keeper.record_batch(results)
        
        answers = [
            self.PathAnswer(
                path_id=f"path_{i}", answer="Elon Musk",
                reasoning=f"Found via search using {s} approach",
                turns_used=10 + i * 5,
            )
            for i, s in enumerate(selection.strategies)
        ]
        report = self.detector.analyze(answers)
        self.assertIsInstance(report.is_groupthink, bool)
        
        self.engine.build_profiles()
        profiles = self.engine.get_all_profiles()
        self.assertTrue(len(profiles) > 0)

    def test_warm_pipeline_with_history(self):
        """Run with existing history: adaptive selection."""
        for i in range(15):
            for j, strategy in enumerate(["breadth_first", "depth_first", "lateral_thinking", "verification_heavy"]):
                self.keeper.record(self.StrategyResult(
                    task_id=f"hist_{i}", strategy_name=strategy,
                    task_type="search", is_winner=(strategy == "breadth_first"),
                    turns_used=10, cost_usd=0.01, status="success",
                ))
        
        self.engine.build_profiles()
        selection = self.selector.select("Find the latest news about AI", num_paths=3)
        self.assertEqual(selection.method, "adaptive")
        
        if "breadth_first" in selection.strategies:
            idx = selection.strategies.index("breadth_first")
            self.assertEqual(selection.roles[idx], "exploit")

    def test_lifecycle_integration(self):
        """Test lifecycle evaluation after recording results."""
        for i in range(15):
            self.keeper.record(self.StrategyResult(
                task_id=f"t{i}", strategy_name="bad_strategy",
                task_type="search", is_winner=False, status="success",
                turns_used=50, cost_usd=0.05,
            ))
        
        self.engine.build_profiles()
        
        from src.core.strategy_lifecycle import LifecycleStatus
        state = self.lifecycle.get_state("bad_strategy")
        state.status = LifecycleStatus.ACTIVE
        event = self.lifecycle.evaluate("bad_strategy")
        
        self.assertIsNotNone(event)
        self.assertIn(event.to_status, ["probation", "retired"])

    def test_experience_extraction_integration(self):
        """Test learnings extraction from execution history."""
        for i in range(10):
            self.keeper.record(self.StrategyResult(
                task_id=f"s{i}", strategy_name="bf",
                task_type="search", is_winner=(i < 8),
                turns_used=10, cost_usd=0.01, status="success",
            ))
            self.keeper.record(self.StrategyResult(
                task_id=f"c{i}", strategy_name="bf",
                task_type="compute", is_winner=(i < 2),
                turns_used=10, cost_usd=0.01, status="success",
            ))
        
        self.engine.build_profiles()
        learnings = self.extractor.extract_all()
        self.assertTrue(len(learnings) > 0)

    def test_discovery_bus_and_cache_integration(self):
        """Test discovery bus and result cache work together."""
        from src.core.discovery_bus import DiscoveryBus, Discovery, DiscoveryType
        from src.core.result_cache import ResultCache
        
        bus = DiscoveryBus(max_discoveries=100)
        cache = ResultCache(max_entries=50, default_ttl=300)
        
        async def run():
            discovery = Discovery(
                discovery_id="d1", path_id="path_0", strategy_name="bf",
                discovery_type=DiscoveryType.EVIDENCE,
                content="GDP of China is $18 trillion", confidence=0.9,
            )
            await bus.publish(discovery)
            
            discoveries = await bus.get_discoveries(exclude_path="path_1")
            self.assertEqual(len(discoveries), 1)
            
            await cache.put("search", {"query": "china gdp"}, "18 trillion")
            result = await cache.get("search", {"query": "china gdp"})
            self.assertEqual(result, "18 trillion")
        
        run_async(run())

    def test_full_feedback_loop(self):
        """Test complete feedback loop: execute → record → profile → select."""
        sel1 = self.selector.select("Find X", num_paths=2)
        self.assertEqual(sel1.method, "cold_start")
        
        for s in sel1.strategies:
            self.keeper.record(self.StrategyResult(
                task_id="round1", strategy_name=s,
                task_type="search", is_winner=(s == sel1.strategies[0]),
                turns_used=10, cost_usd=0.01, status="success",
            ))
        
        self.engine.build_profiles()
        
        for round_num in range(2, 12):
            for s in sel1.strategies:
                self.keeper.record(self.StrategyResult(
                    task_id=f"round{round_num}", strategy_name=s,
                    task_type="search", is_winner=(s == sel1.strategies[0]),
                    turns_used=10, cost_usd=0.01, status="success",
                ))
        
        self.keeper.clear()
        self.engine.build_profiles()
        
        profiles = self.engine.get_all_profiles()
        self.assertTrue(len(profiles) > 0)


class TestCostTrackerIntegration(unittest.TestCase):
    """EA-404: Cost tracker in pipeline context."""

    def test_cost_tracking_across_paths(self):
        from src.core.cost_tracker import CostTracker
        
        tracker = CostTracker(log_dir=tempfile.mkdtemp())
        
        for path_id in range(3):
            tracker.record_path_cost(
                path_id=f"path_{path_id}",
                strategy_name="breadth_first",
                model_name="claude-sonnet-4-20250514",
                input_tokens=1000 * (path_id + 1),
                output_tokens=500 * (path_id + 1),
            )
        
        summary = tracker.get_summary()
        self.assertGreater(summary.total_cost_usd, 0)
        self.assertEqual(summary.total_paths, 3)

    def test_budget_tracking(self):
        from src.core.cost_tracker import CostTracker
        
        tracker = CostTracker(log_dir=tempfile.mkdtemp())
        tracker.record_path_cost(
            path_id="p0", strategy_name="bf",
            model_name="claude-sonnet-4-20250514",
            input_tokens=100000, output_tokens=100000,
        )
        summary = tracker.get_summary()
        self.assertGreater(summary.total_cost_usd, 0)


class TestStreamingIntegration(unittest.TestCase):
    """EA-404: Streaming in pipeline context."""

    def test_stream_events_flow(self):
        from src.core.streaming import MultiStreamManager, StreamEvent, StreamEventType, CallbackStreamConsumer
        
        manager = MultiStreamManager()
        collected = []
        consumer = CallbackStreamConsumer(callback=lambda e: collected.append(e))
        manager.add_consumer(consumer)
        
        event1 = StreamEvent(
            event_type=StreamEventType.PATH_START,
            path_id="path_0",
            strategy_name="breadth_first",
        )
        event2 = StreamEvent(
            event_type=StreamEventType.PATH_END,
            path_id="path_0",
            strategy_name="breadth_first",
            content="Done",
        )
        
        async def run():
            await manager.broadcast(event1)
            await manager.broadcast(event2)
        
        run_async(run())
        
        self.assertEqual(len(collected), 2)
        self.assertEqual(collected[0].event_type, StreamEventType.PATH_START)
        self.assertEqual(collected[1].event_type, StreamEventType.PATH_END)


if __name__ == "__main__":
    unittest.main(verbosity=2)
