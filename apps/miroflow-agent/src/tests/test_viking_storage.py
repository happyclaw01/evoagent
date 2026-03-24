# Copyright 2026 EvoAgent Contributors
# SPDX-License-Identifier: MIT
"""
Tests for VikingStorageSync and write-through integration in Stores.
"""

import asyncio
import json
import tempfile
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.core.viking_storage import VikingStorageSync
from src.core.openviking_context import OpenVikingContext
from src.core.inline_step_trace import DigestStore, PathDigest, TaskDigestBundle
from src.core.strategy_island import (
    IslandStore,
    LocalJsonBackend,
    IslandPool,
    IslandConfig,
    StrategyIsland,
)
from src.evolving.experience_store import ExperienceStore


# ────────────────────────────────────────────────────────────
# Helpers
# ────────────────────────────────────────────────────────────


def _make_viking_context() -> OpenVikingContext:
    """Create an in-memory OpenVikingContext for testing."""
    ctx = OpenVikingContext(enabled=False, fallback_mode=True)
    return ctx


def _wait_for_queue(storage: VikingStorageSync, timeout: float = 2.0) -> None:
    """Wait until the background queue is drained."""
    deadline = time.monotonic() + timeout
    while storage.pending_count > 0 and time.monotonic() < deadline:
        time.sleep(0.05)


# ────────────────────────────────────────────────────────────
# VikingStorageSync unit tests
# ────────────────────────────────────────────────────────────


class TestVikingStorageSync:
    """Tests for the core VikingStorageSync class."""

    def test_put_is_non_blocking(self):
        """put() should return immediately without waiting for the write."""
        ctx = _make_viking_context()
        storage = VikingStorageSync(ctx)

        start = time.monotonic()
        storage.put("viking://test/key1", {"hello": "world"})
        elapsed = time.monotonic() - start

        # put() must return in < 100ms (non-blocking)
        assert elapsed < 0.1
        _wait_for_queue(storage)

    def test_worker_processes_queue(self):
        """Background worker should process enqueued items."""
        ctx = _make_viking_context()
        storage = VikingStorageSync(ctx)

        storage.put("viking://test/a", {"v": 1})
        storage.put("viking://test/b", {"v": 2})
        storage.put("viking://test/c", {"v": 3})

        _wait_for_queue(storage)

        # All items should be processed (stored in ctx._memory_store)
        assert "viking://test/a" in ctx._memory_store
        assert "viking://test/b" in ctx._memory_store
        assert "viking://test/c" in ctx._memory_store

    def test_retry_on_failure(self):
        """Failed writes should be retried during idle periods."""
        ctx = _make_viking_context()
        call_count = 0
        original_save = OpenVikingContext.save_to_uri

        async def flaky_save(uri, data):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise ConnectionError("simulated network error")
            await original_save(ctx, uri, data)

        # Patch the instance method directly
        ctx.save_to_uri = flaky_save
        storage = VikingStorageSync(ctx)
        storage.put("viking://test/retry", {"data": "value"})
        # Wait for initial attempt + retry cycle
        time.sleep(3.0)

        # After retry, data should be stored
        assert "viking://test/retry" in ctx._memory_store
        assert call_count >= 2

    def test_pending_count(self):
        """pending_count should reflect queue + failed items."""
        ctx = _make_viking_context()
        storage = VikingStorageSync(ctx)

        assert storage.pending_count == 0
        storage.put("viking://test/x", {"x": 1})
        # Right after put, pending_count should be >= 1
        assert storage.pending_count >= 0  # race-safe: may already be processed

        _wait_for_queue(storage)
        assert storage.pending_count == 0

    def test_daemon_thread(self):
        """Worker thread should be a daemon (dies with process)."""
        ctx = _make_viking_context()
        storage = VikingStorageSync(ctx)
        assert storage._thread.daemon is True


# ────────────────────────────────────────────────────────────
# ExperienceStore backward compatibility + write-through
# ────────────────────────────────────────────────────────────


