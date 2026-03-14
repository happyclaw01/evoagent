# Copyright (c) 2025 MiroMind
# Unit Tests for EA-305: Inter-Path Communication Bus (Discovery Bus)

import asyncio
import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))


def run_async(coro):
    """Helper to run async tests."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


class TestDiscoveryTypes(unittest.TestCase):
    """Test DiscoveryType enum."""

    def test_all_types_exist(self):
        from src.core.discovery_bus import DiscoveryType
        expected = ["evidence", "source", "tool_result", "dead_end",
                     "contradiction", "partial_answer", "insight"]
        for t in expected:
            self.assertIn(t, [dt.value for dt in DiscoveryType])

    def test_type_is_string(self):
        from src.core.discovery_bus import DiscoveryType
        self.assertEqual(DiscoveryType.EVIDENCE, "evidence")
        self.assertEqual(DiscoveryType.DEAD_END, "dead_end")


class TestDiscovery(unittest.TestCase):
    """Test Discovery dataclass."""

    def test_create_discovery(self):
        from src.core.discovery_bus import Discovery, DiscoveryType
        d = Discovery(
            discovery_id="d1",
            path_id="path_0",
            strategy_name="breadth_first",
            discovery_type=DiscoveryType.EVIDENCE,
            content="GDP growth rate is 3.2%",
            confidence=0.85,
            tags=["GDP", "macro"],
        )
        self.assertEqual(d.discovery_id, "d1")
        self.assertEqual(d.confidence, 0.85)
        self.assertEqual(d.tags, ["GDP", "macro"])

    def test_to_dict(self):
        from src.core.discovery_bus import Discovery, DiscoveryType
        d = Discovery(
            discovery_id="d1",
            path_id="path_0",
            strategy_name="breadth_first",
            discovery_type=DiscoveryType.SOURCE,
            content="Found source",
            data={"url": "https://example.com"},
        )
        result = d.to_dict()
        self.assertEqual(result["discovery_type"], "source")
        self.assertEqual(result["data"]["url"], "https://example.com")
        self.assertIn("timestamp", result)

    def test_to_prompt_snippet(self):
        from src.core.discovery_bus import Discovery, DiscoveryType
        d = Discovery(
            discovery_id="d1",
            path_id="path_0",
            strategy_name="depth_first",
            discovery_type=DiscoveryType.EVIDENCE,
            content="The answer is 42",
            confidence=0.9,
        )
        snippet = d.to_prompt_snippet()
        self.assertIn("depth_first", snippet)
        self.assertIn("Evidence", snippet)
        self.assertIn("90%", snippet)
        self.assertIn("The answer is 42", snippet)


class TestDiscoveryBusPublish(unittest.TestCase):
    """Test DiscoveryBus publish functionality."""

    def test_publish_single(self):
        from src.core.discovery_bus import DiscoveryBus, Discovery, DiscoveryType
        bus = DiscoveryBus()
        d = Discovery(
            discovery_id="d1",
            path_id="path_0",
            strategy_name="breadth_first",
            discovery_type=DiscoveryType.EVIDENCE,
            content="test discovery",
        )
        run_async(bus.publish(d))
        stats = run_async(bus.get_stats())
        self.assertEqual(stats["total_published"], 1)
        self.assertEqual(stats["current_discoveries"], 1)

    def test_publish_multiple(self):
        from src.core.discovery_bus import DiscoveryBus, Discovery, DiscoveryType
        bus = DiscoveryBus()
        for i in range(5):
            d = Discovery(
                discovery_id=f"d{i}",
                path_id=f"path_{i % 3}",
                strategy_name="breadth_first",
                discovery_type=DiscoveryType.EVIDENCE,
                content=f"discovery {i}",
            )
            run_async(bus.publish(d))
        stats = run_async(bus.get_stats())
        self.assertEqual(stats["total_published"], 5)
        self.assertEqual(stats["current_discoveries"], 5)

    def test_fifo_eviction(self):
        from src.core.discovery_bus import DiscoveryBus, Discovery, DiscoveryType
        bus = DiscoveryBus(max_discoveries=3)
        for i in range(5):
            d = Discovery(
                discovery_id=f"d{i}",
                path_id="path_0",
                strategy_name="breadth_first",
                discovery_type=DiscoveryType.EVIDENCE,
                content=f"discovery {i}",
            )
            run_async(bus.publish(d))
        stats = run_async(bus.get_stats())
        self.assertEqual(stats["current_discoveries"], 3)
        self.assertEqual(stats["evictions"], 2)
        # Should keep the last 3
        results = run_async(bus.get_discoveries())
        self.assertEqual(len(results), 3)
        self.assertEqual(results[0].discovery_id, "d4")  # Most recent first


class TestDiscoveryBusQuery(unittest.TestCase):
    """Test DiscoveryBus query/filter functionality."""

    def _create_bus_with_data(self):
        from src.core.discovery_bus import DiscoveryBus, Discovery, DiscoveryType
        bus = DiscoveryBus()
        discoveries = [
            Discovery("d1", "path_0", "breadth_first", DiscoveryType.EVIDENCE,
                       "evidence 1", confidence=0.9, tags=["finance"]),
            Discovery("d2", "path_1", "depth_first", DiscoveryType.SOURCE,
                       "source 1", confidence=0.7, tags=["tech"]),
            Discovery("d3", "path_0", "breadth_first", DiscoveryType.DEAD_END,
                       "dead end 1", confidence=0.6, tags=["finance"]),
            Discovery("d4", "path_2", "lateral_thinking", DiscoveryType.EVIDENCE,
                       "evidence 2", confidence=0.3, tags=["finance", "GDP"]),
            Discovery("d5", "path_1", "depth_first", DiscoveryType.CONTRADICTION,
                       "contradiction 1", confidence=0.8, tags=["tech"]),
        ]
        for d in discoveries:
            run_async(bus.publish(d))
        return bus

    def test_get_all_discoveries(self):
        bus = self._create_bus_with_data()
        results = run_async(bus.get_discoveries())
        self.assertEqual(len(results), 5)
        # Most recent first
        self.assertEqual(results[0].discovery_id, "d5")

    def test_exclude_path(self):
        bus = self._create_bus_with_data()
        results = run_async(bus.get_discoveries(exclude_path="path_0"))
        self.assertEqual(len(results), 3)
        for d in results:
            self.assertNotEqual(d.path_id, "path_0")

    def test_filter_by_type(self):
        from src.core.discovery_bus import DiscoveryType
        bus = self._create_bus_with_data()
        results = run_async(bus.get_discoveries(discovery_type=DiscoveryType.EVIDENCE))
        self.assertEqual(len(results), 2)
        for d in results:
            self.assertEqual(d.discovery_type, DiscoveryType.EVIDENCE)

    def test_filter_by_confidence(self):
        bus = self._create_bus_with_data()
        results = run_async(bus.get_discoveries(min_confidence=0.7))
        self.assertEqual(len(results), 3)
        for d in results:
            self.assertGreaterEqual(d.confidence, 0.7)

    def test_filter_by_tags(self):
        bus = self._create_bus_with_data()
        results = run_async(bus.get_discoveries(tags=["GDP"]))
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].discovery_id, "d4")

    def test_filter_combined(self):
        from src.core.discovery_bus import DiscoveryType
        bus = self._create_bus_with_data()
        results = run_async(bus.get_discoveries(
            exclude_path="path_0",
            discovery_type=DiscoveryType.EVIDENCE,
            min_confidence=0.2,
        ))
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].discovery_id, "d4")

    def test_limit(self):
        bus = self._create_bus_with_data()
        results = run_async(bus.get_discoveries(limit=2))
        self.assertEqual(len(results), 2)

    def test_get_dead_ends(self):
        bus = self._create_bus_with_data()
        results = run_async(bus.get_dead_ends())
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].content, "dead end 1")

    def test_get_contradictions(self):
        bus = self._create_bus_with_data()
        results = run_async(bus.get_contradictions())
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].content, "contradiction 1")


class TestDiscoveryBusNewDiscoveries(unittest.TestCase):
    """Test incremental polling via get_new_discoveries."""

    def test_new_discoveries_first_call(self):
        from src.core.discovery_bus import DiscoveryBus, Discovery, DiscoveryType
        bus = DiscoveryBus()
        d = Discovery("d1", "path_0", "bf", DiscoveryType.EVIDENCE, "test")
        run_async(bus.publish(d))
        # path_1 has never read, should get all except own
        results = run_async(bus.get_new_discoveries("path_1"))
        self.assertEqual(len(results), 1)

    def test_new_discoveries_no_own(self):
        from src.core.discovery_bus import DiscoveryBus, Discovery, DiscoveryType
        bus = DiscoveryBus()
        d = Discovery("d1", "path_0", "bf", DiscoveryType.EVIDENCE, "test")
        run_async(bus.publish(d))
        # path_0 should not see its own discovery
        results = run_async(bus.get_new_discoveries("path_0"))
        self.assertEqual(len(results), 0)

    def test_new_discoveries_incremental(self):
        from src.core.discovery_bus import DiscoveryBus, Discovery, DiscoveryType
        bus = DiscoveryBus()
        
        d1 = Discovery("d1", "path_0", "bf", DiscoveryType.EVIDENCE, "first")
        run_async(bus.publish(d1))
        
        # First read by path_1
        results1 = run_async(bus.get_new_discoveries("path_1"))
        self.assertEqual(len(results1), 1)
        
        time.sleep(0.01)  # Ensure timestamp difference
        
        # Publish another discovery
        d2 = Discovery("d2", "path_0", "bf", DiscoveryType.SOURCE, "second",
                        timestamp=time.time())
        run_async(bus.publish(d2))
        
        # Second read should only get the new one
        results2 = run_async(bus.get_new_discoveries("path_1"))
        self.assertEqual(len(results2), 1)
        self.assertEqual(results2[0].discovery_id, "d2")


class TestDiscoveryBusContext(unittest.TestCase):
    """Test context formatting for prompt injection."""

    def test_empty_context(self):
        from src.core.discovery_bus import DiscoveryBus
        bus = DiscoveryBus()
        ctx = run_async(bus.format_context_for_path("path_0"))
        self.assertEqual(ctx, "")

    def test_context_with_discoveries(self):
        from src.core.discovery_bus import DiscoveryBus, Discovery, DiscoveryType
        bus = DiscoveryBus()
        d = Discovery("d1", "path_0", "breadth_first", DiscoveryType.EVIDENCE,
                       "GDP is 3.2%", confidence=0.9)
        run_async(bus.publish(d))
        
        ctx = run_async(bus.format_context_for_path("path_1"))
        self.assertIn("Cross-Path Intelligence", ctx)
        self.assertIn("GDP is 3.2%", ctx)
        self.assertIn("breadth_first", ctx)

    def test_context_excludes_own(self):
        from src.core.discovery_bus import DiscoveryBus, Discovery, DiscoveryType
        bus = DiscoveryBus()
        d = Discovery("d1", "path_0", "bf", DiscoveryType.EVIDENCE, "test")
        run_async(bus.publish(d))
        
        ctx = run_async(bus.format_context_for_path("path_0"))
        self.assertEqual(ctx, "")


class TestDiscoveryBusClear(unittest.TestCase):
    """Test bus clear/reset functionality."""

    def test_clear(self):
        from src.core.discovery_bus import DiscoveryBus, Discovery, DiscoveryType
        bus = DiscoveryBus()
        d = Discovery("d1", "path_0", "bf", DiscoveryType.EVIDENCE, "test")
        run_async(bus.publish(d))
        run_async(bus.clear())
        stats = run_async(bus.get_stats())
        self.assertEqual(stats["current_discoveries"], 0)
        self.assertEqual(stats["total_published"], 0)


class TestGlobalBus(unittest.TestCase):
    """Test singleton bus management."""

    def test_reset_creates_new(self):
        from src.core.discovery_bus import (
            get_discovery_bus_sync, reset_discovery_bus, Discovery, DiscoveryType
        )
        reset_discovery_bus()
        bus1 = get_discovery_bus_sync()
        d = Discovery("d1", "p0", "bf", DiscoveryType.EVIDENCE, "test")
        run_async(bus1.publish(d))
        
        reset_discovery_bus()
        bus2 = get_discovery_bus_sync()
        stats = run_async(bus2.get_stats())
        self.assertEqual(stats["current_discoveries"], 0)

    def test_sync_getter(self):
        from src.core.discovery_bus import get_discovery_bus_sync, reset_discovery_bus
        reset_discovery_bus()
        bus = get_discovery_bus_sync()
        self.assertIsNotNone(bus)

    def test_async_getter(self):
        from src.core.discovery_bus import get_discovery_bus, reset_discovery_bus
        reset_discovery_bus()
        bus = run_async(get_discovery_bus())
        self.assertIsNotNone(bus)


class TestTimestampFiltering(unittest.TestCase):
    """Test timestamp-based filtering."""

    def test_since_timestamp(self):
        from src.core.discovery_bus import DiscoveryBus, Discovery, DiscoveryType
        bus = DiscoveryBus()
        
        t1 = time.time()
        d1 = Discovery("d1", "p0", "bf", DiscoveryType.EVIDENCE, "old", timestamp=t1)
        run_async(bus.publish(d1))
        
        t2 = t1 + 1.0
        d2 = Discovery("d2", "p0", "bf", DiscoveryType.EVIDENCE, "new", timestamp=t2)
        run_async(bus.publish(d2))
        
        # Get only discoveries after t1
        results = run_async(bus.get_discoveries(since_timestamp=t1 + 0.5))
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].discovery_id, "d2")


if __name__ == "__main__":
    unittest.main(verbosity=2)
