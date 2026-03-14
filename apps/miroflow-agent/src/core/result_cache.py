# Copyright (c) 2025 MiroMind
# EA-306: Result Cache Layer
#
# Caches tool call results across paths to avoid redundant API calls.
# When path A searches "GDP growth rate 2024" and path B tries the same query,
# the cache returns the stored result instead of making another API call.
#
# Integrates with EA-305 DiscoveryBus: cached results can optionally be
# published as TOOL_RESULT discoveries for cross-path awareness.
#
# Key design decisions:
# - Content-addressed: cache key = hash(tool_name + normalized_args)
# - TTL-based expiration: results expire after configurable duration
# - Hit/miss stats for cost analysis (EA-304 integration)
# - Async-safe via asyncio.Lock

import asyncio
import hashlib
import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


@dataclass
class CacheEntry:
    """A single cached result."""
    cache_key: str
    tool_name: str
    args_hash: str
    result: Any
    created_at: float = field(default_factory=time.time)
    ttl_seconds: float = 300.0  # Default 5 minutes
    hit_count: int = 0
    source_path_id: str = ""
    
    @property
    def is_expired(self) -> bool:
        return (time.time() - self.created_at) > self.ttl_seconds
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "cache_key": self.cache_key,
            "tool_name": self.tool_name,
            "args_hash": self.args_hash,
            "created_at": self.created_at,
            "ttl_seconds": self.ttl_seconds,
            "hit_count": self.hit_count,
            "source_path_id": self.source_path_id,
            "is_expired": self.is_expired,
        }


def _normalize_args(args: Dict[str, Any]) -> str:
    """Normalize tool arguments for consistent hashing."""
    # Sort keys, normalize whitespace in string values
    normalized = {}
    for k, v in sorted(args.items()):
        if isinstance(v, str):
            v = " ".join(v.lower().split())
        normalized[k] = v
    return json.dumps(normalized, sort_keys=True, ensure_ascii=False)


def _make_cache_key(tool_name: str, args: Dict[str, Any]) -> str:
    """Generate a content-addressed cache key."""
    normalized = _normalize_args(args)
    content = f"{tool_name}:{normalized}"
    return hashlib.sha256(content.encode()).hexdigest()[:16]