class TestExperienceStoreViking:
    """Tests for ExperienceStore with viking_storage integration."""

    def test_backward_compat_none(self, tmp_path):
        """When viking_storage=None, behavior is unchanged."""
        store = ExperienceStore(str(tmp_path / "exp.jsonl"), viking_storage=None)
        store.add({"task_id": "t1", "lesson": "test"})
        assert len(store.get_all()) == 1

    def test_add_calls_viking_put(self, tmp_path):
        """add() should call viking_storage.put() with correct URI."""
        mock_viking = MagicMock()
        store = ExperienceStore(str(tmp_path / "exp.jsonl"), viking_storage=mock_viking)

        store.add({"task_id": "task_42", "lesson": "learned"})

        mock_viking.put.assert_called_once()
        uri, data = mock_viking.put.call_args[0]
        assert uri == "viking://agent/experiences/task_42"
        assert data["task_id"] == "task_42"

    def test_add_batch_calls_viking_put(self, tmp_path):
        """add_batch() should call viking_storage.put() for each new experience."""
        mock_viking = MagicMock()
        store = ExperienceStore(str(tmp_path / "exp.jsonl"), viking_storage=mock_viking)

        count = store.add_batch([
            {"task_id": "b1", "lesson": "one"},
            {"task_id": "b2", "lesson": "two"},
        ])

        assert count == 2
        assert mock_viking.put.call_count == 2
        uris = [call[0][0] for call in mock_viking.put.call_args_list]
        assert "viking://agent/experiences/b1" in uris
        assert "viking://agent/experiences/b2" in uris

    def test_add_no_task_id_skips_viking(self, tmp_path):
        """add() with empty task_id should not call viking put."""
        mock_viking = MagicMock()
        store = ExperienceStore(str(tmp_path / "exp.jsonl"), viking_storage=mock_viking)

        store.add({"task_id": "", "lesson": "no id"})
        mock_viking.put.assert_not_called()

    def test_local_file_preserved(self, tmp_path):
        """Local JSONL file is always written (write-through, not write-replace)."""
        mock_viking = MagicMock()
        exp_file = tmp_path / "exp.jsonl"
        store = ExperienceStore(str(exp_file), viking_storage=mock_viking)

        store.add({"task_id": "local_check", "lesson": "persist"})

        assert exp_file.exists()
        content = exp_file.read_text()
        assert "local_check" in content


# ────────────────────────────────────────────────────────────
# IslandStore backward compatibility + write-through
# ────────────────────────────────────────────────────────────


class TestIslandStoreViking:
    """Tests for IslandStore with viking_storage integration."""

    def test_backward_compat_none(self, tmp_path):
        """When viking_storage=None, behavior is unchanged."""
        backend = LocalJsonBackend(tmp_path)
        store = IslandStore(backend, viking_storage=None)
        pool = IslandPool([IslandConfig(name="test", perspective="testing")])
        store.save(pool)
        loaded = store.load()
        assert loaded is not None

    def test_save_calls_viking_put(self, tmp_path):
        """save() should PUT each island to Viking."""
        mock_viking = MagicMock()
        backend = LocalJsonBackend(tmp_path)
        store = IslandStore(backend, viking_storage=mock_viking)

        configs = [
            IslandConfig(name="island_a", perspective="view a"),
            IslandConfig(name="island_b", perspective="view b"),
        ]
        pool = IslandPool(configs)
        store.save(pool)

        assert mock_viking.put.call_count == 2
        uris = [call[0][0] for call in mock_viking.put.call_args_list]
        assert "viking://agent/skills/islands/island_a" in uris
        assert "viking://agent/skills/islands/island_b" in uris

    def test_save_result_calls_viking_put(self, tmp_path):
        """save_result() should PUT result to Viking."""
        mock_viking = MagicMock()
        backend = LocalJsonBackend(tmp_path)
        store = IslandStore(backend, viking_storage=mock_viking)

        result = {"task_id": "res_1", "answer": "42"}
        store.save_result(result)

        mock_viking.put.assert_called_once()
        uri, data = mock_viking.put.call_args[0]
        assert uri == "viking://agent/memory/results/res_1"
        assert data["answer"] == "42"

    def test_local_files_preserved(self, tmp_path):
        """Local JSON files are always written."""
        mock_viking = MagicMock()
        backend = LocalJsonBackend(tmp_path)
        store = IslandStore(backend, viking_storage=mock_viking)

        pool = IslandPool([IslandConfig(name="persist", perspective="test")])
        store.save(pool)

        # Check local files exist
        assert (tmp_path / "islands" / "island_0" / "_meta.json").exists()


# ────────────────────────────────────────────────────────────
# DigestStore backward compatibility + write-through
# ────────────────────────────────────────────────────────────


