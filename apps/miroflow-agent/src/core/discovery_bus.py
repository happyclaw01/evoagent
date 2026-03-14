# Copyright (c) 2025 MiroMind
# EA-305: Inter-Path Communication Bus (Discovery Bus)
#
# Enables paths to share intermediate discoveries during execution,
# avoiding redundant work and enabling cross-pollination of findings.
#
# Design references:
# - Ant Colony Optimization pheromone mechanism (Dorigo, 1992)
# - EvoAgent research log: multi-agent-collaboration-theory.md
# - Knowledge sharing Level 3-4 (intermediate discoveries + tool results)
#
# Key design decisions:
# - Async-safe: all operations are thread/coroutine safe via asyncio.Lock
# - Non-blocking: subscribers poll discoveries, never block on publish
# - Selective: paths can filter discoveries by type and relevance
# - Lightweight: discoveries are small metadata, not full results

import asyncio
import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Set

logger = logging.getLogger(__name__)


class DiscoveryType(str, Enum):
    """Types of discoveries that can be shared between paths."""
    EVIDENCE = "evidence"           # Found a key piece of evidence
    SOURCE = "source"               # Found a useful source/URL
    TOOL_RESULT = "tool_result"     # Cached tool call result (EA-306 bridge)
    DEAD_END = "dead_end"           # A search direction that leads nowhere
    CONTRADICTION = "contradiction" # Found conflicting information
    PARTIAL_ANSWER = "partial_answer"  # Intermediate answer candidate
    INSIGHT = "insight"             # A reasoning insight or connection


@dataclass
class Discovery:
    """A single discovery published by a path."""
    discovery_id: str
    path_id: str
    strategy_name: str
    discovery_type: DiscoveryType
    content: str                    # Human-readable description
    data: Dict[str, Any] = field(default_factory=dict)  # Structured data
    confidence: float = 0.5         # 0.0 to 1.0
    timestamp: float = field(default_factory=time.time)
    tags: List[str] = field(default_factory=list)  # For filtering
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "discovery_id": self.discovery_id,
            "path_id": self.path_id,
            "strategy_name": self.strategy_name,
            "discovery_type": self.discovery_type.value,
            "content": self.content,
            "data": self.data,
            "confidence": self.confidence,
            "timestamp": self.timestamp,
            "tags": self.tags,
        }
    
    def to_prompt_snippet(self) -> str:
        """Format discovery as a prompt snippet for injection into path context."""
        type_label = self.discovery_type.value.replace("_", " ").title()
        conf_label = f"{self.confidence:.0%}"
        return (
            f"[Discovery from {self.strategy_name}] "
            f"({type_label}, confidence: {conf_label}): {self.content}"
        )


