# Copyright (c) 2025 MiroMind
# Unit Tests for EA-011: Async Streaming Output

import asyncio
import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent))


class TestStreamEvent(unittest.TestCase):
    """Test StreamEvent dataclass"""

    def test_stream_event_creation(self):
        """Test creating a StreamEvent"""
        from src.core.streaming import StreamEvent, StreamEventType
        
        event = StreamEvent(
            event_type=StreamEventType.THINKING,
            path_id="path_0",
            turn=1,
            content="Testing the system",
        )
        
        self.assertEqual(event.event_type, StreamEventType.THINKING)
        self.assertEqual(event.path_id, "path_0")
        self.assertEqual(event.turn, 1)
        self.assertEqual(event.content, "Testing the system")
    
    def test_stream_event_to_dict(self):
        """Test converting event to dict"""
        from src.core.streaming import StreamEvent, StreamEventType
        
        event = StreamEvent(
            event_type=StreamEventType.TOOL_CALL,
            path_id="path_1",
            content="Calling search tool",
        )
        
        d = event.to_dict()
        
        self.assertIn("event_type", d)
        self.assertIn("path_id", d)
        self.assertIn("content", d)
        self.assertIn("timestamp", d)
        self.assertIn("event_id", d)
    
    def test_stream_event_to_json(self):
        """Test converting event to JSON"""
        from src.core.streaming import StreamEvent, StreamEventType
        
        event = StreamEvent(
            event_type=StreamEventType.INFO,
            content="Test message",
        )
        
        json_str = event.to_json()
        
        self.assertIn("event_type", json_str)
        self.assertIn("Test message", json_str)


class TestStreamConsumers(unittest.TestCase):
    """Test stream consumers"""

    def test_callback_consumer(self):
        """Test callback consumer"""
        from src.core.streaming import CallbackStreamConsumer, StreamEvent, StreamEventType
        
        received_events = []
        
        def callback(event):
            received_events.append(event)
        
        consumer = CallbackStreamConsumer(callback)
        
        event = StreamEvent(
            event_type=StreamEventType.INFO,
            content="Test",
        )
        
        # Run async callback
        asyncio.run(consumer.send(event))
        
        self.assertEqual(len(received_events), 1)
        self.assertEqual(received_events[0].content, "Test")

    def test_queue_consumer(self):
        """Test queue consumer"""
        from src.core.streaming import QueueStreamConsumer, StreamEvent, StreamEventType
        
        queue = asyncio.Queue()
        consumer = QueueStreamConsumer(queue)
        
        event = StreamEvent(
            event_type=StreamEventType.INFO,
            content="Queue test",
        )
        
        asyncio.run(consumer.send(event))
        
        # Check queue has the event
        self.assertFalse(queue.empty())
        queued_event = asyncio.run(queue.get())
        self.assertEqual(queued_event.content, "Queue test")


class TestMultiStreamManager(unittest.TestCase):
    """Test MultiStreamManager"""

    def test_create_path_stream(self):
        """Test creating a path stream"""
        from src.core.streaming import MultiStreamManager
        
        manager = MultiStreamManager()
        stream = manager.create_path_stream("path_0", "breadth_first")
        
        self.assertEqual(stream.path_id, "path_0")
        self.assertEqual(stream.strategy_name, "breadth_first")
        self.assertEqual(manager.get_path_stream("path_0"), stream)

    def test_broadcast_to_console(self):
        """Test broadcasting to console consumer"""
        from src.core.streaming import (
            MultiStreamManager, 
            ConsoleStreamConsumer,
            StreamEvent,
            StreamEventType,
        )
        
        manager = MultiStreamManager()
        manager.add_consumer(ConsoleStreamConsumer(verbose=True))
        
        # This should not raise
        event = StreamEvent(
            event_type=StreamEventType.INFO,
            content="Test broadcast",
        )
        
        asyncio.run(manager.broadcast(event))