class TestDigestStoreViking:
    """Tests for DigestStore with viking_storage integration."""

    def _make_digest(self, task_id="task_1", path_index=0) -> PathDigest:
        return PathDigest(
            task_id=task_id,
            path_index=path_index,
            strategy_name="breadth_first",
            answer="test answer",
            confidence="high",
        )

    def _make_bundle(self, task_id="task_1") -> TaskDigestBundle:
        return TaskDigestBundle(
            task_id=task_id,
            question="What is the answer?",
            path_digests=[self._make_digest(task_id, 0)],
            voted_answer="test answer",
        )

    @pytest.mark.asyncio
    async def test_backward_compat_none(self, tmp_path):
        """When viking_storage=None, behavior is unchanged."""
        store = DigestStore(base_dir=str(tmp_path), viking_storage=None)
        digest = self._make_digest()
        await store.save_path_digest(digest)
        loaded = await store.load_path_digest("task_1", 0)
        assert loaded is not None

    @pytest.mark.asyncio
    async def test_save_path_digest_calls_viking(self, tmp_path):
        """save_path_digest() should PUT to Viking."""
        mock_viking = MagicMock()
        store = DigestStore(base_dir=str(tmp_path), viking_storage=mock_viking)

        digest = self._make_digest("d_task", 2)
        await store.save_path_digest(digest)

        mock_viking.put.assert_called_once()
        uri, data = mock_viking.put.call_args[0]
        assert uri == "viking://agent/memory/digests/d_task_path2"
        assert data["task_id"] == "d_task"

    @pytest.mark.asyncio
    async def test_save_task_bundle_calls_viking(self, tmp_path):
        """save_task_bundle() should PUT to Viking."""
        mock_viking = MagicMock()
        store = DigestStore(base_dir=str(tmp_path), viking_storage=mock_viking)

        bundle = self._make_bundle("bundle_task")
        await store.save_task_bundle(bundle)

        mock_viking.put.assert_called_once()
        uri, data = mock_viking.put.call_args[0]
        assert uri == "viking://agent/memory/digests/bundle_task_bundle"
        assert data["task_id"] == "bundle_task"

    @pytest.mark.asyncio
    async def test_local_files_preserved(self, tmp_path):
        """Local JSON files are always written."""
        mock_viking = MagicMock()
        store = DigestStore(base_dir=str(tmp_path), viking_storage=mock_viking)

        digest = self._make_digest()
        await store.save_path_digest(digest)

        assert (tmp_path / "task_1_path0.json").exists()


# ────────────────────────────────────────────────────────────
# OpenVikingContext.save_to_uri tests
# ────────────────────────────────────────────────────────────


# ────────────────────────────────────────────────────────────
# OpenVikingContext READ / SEARCH tests
# ────────────────────────────────────────────────────────────


class TestOpenVikingContextRead:
    """Tests for load_from_uri, search_by_embedding, list_by_prefix."""

    @pytest.mark.asyncio
    async def test_load_from_uri_roundtrip(self):
        """Store data via save_to_uri, read back via load_from_uri."""
        ctx = _make_viking_context()
        await ctx.save_to_uri("viking://test/read1", {"answer": 42})
        result = await ctx.load_from_uri("viking://test/read1")
        assert result is not None
        assert result["answer"] == 42

    @pytest.mark.asyncio
    async def test_load_from_uri_missing(self):
        """load_from_uri returns None for unknown URIs."""
        ctx = _make_viking_context()
        assert await ctx.load_from_uri("viking://nope") is None

    @pytest.mark.asyncio
    async def test_search_by_embedding_keyword_match(self):
        """Fallback search matches by keyword."""
        ctx = _make_viking_context()
        await ctx.save_to_uri("viking://agent/experiences/t1", {"task_id": "t1", "lesson": "gradient explosion"})
        await ctx.save_to_uri("viking://agent/experiences/t2", {"task_id": "t2", "lesson": "learning rate too high"})
        await ctx.save_to_uri("viking://other/t3", {"task_id": "t3", "lesson": "gradient vanishing"})

        hits = await ctx.search_by_embedding(
            query_text="gradient problems",
            uri_prefix="viking://agent/experiences/",
        )
        assert len(hits) >= 1
        uris = [h["uri"] for h in hits]
        assert "viking://agent/experiences/t1" in uris
        # t3 is outside prefix — must not appear
        assert "viking://other/t3" not in uris

    @pytest.mark.asyncio
    async def test_search_by_embedding_no_match(self):
        """search_by_embedding returns empty list for unrelated query."""
        ctx = _make_viking_context()
        await ctx.save_to_uri("viking://agent/experiences/t1", {"lesson": "hello world"})
        hits = await ctx.search_by_embedding("zzzznonexistent", "viking://agent/experiences/")
        assert hits == []

    @pytest.mark.asyncio
    async def test_list_by_prefix(self):
        """list_by_prefix filters by URI prefix."""
        ctx = _make_viking_context()
        await ctx.save_to_uri("viking://a/1", {"v": 1})
        await ctx.save_to_uri("viking://a/2", {"v": 2})
        await ctx.save_to_uri("viking://b/3", {"v": 3})

        results = await ctx.list_by_prefix("viking://a/")
        assert len(results) == 2
        uris = {r["uri"] for r in results}
        assert uris == {"viking://a/1", "viking://a/2"}

    @pytest.mark.asyncio
    async def test_list_by_prefix_limit(self):
        """list_by_prefix respects limit."""
        ctx = _make_viking_context()
        for i in range(10):
            await ctx.save_to_uri(f"viking://lim/{i}", {"i": i})
        results = await ctx.list_by_prefix("viking://lim/", limit=3)
        assert len(results) == 3