class DiscoveryBus:
    """
    EA-305: Inter-path communication bus.
    
    Allows paths to publish intermediate discoveries and subscribe to
    discoveries from other paths. Implements a pheromone-like mechanism
    where discoveries accumulate and can influence other paths' decisions.
    
    Thread-safe via asyncio.Lock for concurrent path access.
    
    Usage:
        bus = DiscoveryBus()
        
        # Path A publishes a discovery
        await bus.publish(Discovery(
            discovery_id="d1",
            path_id="path_0",
            strategy_name="breadth_first",
            discovery_type=DiscoveryType.SOURCE,
            content="Found authoritative source: https://example.com/data",
            confidence=0.9,
            tags=["finance", "GDP"],
        ))
        
        # Path B retrieves discoveries from other paths
        discoveries = await bus.get_discoveries(
            exclude_path="path_1",  # Don't return own discoveries
            discovery_type=DiscoveryType.SOURCE,
        )
    """
    
    def __init__(self, max_discoveries: int = 100):
        """
        Args:
            max_discoveries: Maximum number of discoveries to retain (FIFO eviction).
        """
        self._discoveries: List[Discovery] = []
        self._lock = asyncio.Lock()
        self._max_discoveries = max_discoveries
        self._subscribers: Dict[str, float] = {}  # path_id -> last_read_timestamp
        self._stats = {
            "total_published": 0,
            "total_reads": 0,
            "evictions": 0,
        }
    
    async def publish(self, discovery: Discovery) -> None:
        """
        Publish a discovery to the bus.
        
        Args:
            discovery: The discovery to publish.
        """
        async with self._lock:
            self._discoveries.append(discovery)
            self._stats["total_published"] += 1
            
            # FIFO eviction if over capacity
            if len(self._discoveries) > self._max_discoveries:
                evicted = len(self._discoveries) - self._max_discoveries
                self._discoveries = self._discoveries[evicted:]
                self._stats["evictions"] += evicted
            
            logger.debug(
                f"EA-305: Discovery published by {discovery.path_id} "
                f"({discovery.discovery_type.value}): {discovery.content[:80]}"
            )
    
    async def get_discoveries(
        self,
        exclude_path: Optional[str] = None,
        discovery_type: Optional[DiscoveryType] = None,
        min_confidence: float = 0.0,
        since_timestamp: Optional[float] = None,
        tags: Optional[List[str]] = None,
        limit: int = 20,
    ) -> List[Discovery]:
        """
        Retrieve discoveries from the bus with optional filtering.
        
        Args:
            exclude_path: Exclude discoveries from this path (typically self).
            discovery_type: Filter by discovery type.
            min_confidence: Minimum confidence threshold.
            since_timestamp: Only return discoveries after this timestamp.
            tags: Filter by tags (any match).
            limit: Maximum number of discoveries to return.
        
        Returns:
            List of matching discoveries, most recent first.
        """
        async with self._lock:
            self._stats["total_reads"] += 1
            
            results = []
            for d in reversed(self._discoveries):  # Most recent first
                if len(results) >= limit:
                    break
                
                # Apply filters
                if exclude_path and d.path_id == exclude_path:
                    continue
                if discovery_type and d.discovery_type != discovery_type:
                    continue
                if d.confidence < min_confidence:
                    continue
                if since_timestamp and d.timestamp < since_timestamp:
                    continue
                if tags and not any(t in d.tags for t in tags):
                    continue
                
                results.append(d)
            
            # Update subscriber timestamp
            if exclude_path:
                self._subscribers[exclude_path] = time.time()
            
            return results
    
    async def get_new_discoveries(self, path_id: str, limit: int = 10) -> List[Discovery]:
        """
        Get discoveries published since this path's last read.
        Convenience method for incremental polling.
        
        Args:
            path_id: The requesting path's ID.
            limit: Maximum number of discoveries.
        
        Returns:
            New discoveries since last read by this path.
        """
        last_read = self._subscribers.get(path_id, 0.0)
        return await self.get_discoveries(
            exclude_path=path_id,
            since_timestamp=last_read,
            limit=limit,
        )
    
    async def get_dead_ends(self, exclude_path: Optional[str] = None) -> List[Discovery]:
        """Get all reported dead ends (paths to avoid)."""
        return await self.get_discoveries(
            exclude_path=exclude_path,
            discovery_type=DiscoveryType.DEAD_END,
            limit=50,
        )
    
    async def get_contradictions(self, exclude_path: Optional[str] = None) -> List[Discovery]:
        """Get all reported contradictions (need resolution)."""
        return await self.get_discoveries(
            exclude_path=exclude_path,
            discovery_type=DiscoveryType.CONTRADICTION,
            limit=50,
        )
    
    async def format_context_for_path(
        self,
        path_id: str,
        max_tokens_estimate: int = 500,
    ) -> str:
        """
        Format relevant discoveries as context text for injection into a path's prompt.
        
        This is the main integration point: before each turn, a path can call this
        to get a summary of what other paths have found.
        
        Args:
            path_id: The requesting path's ID.
            max_tokens_estimate: Rough limit on output length (chars ≈ tokens * 4).
        
        Returns:
            Formatted context string, or empty string if no relevant discoveries.
        """
        discoveries = await self.get_new_discoveries(path_id, limit=10)
        
        if not discoveries:
            return ""
        
        lines = ["\n[Cross-Path Intelligence — discoveries from other exploration paths:]"]
        char_count = len(lines[0])
        max_chars = max_tokens_estimate * 4
        
        for d in discoveries:
            snippet = d.to_prompt_snippet()
            if char_count + len(snippet) + 2 > max_chars:
                break
            lines.append(f"  • {snippet}")
            char_count += len(snippet) + 4
        
        lines.append("[End of cross-path intelligence]\n")
        
        return "\n".join(lines)
    
    async def get_stats(self) -> Dict[str, Any]:
        """Get bus statistics."""
        async with self._lock:
            return {
                **self._stats,
                "current_discoveries": len(self._discoveries),
                "max_capacity": self._max_discoveries,
                "active_subscribers": len(self._subscribers),
            }
    
    async def clear(self) -> None:
        """Clear all discoveries and reset state."""
        async with self._lock:
            self._discoveries.clear()
            self._subscribers.clear()
            self._stats = {
                "total_published": 0,
                "total_reads": 0,
                "evictions": 0,
            }


# Singleton instance for cross-path communication
_global_bus: Optional[DiscoveryBus] = None
_bus_lock = asyncio.Lock()


async def get_discovery_bus(max_discoveries: int = 100) -> DiscoveryBus:
    """Get or create the global DiscoveryBus singleton."""
    global _global_bus
    if _global_bus is None:
        _global_bus = DiscoveryBus(max_discoveries=max_discoveries)
    return _global_bus


def get_discovery_bus_sync(max_discoveries: int = 100) -> DiscoveryBus:
    """Synchronous getter for the global DiscoveryBus (creates if needed)."""
    global _global_bus
    if _global_bus is None:
        _global_bus = DiscoveryBus(max_discoveries=max_discoveries)
    return _global_bus


def reset_discovery_bus() -> None:
    """Reset the global bus (for testing)."""
    global _global_bus
    _global_bus = None
