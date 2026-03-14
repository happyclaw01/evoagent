# Copyright (c) 2025 MiroMind
# Unit Tests for EA-306: Result Cache Layer

import asyncio
import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))


def run_async(coro):
    """Helper to run async tests."""
    return asyncio.get_event_loop().run_until_complete(coro)


class TestCacheKey(unittest.TestCase):
    """Test cache key generation."""

    def test_same_args_same_key(self):
        from src.core.result_cache import _make_cache_key
        k1 = _make_cache_key("search", {"query": "hello world"})
        k2 = _make_cache_key("search", {"query": "hello world"})
        self.assertEqual(k1, k2)

    def test_different_tool_different_key(self):
        from src.core.result_cache import _make_cache_key
        k1 = _make_cache_key("search", {"query": "hello"})
        k2 = _make_cache_key("scrape", {"query": "hello"})
        self.assertNotEqual(k1, k2)

    def test_different_args_different_key(self):
        from src.core.result_cache import _make_cache_key
        k1 = _make_cache_key("search", {"query": "hello"})
        k2 = _make_cache_key("search", {"query": "world"})
        self.assertNotEqual(k1, k2)

    def test_whitespace_normalization(self):
        from src.core.result_cache import _make_cache_key
        k1 = _make_cache_key("search", {"query": "hello  world"})
        k2 = _make_cache_key("search", {"query": "hello world"})
        self.assertEqual(k1, k2)

    def test_case_normalization(self):
        from src.core.result_cache import _make_cache_key
        k1 = _make_cache_key("search", {"query": "Hello World"})
        k2 = _make_cache_key("search", {"query": "hello world"})
        self.assertEqual(k1, k2)

    def test_arg_order_irrelevant(self):
        from src.core.result_cache import _make_cache_key
        k1 = _make_cache_key("search", {"query": "test", "limit": 10})
        k2 = _make_cache_key("search", {"limit": 10, "query": "test"})
        self.assertEqual(k1, k2)


class TestCacheEntry(unittest.TestCase):
    """Test CacheEntry dataclass."""

    def test_not_expired(self):
        from src.core.result_cache import CacheEntry
        entry = CacheEntry(
            cache_key="k1", tool_name="search", args_hash="abc",
            result="data", ttl_seconds=300.0,
        )
        self.assertFalse(entry.is_expired)

    def test_expired(self):
        from src.core.result_cache import CacheEntry
        entry = CacheEntry(
            cache_key="k1", tool_name="search", args_hash="abc",
            result="data", ttl_seconds=0.0,
            created_at=time.time() - 1.0,
        )
        self.assertTrue(entry.is_expired)

    def test_to_dict(self):
        from src.core.result_cache import CacheEntry
        entry = CacheEntry(
            cache_key="k1", tool_name="search", args_hash="abc",
            result="data", source_path_id="path_0",
        )
        d = entry.to_dict()
        self.assertEqual(d["tool_name"], "search")
        self.assertEqual(d["source_path_id"], "path_0")
        self.assertIn("is_expired", d)


class TestResultCachePutGet(unittest.TestCase):
    """Test basic put/get operations."""

    def test_put_and_get(self):
        from src.core.result_cache import ResultCache
        cache = ResultCache()
        run_async(cache.put("search", {"query": "test"}, {"results": [1, 2, 3]}, "path_0"))
        result = run_async(cache.get("search", {"query": "test"}))
        self.assertEqual(result, {"results": [1, 2, 3]})

    def test_cache_miss(self):
        from src.core.result_cache import ResultCache
        cache = ResultCache()
        result = run_async(cache.get("search", {"query": "nonexistent"}))
        self.assertIsNone(result)

    def test_expired_entry_returns_none(self):
        from src.core.result_cache import ResultCache
        cache = ResultCache(default_ttl=0.0)
        run_async(cache.put("search", {"query": "test"}, "data"))
        time.sleep(0.01)
        result = run_async(cache.get("search", {"query": "test"}))
        self.assertIsNone(result)

    def test_custom_ttl(self):
        from src.core.result_cache import ResultCache
        cache = ResultCache(default_ttl=300.0)
        run_async(cache.put("search", {"query": "test"}, "data", ttl=0.0))
        time.sleep(0.01)
        result = run_async(cache.get("search", {"query": "test"}))
        self.assertIsNone(result)

    def test_hit_count_increments(self):
        from src.core.result_cache import ResultCache
        cache = ResultCache()
        run_async(cache.put("search", {"query": "test"}, "data"))
        run_async(cache.get("search", {"query": "test"}))
        run_async(cache.get("search", {"query": "test"}))
        stats = run_async(cache.get_stats())
        self.assertEqual(stats["hits"], 2)

    def test_disabled_cache(self):
        from src.core.result_cache import ResultCache
        cache = ResultCache(enabled=False)
        run_async(cache.put("search", {"query": "test"}, "data"))
        result = run_async(cache.get("search", {"query": "test"}))
        self.assertIsNone(result)


class TestResultCacheEviction(unittest.TestCase):
    """Test LRU eviction."""

    def test_lru_eviction(self):
        from src.core.result_cache import ResultCache
        cache = ResultCache(max_entries=3)
        for i in range(4):
            run_async(cache.put("search", {"query": f"q{i}"}, f"result_{i}"))
        stats = run_async(cache.get_stats())
        self.assertEqual(stats["current_entries"], 3)
        self.assertEqual(stats["evictions"], 1)
        # Oldest (q0) should be evicted
        r0 = run_async(cache.get("search", {"query": "q0"}))
        self.assertIsNone(r0)
        # Newest should still be there
        r3 = run_async(cache.get("search", {"query": "q3"}))
        self.assertEqual(r3, "result_3")