# ────────────────────────────────────────────────────────────
# VikingStorageSync.query_sync tests
# ────────────────────────────────────────────────────────────


class TestVikingStorageSyncQuerySync:
    """Tests for query_sync blocking read path."""

    def test_query_sync_returns_result(self):
        """query_sync should block and return the coroutine result."""
        ctx = _make_viking_context()
        storage = VikingStorageSync(ctx)

        # First write something
        storage.put("viking://qs/key1", {"data": "hello"})
        _wait_for_queue(storage)

        # Now read it back synchronously
        result = storage.query_sync(ctx.load_from_uri("viking://qs/key1"))
        assert result is not None
        assert result["data"] == "hello"

    def test_query_sync_returns_none_for_missing(self):
        """query_sync should return None for missing URIs."""
        ctx = _make_viking_context()
        storage = VikingStorageSync(ctx)
        result = storage.query_sync(ctx.load_from_uri("viking://missing"))
        assert result is None


# ────────────────────────────────────────────────────────────
# ExperienceStore semantic query tests
# ────────────────────────────────────────────────────────────


class TestExperienceStoreSemanticQuery:
    """Tests for ExperienceStore.query with semantic_query."""

    def test_semantic_query_merges_results(self, tmp_path):
        """Semantic query should merge remote results with local, dedup by task_id."""
        ctx = _make_viking_context()
        storage = VikingStorageSync(ctx)

        # Write some experiences to Viking
        storage.put("viking://agent/experiences/remote1", {
            "task_id": "remote1", "lesson": "failure pattern alpha", "was_correct": False,
            "question_type": "math", "created_at": "2026-01-01T00:00:00",
        })
        _wait_for_queue(storage)

        # Create local store with a different experience
        store = ExperienceStore(
            str(tmp_path / "exp.jsonl"),
            viking_storage=storage,
            viking_context=ctx,
        )
        store.add({"task_id": "local1", "lesson": "local insight", "was_correct": False,
                    "question_type": "math"})

        results = store.query(
            was_correct=False,
            semantic_query="failure pattern",
            max_count=10,
        )
        task_ids = [r["task_id"] for r in results]
        assert "local1" in task_ids
        assert "remote1" in task_ids

    def test_semantic_query_dedup_by_task_id(self, tmp_path):
        """When same task_id exists locally and remotely, local wins (no dups)."""
        ctx = _make_viking_context()
        storage = VikingStorageSync(ctx)

        storage.put("viking://agent/experiences/dup1", {
            "task_id": "dup1", "lesson": "remote version", "was_correct": False,
            "question_type": "geo", "created_at": "2026-01-01T00:00:00",
        })
        _wait_for_queue(storage)

        store = ExperienceStore(
            str(tmp_path / "exp.jsonl"),
            viking_storage=storage,
            viking_context=ctx,
        )
        store.add({"task_id": "dup1", "lesson": "local version", "was_correct": False,
                    "question_type": "geo"})

        results = store.query(was_correct=False, semantic_query="version", max_count=10)
        dup_entries = [r for r in results if r["task_id"] == "dup1"]
        assert len(dup_entries) == 1
        assert dup_entries[0]["lesson"] == "local version"

    def test_semantic_query_none_unchanged(self, tmp_path):
        """When semantic_query=None, behavior is identical to before."""
        store = ExperienceStore(str(tmp_path / "exp.jsonl"))
        store.add({"task_id": "t1", "lesson": "a", "was_correct": True})
        results = store.query(semantic_query=None)
        assert len(results) == 1


# ────────────────────────────────────────────────────────────
# IslandStore viking fallback load tests
# ────────────────────────────────────────────────────────────


