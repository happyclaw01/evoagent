# Copyright (c) 2025 MiroMind
# Unit Tests for EA-307: OpenViking Integration

import asyncio
import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent))


class TestOpenVikingContextInit(unittest.TestCase):
    """Test OpenVikingContext initialization"""

    def test_default_initialization(self):
        """Test default init values"""
        from src.core.openviking_context import OpenVikingContext
        
        ctx = OpenVikingContext()
        
        self.assertEqual(ctx.server_url, "http://localhost:8080")
        self.assertEqual(ctx.api_key, "")
        self.assertTrue(ctx.enabled)
        self.assertTrue(ctx.fallback_mode)
        self.assertFalse(ctx._connected)

    def test_custom_initialization(self):
        """Test custom init values"""
        from src.core.openviking_context import OpenVikingContext
        
        ctx = OpenVikingContext(
            server_url="http://custom:9090",
            api_key="test-key",
            enabled=False,
            fallback_mode=False,
        )
        
        self.assertEqual(ctx.server_url, "http://custom:9090")
        self.assertEqual(ctx.api_key, "test-key")
        self.assertFalse(ctx.enabled)


class TestContextLoading(unittest.TestCase):
    """Test EA-307.2: Context Loading"""

    def test_load_task_context_returns_list(self):
        """Test load_task_context returns list of ContextBlocks"""
        import asyncio
        from src.core.openviking_context import OpenVikingContext
        
        async def test():
            ctx = OpenVikingContext()
            await ctx.connect()
            
            result = await ctx.load_task_context(
                task_description="Test task",
                strategy_name="breadth_first",
                load_depth="L1"
            )
            
            self.assertIsInstance(result, list)
            self.assertGreater(len(result), 0)
            
            # Check block structure
            for block in result:
                self.assertTrue(hasattr(block, 'uri'))
                self.assertTrue(hasattr(block, 'content'))
                self.assertTrue(hasattr(block, 'layer'))
        
        asyncio.run(test())

    def test_different_strategies_different_context(self):
        """Test different strategies get different context"""
        import asyncio
        from src.core.openviking_context import OpenVikingContext
        
        async def test():
            ctx = OpenVikingContext()
            await ctx.connect()
            
            ctx_breadth = await ctx.load_task_context("test", "breadth_first", "L1")
            ctx_depth = await ctx.load_task_context("test", "depth_first", "L1")
            
            # Should have different content
            breadth_content = " ".join(b.uri + b.content for b in ctx_breadth)
            depth_content = " ".join(b.uri + b.content for b in ctx_depth)
            
            self.assertNotEqual(breadth_content, depth_content)
        
        asyncio.run(test())


class TestExperienceStorage(unittest.TestCase):
    """Test EA-307.3: Experience Storage"""

    def test_save_path_result_stores_memory(self):
        """Test saving path result adds to memory"""
        import asyncio
        from src.core.openviking_context import OpenVikingContext
        
        async def test():
            ctx = OpenVikingContext()
            await ctx.connect()
            
            result = {
                "answer": "The answer is 42",
                "turns": 5,
                "tool_calls": ["search", "scrape"]
            }
            
            await ctx.save_path_result(
                path_id="path_0",
                strategy="breadth_first",
                result=result,
                success=True
            )
            
            # Check memory was stored
            self.assertIn("path_0", ctx._memory_store)
            self.assertEqual(len(ctx._memory_store["path_0"]), 1)
        
        asyncio.run(test())

    def test_failed_result_not_stored(self):
        """Test failed results are not stored"""
        import asyncio
        from src.core.openviking_context import OpenVikingContext
        
        async def test():
            ctx = OpenVikingContext()
            await ctx.connect()
            
            result = {"answer": "test", "turns": 1}
            
            await ctx.save_path_result(
                path_id="path_fail",
                strategy="depth_first",
                result=result,
                success=False
            )
            
            # Should not store failed results
            self.assertEqual(len(ctx._memory_store), 0)
        
        asyncio.run(test())


