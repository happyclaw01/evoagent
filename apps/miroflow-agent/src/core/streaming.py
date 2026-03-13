# Copyright (c) 2025 MiroMind
# EA-011: Async Streaming Output
#
# Provides real-time streaming of intermediate thinking process
# from each path to consumers (frontend, logs, etc.)

import asyncio
import json
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional
import uuid


class StreamEventType(Enum):
    """Types of streaming events"""
    PATH_START = "path_start"
    PATH_END = "path_end"
    THINKING = "thinking"  # LLM thought process
    TOOL_CALL = "tool_call"
    TOOL_RESULT = "tool_result"
    TURN_START = "turn_start"
    TURN_END = "turn_end"
    ERROR = "error"
    INFO = "info"
    WARNING = "warning"
    COST_UPDATE = "cost_update"
    CONSENSUS = "consensus"  # EA-009: early stopping consensus reached


@dataclass
class StreamEvent:
    """A single streaming event"""
    event_type: StreamEventType
    path_id: Optional[str] = None
    strategy_name: Optional[str] = None
    turn: Optional[int] = None
    content: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    event_id: str = field(default_factory=lambda: str(uuid.uuid4()))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "event_type": self.event_type.value,
            "path_id": self.path_id,
            "strategy_name": self.strategy_name,
            "turn": self.turn,
            "content": self.content,
            "metadata": self.metadata,
            "timestamp": self.timestamp,
            "event_id": self.event_id,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict())


class StreamConsumer(ABC):
    """Abstract base class for stream consumers"""
    
    @abstractmethod
    async def send(self, event: StreamEvent):
        """Send an event to this consumer"""
        pass
    
    @abstractmethod
    async def close(self):
        """Close this consumer"""
        pass


class QueueStreamConsumer(StreamConsumer):
    """Consumer that puts events into an asyncio queue"""
    
    def __init__(self, queue: asyncio.Queue):
        self.queue = queue
    
    async def send(self, event: StreamEvent):
        await self.queue.put(event)
    
    async def close(self):
        pass  # Queue doesn't need closing


class CallbackStreamConsumer(StreamConsumer):
    """Consumer that calls a callback function for each event"""
    
    def __init__(self, callback: Callable[[StreamEvent], None]):
        self.callback = callback
    
    async def send(self, event: StreamEvent):
        try:
            self.callback(event)
        except Exception as e:
            pass  # Don't let callback errors break the stream
    
    async def close(self):
        pass


class FileStreamConsumer(StreamConsumer):
    """Consumer that writes events to a file in real-time"""
    
    def __init__(self, filepath: Path, buffer_size: int = 1):
        self.filepath = filepath
        self.buffer_size = buffer_size
        self.buffer: List[str] = []
        self.file_handle = None
        
    async def _ensure_file_open(self):
        if self.file_handle is None:
            self.filepath.parent.mkdir(parents=True, exist_ok=True)
            self.file_handle = open(self.filepath, "a", buffering=1)
    
    async def send(self, event: StreamEvent):
        await self._ensure_file_open()
        line = event.to_json() + "\n"
        self.file_handle.write(line)
        self.file_handle.flush()
    
    async def close(self):
        if self.file_handle:
            self.file_handle.close()
            self.file_handle = None


class ConsoleStreamConsumer(StreamConsumer):
    """Consumer that prints events to console"""
    
    def __init__(self, verbose: bool = True):
        self.verbose = verbose
    
    async def send(self, event: StreamEvent):
        if not self.verbose and event.event_type not in [
            StreamEventType.INFO, 
            StreamEventType.WARNING,
            StreamEventType.ERROR
        ]:
            return
        
        prefix = f"[{event.event_type.value.upper()}]"
        if event.path_id:
            prefix += f" [{event.path_id}]"
        if event.turn is not None:
            prefix += f" T{event.turn}"
        
        print(f"{prefix}: {event.content[:200]}")
    
    async def close(self):
        pass


class MultiStreamManager:
    """
    Manages multiple stream consumers and coordinates event distribution.
    
    Usage:
        manager = MultiStreamManager()
        
        # Add consumers
        manager.add_consumer(ConsoleStreamConsumer())
        manager.add_consumer(FileStreamManager(Path("logs/stream.jsonl")))
        
        # Create a stream for a path
        stream = manager.create_path_stream("path_0", "breadth_first")
        
        # Emit events
        await stream.emit_thinking("Let me search for...")
        await stream.emit_tool_call("google_search", {"q": "test"})
    """
    
    def __init__(self):
        self.consumers: List[StreamConsumer] = []
        self.path_streams: Dict[str, 'PathStream'] = {}
    
    def add_consumer(self, consumer: StreamConsumer):
        """Add a stream consumer"""
        self.consumers.append(consumer)
    
    def remove_consumer(self, consumer: StreamConsumer):
        """Remove a stream consumer"""
        if consumer in self.consumers:
            self.consumers.remove(consumer)
    
    async def broadcast(self, event: StreamEvent):
        """Broadcast an event to all consumers"""
        for consumer in self.consumers:
            try:
                await consumer.send(event)
            except Exception as e:
                # Don't let one consumer failure break others
                pass
    
    def create_path_stream(
        self, 
        path_id: str, 
        strategy_name: str,
        task_description: Optional[str] = None,
    ) -> 'PathStream':
        """Create a stream for a specific path"""
        stream = PathStream(
            path_id=path_id,
            strategy_name=strategy_name,
            task_description=task_description,
            manager=self,
        )
        self.path_streams[path_id] = stream
        return stream
    
    def get_path_stream(self, path_id: str) -> Optional['PathStream']:
        """Get a path stream by ID"""
        return self.path_streams.get(path_id)
    
    async def close_all(self):
        """Close all consumers"""
        for consumer in self.consumers:
            await consumer.close()
        self.path_streams.clear()