class ResultCache:
    """
    EA-306: Cross-path result cache.
    
    Caches tool call results so that multiple paths exploring the same
    task don't repeat identical API calls (search queries, web scrapes, etc.).
    
    Usage:
        cache = ResultCache()
        
        # Check cache before making a tool call
        result = await cache.get("web_search", {"query": "GDP 2024"})
        if result is not None:
            # Cache hit — use cached result
            pass
        else:
            # Cache miss — make the actual call
            result = await actual_tool_call(...)
            await cache.put("web_search", {"query": "GDP 2024"}, result, path_id="path_0")
    """
    
    def __init__(
        self,
        default_ttl: float = 300.0,
        max_entries: int = 200,
        enabled: bool = True,
    ):
        """
        Args:
            default_ttl: Default time-to-live in seconds for cached entries.
            max_entries: Maximum cache size (LRU eviction).
            enabled: Whether caching is active (can be disabled for testing).
        """
        self._cache: Dict[str, CacheEntry] = {}
        self._lock = asyncio.Lock()
        self._default_ttl = default_ttl
        self._max_entries = max_entries
        self._enabled = enabled
        self._stats = {
            "hits": 0,
            "misses": 0,
            "puts": 0,
            "evictions": 0,
            "expirations": 0,
        }
    
    async def get(
        self,
        tool_name: str,
        args: Dict[str, Any],
    ) -> Optional[Any]:
        """
        Look up a cached result.
        
        Args:
            tool_name: Name of the tool (e.g., "web_search", "scrape_url").
            args: Tool arguments.
        
        Returns:
            Cached result if found and not expired, None otherwise.
        """
        if not self._enabled:
            self._stats["misses"] += 1
            return None
        
        key = _make_cache_key(tool_name, args)
        
        async with self._lock:
            entry = self._cache.get(key)
            
            if entry is None:
                self._stats["misses"] += 1
                return None
            
            if entry.is_expired:
                del self._cache[key]
                self._stats["expirations"] += 1
                self._stats["misses"] += 1
                logger.debug(f"EA-306: Cache expired for {tool_name} (key={key[:8]})")
                return None
            
            entry.hit_count += 1
            self._stats["hits"] += 1
            logger.debug(
                f"EA-306: Cache HIT for {tool_name} (key={key[:8]}, "
                f"hits={entry.hit_count}, source={entry.source_path_id})"
            )
            return entry.result
    
    async def put(
        self,
        tool_name: str,
        args: Dict[str, Any],
        result: Any,
        path_id: str = "",
        ttl: Optional[float] = None,
    ) -> str:
        """
        Store a result in the cache.
        
        Args:
            tool_name: Name of the tool.
            args: Tool arguments.
            result: The result to cache.
            path_id: ID of the path that produced this result.
            ttl: Time-to-live in seconds (uses default if not specified).
        
        Returns:
            The cache key.
        """
        if not self._enabled:
            return ""
        
        key = _make_cache_key(tool_name, args)
        
        async with self._lock:
            # LRU eviction: remove oldest entries if over capacity
            if len(self._cache) >= self._max_entries and key not in self._cache:
                # Find and remove the least recently used (oldest created_at)
                oldest_key = min(self._cache, key=lambda k: self._cache[k].created_at)
                del self._cache[oldest_key]
                self._stats["evictions"] += 1
            
            entry = CacheEntry(
                cache_key=key,
                tool_name=tool_name,
                args_hash=hashlib.sha256(
                    _normalize_args(args).encode()
                ).hexdigest()[:8],
                result=result,
                ttl_seconds=ttl if ttl is not None else self._default_ttl,
                source_path_id=path_id,
            )
            self._cache[key] = entry
            self._stats["puts"] += 1
            
            logger.debug(
                f"EA-306: Cached {tool_name} result (key={key[:8]}, "
                f"path={path_id}, ttl={entry.ttl_seconds}s)"
            )
            
            return key
    
    async def has(self, tool_name: str, args: Dict[str, Any]) -> bool:
        """Check if a non-expired entry exists without counting as a hit."""
        if not self._enabled:
            return False
        key = _make_cache_key(tool_name, args)
        async with self._lock:
            entry = self._cache.get(key)
            return entry is not None and not entry.is_expired
    
    async def invalidate(self, tool_name: str, args: Dict[str, Any]) -> bool:
        """
        Invalidate a specific cache entry.
        
        Returns:
            True if entry was found and removed, False otherwise.
        """
        key = _make_cache_key(tool_name, args)
        async with self._lock:
            if key in self._cache:
                del self._cache[key]
                return True
            return False
    
    async def invalidate_by_tool(self, tool_name: str) -> int:
        """
        Invalidate all entries for a specific tool.
        
        Returns:
            Number of entries removed.
        """
        async with self._lock:
            keys_to_remove = [
                k for k, v in self._cache.items() if v.tool_name == tool_name
            ]
            for k in keys_to_remove:
                del self._cache[k]
            return len(keys_to_remove)
    
    async def cleanup_expired(self) -> int:
        """
        Remove all expired entries.
        
        Returns:
            Number of entries removed.
        """
        async with self._lock:
            expired_keys = [
                k for k, v in self._cache.items() if v.is_expired
            ]
            for k in expired_keys:
                del self._cache[k]
            self._stats["expirations"] += len(expired_keys)
            return len(expired_keys)
    
    async def get_stats(self) -> Dict[str, Any]:
        """Get cache statistics."""
        async with self._lock:
            total = self._stats["hits"] + self._stats["misses"]
            hit_rate = self._stats["hits"] / total if total > 0 else 0.0
            return {
                **self._stats,
                "current_entries": len(self._cache),
                "max_entries": self._max_entries,
                "hit_rate": round(hit_rate, 4),
                "enabled": self._enabled,
                "default_ttl": self._default_ttl,
            }
    
    async def get_entries_by_tool(self) -> Dict[str, int]:
        """Get count of cached entries grouped by tool name."""
        async with self._lock:
            counts: Dict[str, int] = {}
            for entry in self._cache.values():
                if not entry.is_expired:
                    counts[entry.tool_name] = counts.get(entry.tool_name, 0) + 1
            return counts
    
    async def get_savings_estimate(self) -> Dict[str, Any]:
        """
        Estimate cost savings from cache hits.
        
        Returns:
            Dict with estimated savings metrics.
        """
        async with self._lock:
            total_hits = sum(e.hit_count for e in self._cache.values())
            return {
                "total_cache_hits": total_hits,
                "unique_entries_cached": len(self._cache),
                "estimated_api_calls_saved": total_hits,
            }
    
    async def clear(self) -> None:
        """Clear all cache entries and reset stats."""
        async with self._lock:
            self._cache.clear()
            self._stats = {
                "hits": 0,
                "misses": 0,
                "puts": 0,
                "evictions": 0,
                "expirations": 0,
            }


# Singleton
_global_cache: Optional[ResultCache] = None


def get_result_cache(
    default_ttl: float = 300.0,
    max_entries: int = 200,
) -> ResultCache:
    """Get or create the global ResultCache singleton."""
    global _global_cache
    if _global_cache is None:
        _global_cache = ResultCache(default_ttl=default_ttl, max_entries=max_entries)
    return _global_cache


def reset_result_cache() -> None:
    """Reset the global cache (for testing)."""
    global _global_cache
    _global_cache = None