class TestCrossPathSharing(unittest.TestCase):
    """Test EA-307.4: Cross-Path Sharing"""

    def test_share_discovery(self):
        """Test sharing discovery between paths"""
        import asyncio
        from src.core.openviking_context import OpenVikingContext, Discovery
        
        async def test():
            ctx = OpenVikingContext()
            await ctx.connect()
            
            discovery = Discovery(
                path_id="path_0",
                strategy="breadth_first",
                uri="https://example.com/important",
                title="Important Page",
                snippet="Key information"
            )
            
            await ctx.share_discovery("path_0", "breadth_first", discovery)
            
            # Check discovery was stored
            self.assertIn("path_0", ctx._discovery_store)
            self.assertEqual(len(ctx._discovery_store["path_0"]), 1)
        
        asyncio.run(test())

    def test_query_shared_discoveries(self):
        """Test querying discoveries from other paths"""
        import asyncio
        from src.core.openviking_context import OpenVikingContext, Discovery
        
        async def test():
            ctx = OpenVikingContext()
            await ctx.connect()
            
            # Add discovery from path_0
            discovery = Discovery(
                path_id="path_0",
                strategy="breadth_first",
                uri="https://arxiv.org/papers/AI",
                title="AI Paper",
                snippet="Important research"
            )
            await ctx.share_discovery("path_0", "breadth_first", discovery)
            
            # Query from path_1 (excluding path_0)
            results = await ctx.query_shared_discoveries(
                task="Find AI papers",
                exclude_path="path_1"
            )
            
            # Should find the discovery
            self.assertEqual(len(results), 1)
            self.assertEqual(results[0].uri, "https://arxiv.org/papers/AI")
        
        asyncio.run(test())

    def test_exclude_own_discoveries(self):
        """Test that querying excludes own path"""
        import asyncio
        from src.core.openviking_context import OpenVikingContext, Discovery
        
        async def test():
            ctx = OpenVikingContext()
            await ctx.connect()
            
            # Add discovery from path_0
            await ctx.share_discovery("path_0", "breadth_first", 
                Discovery("path_0", "breadth", "http://test.com", "Test", ""))
            
            # Query from same path - should not return own discoveries
            results = await ctx.query_shared_discoveries("test", "path_0")
            
            # path_0's discovery should be excluded
            self.assertEqual(len(results), 0)
        
        asyncio.run(test())


class TestMemoryIteration(unittest.TestCase):
    """Test EA-307.5: Memory Self-Iteration"""

    def test_trigger_memory_iteration(self):
        """Test memory iteration generates summary"""
        import asyncio
        from src.core.openviking_context import OpenVikingContext
        
        async def test():
            ctx = OpenVikingContext()
            await ctx.connect()
            
            # Add some memories
            await ctx.save_path_result("p1", "breadth_first", 
                {"answer": "A", "turns": 3, "tool_calls": []}, True)
            await ctx.save_path_result("p2", "breadth_first", 
                {"answer": "B", "turns": 4, "tool_calls": []}, True)
            await ctx.save_path_result("p3", "depth_first", 
                {"answer": "C", "turns": 5, "tool_calls": []}, True)
            
            # Trigger iteration
            result = await ctx.trigger_memory_iteration()
            
            # Check results
            self.assertEqual(result["total_memories_processed"], 3)
            self.assertIn("breadth_first", result["strategy_distribution"])
            self.assertEqual(result["strategy_distribution"]["breadth_first"], 2)
            self.assertEqual(result["recommended_strategy"], "breadth_first")
        
        asyncio.run(test())


class TestFactory(unittest.TestCase):
    """Test factory function"""

    def test_create_openviking_context(self):
        """Test factory creates context with config"""
        from src.core.openviking_context import create_openviking_context
        
        config = {
            "openviking": {
                "server_url": "http://test:8000",
                "api_key": "key123",
                "enabled": True,
            }
        }
        
        ctx = create_openviking_context(config)
        
        self.assertEqual(ctx.server_url, "http://test:8000")
        self.assertEqual(ctx.api_key, "key123")
        self.assertTrue(ctx.enabled)


class TestStatistics(unittest.TestCase):
    """Test statistics method"""

    def test_get_statistics(self):
        """Test statistics reflect current state"""
        import asyncio
        from src.core.openviking_context import OpenVikingContext
        
        async def test():
            ctx = OpenVikingContext()
            await ctx.connect()
            
            # Add data
            await ctx.save_path_result("p1", "s1", {"answer": "a", "turns": 1, "tool_calls": []}, True)
            await ctx.share_discovery("p1", "s1", 
                type('D', (), {'path_id': 'p1', 'strategy': 's1', 'uri': 'u', 'title': 't', 'snippet': 's'})())
            
            stats = ctx.get_statistics()
            
            self.assertEqual(stats["total_memories"], 1)
            self.assertEqual(stats["total_discoveries"], 1)
            self.assertEqual(stats["paths_with_memory"], 1)
        
        asyncio.run(test())


if __name__ == "__main__":
    unittest.main(verbosity=2)