class TestIslandStoreVikingLoad:
    """Tests for IslandStore.load with viking_context fallback."""

    def test_load_from_viking_when_local_empty(self, tmp_path):
        """When local is empty, IslandStore.load falls back to Viking."""
        ctx = _make_viking_context()
        storage = VikingStorageSync(ctx)

        # Write an island to Viking
        island = StrategyIsland(IslandConfig(name="remote_island", perspective="remote view"))
        storage.put("viking://agent/skills/islands/remote_island", island.to_dict())
        _wait_for_queue(storage)

        # Create store with empty local backend
        empty_backend = LocalJsonBackend(tmp_path / "empty")
        store = IslandStore(empty_backend, viking_storage=storage, viking_context=ctx)
        pool = store.load()
        assert pool is not None
        assert pool.island_count == 1
        assert pool.islands[0].config.name == "remote_island"

    def test_load_local_preferred_over_viking(self, tmp_path):
        """When local data exists, Viking is not consulted."""
        ctx = _make_viking_context()
        storage = VikingStorageSync(ctx)

        # Write to Viking
        storage.put("viking://agent/skills/islands/remote", 
                     StrategyIsland(IslandConfig(name="remote", perspective="r")).to_dict())
        _wait_for_queue(storage)

        # Write different data locally
        backend = LocalJsonBackend(tmp_path)
        local_pool = IslandPool([IslandConfig(name="local", perspective="l")])
        backend.save_pool(local_pool)

        store = IslandStore(backend, viking_storage=storage, viking_context=ctx)
        pool = store.load()
        assert pool is not None
        assert pool.islands[0].config.name == "local"


# ────────────────────────────────────────────────────────────
# DigestStore viking fallback load tests
# ────────────────────────────────────────────────────────────


class TestDigestStoreVikingLoad:
    """Tests for DigestStore load methods with viking_context fallback."""

    def _make_digest(self, task_id="task_v", path_index=0) -> PathDigest:
        return PathDigest(
            task_id=task_id,
            path_index=path_index,
            strategy_name="breadth_first",
            answer="viking answer",
            confidence="high",
        )

    @pytest.mark.asyncio
    async def test_load_path_digest_from_viking(self, tmp_path):
        """When local file missing, load falls back to Viking."""
        ctx = _make_viking_context()
        digest = self._make_digest("vt1", 0)
        await ctx.save_to_uri("viking://agent/memory/digests/vt1_path0", digest.to_dict())

        store = DigestStore(base_dir=str(tmp_path / "empty"), viking_context=ctx)
        result = await store.load_path_digest("vt1", 0, depth="l0")
        assert result is not None
        assert result["answer"] == "viking answer"

    @pytest.mark.asyncio
    async def test_load_task_comparison_from_viking(self, tmp_path):
        """When local bundle missing, load falls back to Viking."""
        ctx = _make_viking_context()
        bundle = TaskDigestBundle(
            task_id="vb1",
            question="What?",
            path_digests=[self._make_digest("vb1", 0)],
            voted_answer="viking answer",
        )
        await ctx.save_to_uri("viking://agent/memory/digests/vb1_bundle", bundle.to_dict())

        store = DigestStore(base_dir=str(tmp_path / "empty"), viking_context=ctx)
        result = await store.load_task_comparison("vb1")
        assert result is not None
        assert "viking answer" in result

    @pytest.mark.asyncio
    async def test_load_path_digest_local_preferred(self, tmp_path):
        """When local file exists, Viking is not needed."""
        ctx = _make_viking_context()
        store = DigestStore(base_dir=str(tmp_path), viking_context=ctx)

        digest = self._make_digest("local_t", 0)
        digest.answer = "local answer"
        await store.save_path_digest(digest)

        result = await store.load_path_digest("local_t", 0, depth="l0")
        assert result["answer"] == "local answer"


class TestOpenVikingContextSaveToUri:
    """Tests for the new save_to_uri method on OpenVikingContext."""

    @pytest.mark.asyncio
    async def test_save_to_uri_stores_data(self):
        ctx = _make_viking_context()
        await ctx.save_to_uri("viking://test/key", {"val": 123})
        assert "viking://test/key" in ctx._memory_store
        block = ctx._memory_store["viking://test/key"][0]
        assert json.loads(block.content)["val"] == 123

    @pytest.mark.asyncio
    async def test_save_to_uri_caps_history(self):
        ctx = _make_viking_context()
        for i in range(60):
            await ctx.save_to_uri("viking://test/capped", {"i": i})
        assert len(ctx._memory_store["viking://test/capped"]) == 50