class PathStream:
    """
    Represents a stream of events from a single path.
    
    Usage:
        stream = manager.create_path_stream("path_0", "breadth_first")
        
        await stream.start()
        await stream.thinking("Analyzing the problem...")
        await stream.tool_call("search", {"query": "..."})
        await stream.thinking("Found results, processing...")
        await stream.end()
    """
    
    def __init__(
        self,
        path_id: str,
        strategy_name: str,
        task_description: Optional[str],
        manager: MultiStreamManager,
    ):
        self.path_id = path_id
        self.strategy_name = strategy_name
        self.task_description = task_description
        self.manager = manager
        self.turn = 0
        self.started = False
        self.ended = False
    
    async def start(self):
        """Emit path start event"""
        if self.started:
            return
        
        event = StreamEvent(
            event_type=StreamEventType.PATH_START,
            path_id=self.path_id,
            strategy_name=self.strategy_name,
            content=f"Starting path with strategy: {self.strategy_name}",
            metadata={"task_description": self.task_description} if self.task_description else {},
        )
        await self.manager.broadcast(event)
        self.started = True
    
    async def end(self, final_answer: str = "", status: str = "unknown"):
        """Emit path end event"""
        if self.ended:
            return
        
        event = StreamEvent(
            event_type=StreamEventType.PATH_END,
            path_id=self.path_id,
            strategy_name=self.strategy_name,
            content=f"Path completed with status: {status}",
            metadata={"final_answer": final_answer[:500], "status": status},
        )
        await self.manager.broadcast(event)
        self.ended = True
    
    async def thinking(self, content: str):
        """Emit a thinking (LLM thought) event"""
        event = StreamEvent(
            event_type=StreamEventType.THINKING,
            path_id=self.path_id,
            strategy_name=self.strategy_name,
            turn=self.turn,
            content=content,
        )
        await self.manager.broadcast(event)
    
    async def turn_start(self):
        """Emit turn start event"""
        self.turn += 1
        event = StreamEvent(
            event_type=StreamEventType.TURN_START,
            path_id=self.path_id,
            strategy_name=self.strategy_name,
            turn=self.turn,
            content=f"Starting turn {self.turn}",
        )
        await self.manager.broadcast(event)
    
    async def turn_end(self, tool_calls: int = 0):
        """Emit turn end event"""
        event = StreamEvent(
            event_type=StreamEventType.TURN_END,
            path_id=self.path_id,
            strategy_name=self.strategy_name,
            turn=self.turn,
            content=f"Turn {self.turn} completed",
            metadata={"tool_calls_this_turn": tool_calls},
        )
        await self.manager.broadcast(event)
    
    async def tool_call(self, tool_name: str, params: Dict[str, Any]):
        """Emit a tool call event"""
        event = StreamEvent(
            event_type=StreamEventType.TOOL_CALL,
            path_id=self.path_id,
            strategy_name=self.strategy_name,
            turn=self.turn,
            content=f"Calling tool: {tool_name}",
            metadata={"tool_name": tool_name, "params": params},
        )
        await self.manager.broadcast(event)
    
    async def tool_result(self, tool_name: str, result: str, success: bool = True):
        """Emit a tool result event"""
        # Truncate long results
        display_result = result[:500] + "..." if len(result) > 500 else result
        
        event = StreamEvent(
            event_type=StreamEventType.TOOL_RESULT,
            path_id=self.path_id,
            strategy_name=self.strategy_name,
            turn=self.turn,
            content=f"Tool {tool_name} result ({'success' if success else 'error'})",
            metadata={
                "tool_name": tool_name, 
                "result_preview": display_result,
                "success": success,
            },
        )
        await self.manager.broadcast(event)
    
    async def info(self, content: str):
        """Emit an info event"""
        event = StreamEvent(
            event_type=StreamEventType.INFO,
            path_id=self.path_id,
            strategy_name=self.strategy_name,
            turn=self.turn,
            content=content,
        )
        await self.manager.broadcast(event)
    
    async def warning(self, content: str):
        """Emit a warning event"""
        event = StreamEvent(
            event_type=StreamEventType.WARNING,
            path_id=self.path_id,
            strategy_name=self.strategy_name,
            turn=self.turn,
            content=content,
        )
        await self.manager.broadcast(event)
    
    async def error(self, content: str, error_details: Optional[str] = None):
        """Emit an error event"""
        event = StreamEvent(
            event_type=StreamEventType.ERROR,
            path_id=self.path_id,
            strategy_name=self.strategy_name,
            turn=self.turn,
            content=content,
            metadata={"error_details": error_details} if error_details else {},
        )
        await self.manager.broadcast(event)
    
    async def consensus_reached(self, answer: str, consensus_type: str):
        """EA-009: Emit consensus reached event"""
        event = StreamEvent(
            event_type=StreamEventType.CONSENSUS,
            path_id=self.path_id,
            strategy_name=self.strategy_name,
            content=f"Consensus reached: {answer[:100]}",
            metadata={"answer": answer, "consensus_type": consensus_type},
        )
        await self.manager.broadcast(event)


# Global stream manager instance
_global_stream_manager: Optional[MultiStreamManager] = None


def get_stream_manager() -> MultiStreamManager:
    """Get or create the global stream manager"""
    global _global_stream_manager
    if _global_stream_manager is None:
        _global_stream_manager = MultiStreamManager()
    return _global_stream_manager


def reset_stream_manager():
    """Reset the global stream manager (for testing)"""
    global _global_stream_manager
    if _global_stream_manager:
        asyncio.create_task(_global_stream_manager.close_all())
    _global_stream_manager = None