class TestResultCacheInvalidate(unittest.TestCase):
    """Test invalidation."""

    def test_invalidate_specific(self):
        from src.core.result_cache import ResultCache
        cache = ResultCache()
        run_async(cache.put("search", {"query": "test"}, "data"))
        removed = run_async(cache.invalidate("search", {"query": "test"}))
        self.assertTrue(removed)
        result = run_async(cache.get("search", {"query": "test"}))
        self.assertIsNone(result)

    def test_invalidate_nonexistent(self):
        from src.core.result_cache import ResultCache
        cache = ResultCache()
        removed = run_async(cache.invalidate("search", {"query": "nope"}))
        self.assertFalse(removed)

    def test_invalidate_by_tool(self):
        from src.core.result_cache import ResultCache
        cache = ResultCache()
        run_async(cache.put("search", {"query": "q1"}, "r1"))
        run_async(cache.put("search", {"query": "q2"}, "r2"))
        run_async(cache.put("scrape", {"url": "u1"}, "r3"))
        count = run_async(cache.invalidate_by_tool("search"))
        self.assertEqual(count, 2)
        stats = run_async(cache.get_stats())
        self.assertEqual(stats["current_entries"], 1)


class TestResultCacheCleanup(unittest.TestCase):
    """Test expired entry cleanup."""

    def test_cleanup_expired(self):
        from src.core.result_cache import ResultCache
        cache = ResultCache(default_ttl=0.0)
        run_async(cache.put("search", {"query": "q1"}, "r1"))
        run_async(cache.put("search", {"query": "q2"}, "r2"))
        time.sleep(0.01)
        removed = run_async(cache.cleanup_expired())
        self.assertEqual(removed, 2)
        stats = run_async(cache.get_stats())
        self.assertEqual(stats["current_entries"], 0)


class TestResultCacheStats(unittest.TestCase):
    """Test statistics and reporting."""

    def test_stats_initial(self):
        from src.core.result_cache import ResultCache
        cache = ResultCache()
        stats = run_async(cache.get_stats())
        self.assertEqual(stats["hits"], 0)
        self.assertEqual(stats["misses"], 0)
        self.assertEqual(stats["hit_rate"], 0.0)

    def test_hit_rate(self):
        from src.core.result_cache import ResultCache
        cache = ResultCache()
        run_async(cache.put("search", {"query": "test"}, "data"))
        run_async(cache.get("search", {"query": "test"}))  # hit
        run_async(cache.get("search", {"query": "miss"}))  # miss
        stats = run_async(cache.get_stats())
        self.assertAlmostEqual(stats["hit_rate"], 0.5)

    def test_entries_by_tool(self):
        from src.core.result_cache import ResultCache
        cache = ResultCache()
        run_async(cache.put("search", {"query": "q1"}, "r1"))
        run_async(cache.put("search", {"query": "q2"}, "r2"))
        run_async(cache.put("scrape", {"url": "u1"}, "r3"))
        by_tool = run_async(cache.get_entries_by_tool())
        self.assertEqual(by_tool["search"], 2)
        self.assertEqual(by_tool["scrape"], 1)

    def test_savings_estimate(self):
        from src.core.result_cache import ResultCache
        cache = ResultCache()
        run_async(cache.put("search", {"query": "test"}, "data"))
        run_async(cache.get("search", {"query": "test"}))
        run_async(cache.get("search", {"query": "test"}))
        savings = run_async(cache.get_savings_estimate())
        self.assertEqual(savings["total_cache_hits"], 2)
        self.assertEqual(savings["estimated_api_calls_saved"], 2)


class TestResultCacheHas(unittest.TestCase):
    """Test has() check without counting hits."""

    def test_has_existing(self):
        from src.core.result_cache import ResultCache
        cache = ResultCache()
        run_async(cache.put("search", {"query": "test"}, "data"))
        self.assertTrue(run_async(cache.has("search", {"query": "test"})))

    def test_has_nonexistent(self):
        from src.core.result_cache import ResultCache
        cache = ResultCache()
        self.assertFalse(run_async(cache.has("search", {"query": "nope"})))

    def test_has_expired(self):
        from src.core.result_cache import ResultCache
        cache = ResultCache(default_ttl=0.0)
        run_async(cache.put("search", {"query": "test"}, "data"))
        time.sleep(0.01)
        self.assertFalse(run_async(cache.has("search", {"query": "test"})))


class TestResultCacheClear(unittest.TestCase):
    """Test clear."""

    def test_clear(self):
        from src.core.result_cache import ResultCache
        cache = ResultCache()
        run_async(cache.put("search", {"query": "test"}, "data"))
        run_async(cache.clear())
        stats = run_async(cache.get_stats())
        self.assertEqual(stats["current_entries"], 0)
        self.assertEqual(stats["puts"], 0)


class TestGlobalCache(unittest.TestCase):
    """Test singleton management."""

    def test_singleton(self):
        from src.core.result_cache import get_result_cache, reset_result_cache
        reset_result_cache()
        c1 = get_result_cache()
        c2 = get_result_cache()
        self.assertIs(c1, c2)

    def test_reset(self):
        from src.core.result_cache import get_result_cache, reset_result_cache
        reset_result_cache()
        c1 = get_result_cache()
        run_async(c1.put("search", {"query": "test"}, "data"))
        reset_result_cache()
        c2 = get_result_cache()
        stats = run_async(c2.get_stats())
        self.assertEqual(stats["current_entries"], 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
