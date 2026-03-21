# Copyright (c) 2025 MiroMind
# EA-307: OpenViking Integration
#
# Integration layer for OpenViking Context Database
# Provides: context loading, experience storage, cross-path sharing, memory iteration

import asyncio
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class ContextBlock:
    """A block of context loaded from OpenViking"""
    uri: str
    content: str
    layer: str  # L0, L1, L2
    relevance_score: float = 0.0
    source: str = ""  # memory, resource, skill, discovery


@dataclass
class Discovery:
    """A shared discovery from one path to others"""
    path_id: str
    strategy: str
    uri: str  # URL or file path found
    title: str = ""
    snippet: str = ""
    timestamp: str = ""


class OpenVikingContext:
    """
    EvoAgent's OpenViking Context Layer (EA-307)
    
    Provides:
    - EA-307.2: Context loading (L0/L1) with directory recursive retrieval
    - EA-307.3: Experience storage to Agent Memory
    - EA-307.4: Cross-path discovery sharing
    - EA-307.5: Memory self-iteration
    
    Note: Requires OpenViking server to be running.
    For local development without OpenViking, uses fallback in-memory mode.
    """
    
    def __init__(
        self,
        server_url: str = "http://localhost:8080",
        api_key: str = "",
        enabled: bool = True,
        fallback_mode: bool = True,
    ):
        """
        Initialize OpenViking context layer.
        
        Args:
            server_url: OpenViking server URL
            api_key: API key for authentication
            enabled: Whether to enable OpenViking integration
            fallback_mode: Use in-memory fallback if server unavailable
        """
        self.server_url = server_url
        self.api_key = api_key
        self.enabled = enabled
        self.fallback_mode = fallback_mode
        
        # Fallback in-memory storage (when OpenViking unavailable)
        self._memory_store: Dict[str, List[ContextBlock]] = {}
        self._discovery_store: Dict[str, List[Discovery]] = {}
        
        # Configuration
        self.max_l0_tokens = 100
        self.max_l1_tokens = 2000
        self.max_discoveries = 10
        
        self._client = None
        self._connected = False
    
    async def connect(self) -> bool:
        """Connect to OpenViking server"""
        if not self.enabled:
            logger.info("OpenViking integration disabled, using fallback mode")
            return False
        
        try:
            # Health-check: verify the server is actually reachable
            # trust_env=False bypasses ALL_PROXY/HTTP_PROXY which may block localhost
            import aiohttp
            async with aiohttp.ClientSession(trust_env=False) as session:
                async with session.get(
                    f"{self.server_url}/health",
                    timeout=aiohttp.ClientTimeout(total=5),
                ) as resp:
                    if resp.status == 200:
                        self._connected = True
                        logger.info(f"Connected to OpenViking at {self.server_url}")
                        return True
                    else:
                        raise ConnectionError(f"Health check returned {resp.status}")
        except Exception as e:
            logger.warning(f"Failed to connect to OpenViking at {self.server_url}: {e}. Using fallback mode.")
            if self.fallback_mode:
                self._connected = False
                return False
            raise
    
    async def close(self):
        """Close connection to OpenViking server"""
        if self._client:
            await self._client.close()
        self._connected = False
    
    # ==================== EA-307.2: Context Loader ====================
    
    async def load_task_context(
        self,
        task_description: str,
        strategy_name: str,
        load_depth: str = "L1",
    ) -> List[ContextBlock]:
        """
        Load task-related context from OpenViking.
        
        EA-307.2: Context Loading with layered retrieval
        
        Args:
            task_description: The task to load context for
            strategy_name: Strategy name for personalized context
            load_depth: L0 (summary), L1 (overview), or L2 (full)
        
        Returns:
            List of context blocks ranked by relevance
        """
        if not self._connected:
            # Use fallback: generate synthetic context based on strategy
            return self._get_fallback_context(task_description, strategy_name, load_depth)
        
        try:
            # In production:
            # 1. Intent analysis
            # 2. Directory recursive retrieval
            # 3. Return ranked results
            
            # For now, use fallback
            return self._get_fallback_context(task_description, strategy_name, load_depth)
            
        except Exception as e:
            logger.warning(f"Context loading failed: {e}, using fallback")
            return self._get_fallback_context(task_description, strategy_name, load_depth)
    
    def _get_fallback_context(
        self, 
        task: str, 
        strategy: str, 
        depth: str
    ) -> List[ContextBlock]:
        """Generate fallback context when OpenViking unavailable.
        
        SI-403: Falls back to island/strategy structure when available.
        Tries to load island perspectives and strategy descriptions from IslandPool.
        """
        contexts = []

        # SI-403: Try island/strategy structure first
        try:
            from .strategy_island import IslandPool
            pool = IslandPool()
            for island in pool.islands:
                perspective = island.config.perspective
                contexts.append(ContextBlock(
                    uri=f"viking://island/{island.config.name}/perspective",
                    content=f"[Island: {island.config.name}] {perspective}",
                    layer="L0",
                    relevance_score=0.85,
                    source="island",
                ))
            if contexts:
                # Still include strategy-specific guidance so different strategies
                # produce different context (preserves backward compat)
                strategy_prompts = {
                    "breadth_first": "Prioritize diverse sources and multiple perspectives.",
                    "depth_first": "Focus on authoritative primary sources and thorough analysis.",
                    "lateral_thinking": "Explore unconventional angles and creative solutions.",
                    "verification_heavy": "Verify all facts through cross-referencing.",
                }
                strat_prompt = strategy_prompts.get(strategy, "")
                if strat_prompt:
                    contexts.append(ContextBlock(
                        uri=f"viking://agent/instructions/strategy/{strategy}",
                        content=f"[Strategy: {strategy}] {strat_prompt}",
                        layer="L0",
                        relevance_score=0.9,
                        source="agent",
                    ))
                # Add task format instructions at L1
                if depth in ["L1", "L2"]:
                    contexts.append(ContextBlock(
                        uri="viking://agent/instructions/task_format",
                        content="When answering: 1) Provide clear reasoning, 2) Cite sources when possible, "
                                "3) Acknowledge uncertainty, 4) Use structured format for complex answers.",
                        layer="L1",
                        relevance_score=0.8,
                        source="agent",
                    ))
                return contexts
        except Exception:
            pass  # Fall through to legacy prompts

        # Legacy: Strategy-specific system prompt
        strategy_prompts = {
            "breadth_first": "Prioritize diverse sources and multiple perspectives.",
            "depth_first": "Focus on authoritative primary sources and thorough analysis.",
            "lateral_thinking": "Explore unconventional angles and creative solutions.",
            "verification_heavy": "Verify all facts through cross-referencing.",
        }
        
        system_prompt = strategy_prompts.get(strategy, "Provide accurate and helpful responses.")
        
        # L0: Summary layer
        if depth in ["L0", "L1", "L2"]:
            contexts.append(ContextBlock(
                uri="viking://agent/instructions/strategy",
                content=f"[Strategy: {strategy}] {system_prompt}",
                layer="L0",
                relevance_score=0.9,
                source="agent"
            ))
        
        # L1: Overview layer
        if depth in ["L1", "L2"]:
            contexts.append(ContextBlock(
                uri="viking://agent/instructions/task_format",
                content="When answering: 1) Provide clear reasoning, 2) Cite sources when possible, "
                        "3) Acknowledge uncertainty, 4) Use structured format for complex answers.",
                layer="L1",
                relevance_score=0.8,
                source="agent"
            ))
        
        return contexts
    
    # ==================== EA-307.3: Experience Storage ====================
    
    async def save_path_result(
        self,
        path_id: str,
        strategy: str,
        result: Dict[str, Any],
        success: bool,
    ):
        """
        Save path execution result to Agent Memory.
        
        EA-307.3: Experience Storage
        
        Args:
            path_id: Path identifier
            strategy: Strategy used
            result: Execution result dict
            success: Whether execution succeeded
        """
        if not success:
            return
        
        # Extract key information for memory
        memory_entry = {
            "path_id": path_id,
            "strategy": strategy,
            "answer": result.get("answer", "")[:500],
            "turns": result.get("turns", 0),
            "tool_calls": result.get("tool_calls", [])[:5],  # Limit to 5
            "timestamp": datetime.now().isoformat(),
            "insights": self._extract_insights(result),
        }
        
        # Store in memory
        if path_id not in self._memory_store:
            self._memory_store[path_id] = []
        
        # Add as L1 context block
        block = ContextBlock(
            uri=f"viking://agent/memories/{path_id}",
            content=json.dumps(memory_entry),
            layer="L1",
            relevance_score=0.7,
            source="memory"
        )
        
        # Keep only last 10 memories per path
        self._memory_store[path_id].append(block)
        if len(self._memory_store[path_id]) > 10:
            self._memory_store[path_id] = self._memory_store[path_id][-10:]
        
        logger.info(f"Saved memory for path {path_id}")
    
    def _extract_insights(self, result: Dict) -> List[str]:
        """Extract key insights from execution result"""
        insights = []
        
        # Simple heuristic extraction
        answer = result.get("answer", "")
        if answer:
            # Take first sentence as insight
            sentences = answer.split(".")
            if sentences and len(sentences[0]) > 10:
                insights.append(sentences[0][:200])
        
        return insights
    
    # ==================== EA-307.4: Cross-Path Sharing ====================
    
    async def share_discovery(
        self,
        path_id: str,
        strategy: str,
        discovery: Discovery,
    ):
        """
        Share a discovery with other paths.
        
        EA-307.4: Cross-Path Discovery Sharing
        
        Allows one path to share useful findings (URLs, key info) with others.
        """
        if path_id not in self._discovery_store:
            self._discovery_store[path_id] = []
        
        self._discovery_store[path_id].append(discovery)
        
        # Limit discoveries per path
        if len(self._discovery_store[path_id]) > self.max_discoveries:
            self._discovery_store[path_id] = self._discovery_store[path_id][-self.max_discoveries:]
        
        logger.info(f"Path {path_id} shared discovery: {discovery.uri}")
    
    async def query_shared_discoveries(
        self,
        task: str,
        exclude_path: str,
    ) -> List[Discovery]:
        """
        Query discoveries shared by other paths.
        
        EA-307.4: Query shared discoveries
        
        Args:
            task: Task description for relevance matching
            exclude_path: Path ID to exclude (usually current path)
        
        Returns:
            List of relevant discoveries from other paths
        """
        all_discoveries = []
        
        for pid, discoveries in self._discovery_store.items():
            if pid != exclude_path:
                all_discoveries.extend(discoveries)
        
        # Simple keyword-based relevance filtering
        task_keywords = set(task.lower().split())
        relevant = []
        
        for d in all_discoveries:
            # Check if any keyword matches
            content = f"{d.uri} {d.title} {d.snippet}".lower()
            if any(kw in content for kw in task_keywords if len(kw) > 3):
                relevant.append(d)
        
        return relevant[:self.max_discoveries]
    
    # ==================== EA-307.5: Memory Self-Iteration ====================
    
    async def trigger_memory_iteration(self) -> Dict[str, int]:
        """
        Trigger memory self-iteration process.
        
        EA-307.5: Memory Self-Iteration
        
        Analyzes stored memories and extracts long-term patterns.
        Should be called at end of session.
        
        Returns:
            Summary of iteration results
        """
        total_memories = sum(len(v) for v in self._memory_store.values())
        
        # Extract patterns from memories
        strategy_counts = {}
        for path_id, blocks in self._memory_store.items():
            for block in blocks:
                try:
                    data = json.loads(block.content)
                    strat = data.get("strategy", "unknown")
                    strategy_counts[strat] = strategy_counts.get(strat, 0) + 1
                except:
                    pass
        
        # Find most successful strategy
        best_strategy = max(strategy_counts, key=strategy_counts.get) if strategy_counts else None
        
        iteration_result = {
            "total_memories_processed": total_memories,
            "strategy_distribution": strategy_counts,
            "recommended_strategy": best_strategy,
            "new_long_term_insights": [],  # Would be extracted via LLM in full impl
        }
        
        logger.info(f"Memory iteration complete: {total_memories} memories, "
                   f"recommended: {best_strategy}")
        
        return iteration_result
    
    # ==================== Generic URI Storage ====================

    async def save_to_uri(self, uri: str, data: dict) -> None:
        """Save arbitrary data to a viking:// URI.

        Used by VikingStorageSync for write-through persistence.
        When connected to a real OpenViking server this would perform an HTTP PUT;
        in fallback mode the data is stored in the in-memory store keyed by URI.
        """
        block = ContextBlock(
            uri=uri,
            content=json.dumps(data, ensure_ascii=False),
            layer="L1",
            relevance_score=0.5,
            source="write-through",
        )

        # Key by URI prefix to keep things organized
        if uri not in self._memory_store:
            self._memory_store[uri] = []
        self._memory_store[uri].append(block)

        # Cap per-URI history at 50 entries
        if len(self._memory_store[uri]) > 50:
            self._memory_store[uri] = self._memory_store[uri][-50:]

        logger.debug(f"Saved to URI {uri}")

    # ==================== Read / Search Methods ====================

    async def load_from_uri(self, uri: str) -> Optional[dict]:
        """Load data from a viking:// URI.  Returns the stored dict or None.

        In fallback mode: reads latest entry from _memory_store.
        In real mode: HTTP GET to server (not yet implemented).
        """
        blocks = self._memory_store.get(uri)
        if not blocks:
            return None
        # Return latest entry
        try:
            return json.loads(blocks[-1].content)
        except (json.JSONDecodeError, IndexError):
            return None

    async def search_by_embedding(
        self,
        query_text: str,
        uri_prefix: str,
        max_results: int = 10,
    ) -> List[dict]:
        """Semantic search using embedding API.

        Args:
            query_text: Natural language query to embed and search
            uri_prefix: Filter results to URIs starting with this prefix
            max_results: Max results to return

        Returns:
            List of dicts with 'uri' and 'data' keys, sorted by relevance
            (most relevant first).
        """
        if not self._connected:
            return self._fallback_keyword_search(query_text, uri_prefix, max_results)

        # Real mode: POST to server embedding endpoint (future)
        # For now, fallback
        return self._fallback_keyword_search(query_text, uri_prefix, max_results)

    async def list_by_prefix(self, uri_prefix: str, limit: int = 100) -> List[dict]:
        """List all entries under a URI prefix.

        Returns list of dicts with 'uri' and 'data' keys.
        """
        results: List[dict] = []
        for uri, blocks in self._memory_store.items():
            if uri.startswith(uri_prefix) and blocks:
                try:
                    data = json.loads(blocks[-1].content)
                    results.append({"uri": uri, "data": data})
                except (json.JSONDecodeError, IndexError):
                    continue
            if len(results) >= limit:
                break
        return results

    def _fallback_keyword_search(
        self,
        query_text: str,
        uri_prefix: str,
        max_results: int,
    ) -> List[dict]:
        """Simple keyword matching on _memory_store content (fallback mode)."""
        keywords = [w.lower() for w in query_text.split() if len(w) > 2]
        if not keywords:
            return []

        scored: List[tuple] = []
        for uri, blocks in self._memory_store.items():
            if not uri.startswith(uri_prefix) or not blocks:
                continue
            try:
                content_str = blocks[-1].content.lower()
                hits = sum(1 for kw in keywords if kw in content_str)
                if hits > 0:
                    data = json.loads(blocks[-1].content)
                    scored.append((hits, uri, data))
            except (json.JSONDecodeError, IndexError):
                continue

        scored.sort(key=lambda x: x[0], reverse=True)
        return [{"uri": item[1], "data": item[2]} for item in scored[:max_results]]

    # ==================== Utility Methods ====================
    
    def get_statistics(self) -> Dict[str, Any]:
        """Get current statistics"""
        return {
            "connected": self._connected,
            "enabled": self.enabled,
            "total_memories": sum(len(v) for v in self._memory_store.values()),
            "total_discoveries": sum(len(v) for v in self._discovery_store.values()),
            "paths_with_memory": len(self._memory_store),
            "paths_with_discoveries": len(self._discovery_store),
        }


def create_openviking_context(config: Dict[str, Any]) -> OpenVikingContext:
    """Factory function to create OpenViking context from config"""
    ov_config = config.get("openviking", {})
    
    return OpenVikingContext(
        server_url=ov_config.get("server_url", "http://localhost:8080"),
        api_key=ov_config.get("api_key", ""),
        enabled=ov_config.get("enabled", True),
        fallback_mode=ov_config.get("fallback_mode", True),
    )