class TestPathStream(unittest.TestCase):
    """Test PathStream"""

    def test_path_stream_lifecycle(self):
        """Test path stream start and end"""
        from src.core.streaming import (
            MultiStreamManager, 
            PathStream,
            CallbackStreamConsumer,
            StreamEventType,
        )
        
        received = []
        
        class TestConsumer(CallbackStreamConsumer):
            async def send(self, event):
                received.append(event)
        
        manager = MultiStreamManager()
        consumer = TestConsumer(lambda e: None)
        manager.add_consumer(consumer)
        
        stream = manager.create_path_stream("path_test", "depth_first", "Test task")
        
        # Start
        asyncio.run(stream.start())
        
        # Check start event was broadcast
        start_events = [e for e in received if e.event_type == StreamEventType.PATH_START]
        self.assertEqual(len(start_events), 1)
        self.assertEqual(start_events[0].path_id, "path_test")
        
        received.clear()
        
        # End
        asyncio.run(stream.end("Final answer", "success"))
        
        # Check end event
        end_events = [e for e in received if e.event_type == StreamEventType.PATH_END]
        self.assertEqual(len(end_events), 1)
        self.assertEqual(end_events[0].metadata["status"], "success")

    def test_thinking_event(self):
        """Test thinking event emission"""
        from src.core.streaming import (
            MultiStreamManager, 
            CallbackStreamConsumer,
            StreamEventType,
        )
        
        received = []
        
        class TestConsumer(CallbackStreamConsumer):
            async def send(self, event):
                received.append(event)
        
        manager = MultiStreamManager()
        manager.add_consumer(TestConsumer(lambda e: None))
        
        stream = manager.create_path_stream("p1", "breadth_first")
        asyncio.run(stream.start())
        asyncio.run(stream.thinking("Let me search for..."))
        
        thinking_events = [e for e in received if e.event_type == StreamEventType.THINKING]
        self.assertEqual(len(thinking_events), 1)
        self.assertEqual(thinking_events[0].content, "Let me search for...")

    def test_tool_call_events(self):
        """Test tool call and result events"""
        from src.core.streaming import (
            MultiStreamManager, 
            CallbackStreamConsumer,
            StreamEventType,
        )
        
        received = []
        
        class TestConsumer(CallbackStreamConsumer):
            async def send(self, event):
                received.append(event)
        
        manager = MultiStreamManager()
        manager.add_consumer(TestConsumer(lambda e: None))
        
        stream = manager.create_path_stream("p1", "breadth_first")
        asyncio.run(stream.start())
        asyncio.run(stream.tool_call("google_search", {"q": "test"}))
        asyncio.run(stream.tool_result("google_search", '{"results": ["test"]}', True))
        
        call_events = [e for e in received if e.event_type == StreamEventType.TOOL_CALL]
        result_events = [e for e in received if e.event_type == StreamEventType.TOOL_RESULT]
        
        self.assertEqual(len(call_events), 1)
        self.assertEqual(call_events[0].metadata["tool_name"], "google_search")
        self.assertEqual(len(result_events), 1)
        self.assertTrue(result_events[0].metadata["success"])

    def test_turn_tracking(self):
        """Test turn counter increments"""
        from src.core.streaming import (
            MultiStreamManager, 
            CallbackStreamConsumer,
        )
        
        received = []
        
        class TestConsumer(CallbackStreamConsumer):
            async def send(self, event):
                received.append(event)
        
        manager = MultiStreamManager()
        manager.add_consumer(TestConsumer(lambda e: None))
        
        stream = manager.create_path_stream("p1", "breadth_first")
        asyncio.run(stream.start())
        asyncio.run(stream.turn_start())
        asyncio.run(stream.turn_start())
        asyncio.run(stream.turn_start())
        
        # Should be on turn 3 now
        self.assertEqual(stream.turn, 3)


class TestEventTypes(unittest.TestCase):
    """Test all event types are defined"""

    def test_all_event_types(self):
        """Test all expected event types exist"""
        from src.core.streaming import StreamEventType
        
        expected_types = [
            "PATH_START",
            "PATH_END",
            "THINKING",
            "TOOL_CALL",
            "TOOL_RESULT",
            "TURN_START",
            "TURN_END",
            "ERROR",
            "INFO",
            "WARNING",
            "COST_UPDATE",
            "CONSENSUS",
        ]
        
        for expected in expected_types:
            self.assertTrue(hasattr(StreamEventType, expected))


class TestGlobalManager(unittest.TestCase):
    """Test global stream manager singleton"""

    def test_get_stream_manager(self):
        """Test getting global stream manager"""
        from src.core.streaming import get_stream_manager, reset_stream_manager
        
        # Reset first
        reset_stream_manager()
        
        manager1 = get_stream_manager()
        manager2 = get_stream_manager()
        
        # Should be the same instance
        self.assertIs(manager1, manager2)


if __name__ == "__main__":
    unittest.main(verbosity=2)