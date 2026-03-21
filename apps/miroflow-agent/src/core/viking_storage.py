# Copyright 2026 EvoAgent Contributors
# SPDX-License-Identifier: MIT
"""
Viking Storage — Synchronous write-through interface for OpenViking.

Provides a non-blocking synchronous put() API backed by a daemon thread
that processes writes to OpenViking asynchronously. Failed writes are
retried during idle periods.

Used by ExperienceStore, IslandStore, and DigestStore for write-through
persistence to OpenViking without blocking the main execution path.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import json
import logging
import queue
import threading
from typing import Any, Dict, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from .openviking_context import OpenVikingContext

logger = logging.getLogger(__name__)


class VikingStorageSync:
    """Synchronous interface for OpenViking write-through storage.

    Uses a background daemon thread with its own event loop.
    Callers call put() synchronously — never blocks.
    Failed writes go to retry queue, flushed periodically.
    """

    def __init__(self, viking_context: "OpenVikingContext") -> None:
        self._viking = viking_context
        self._queue: queue.Queue = queue.Queue()
        self._query_queue: queue.Queue = queue.Queue()
        self._failed: list = []  # retry buffer
        self._thread = threading.Thread(target=self._worker, daemon=True)
        self._thread.start()

    def _worker(self) -> None:
        """Background thread: processes write queue and query queue with its own event loop."""
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        while True:
            # Process any pending query requests first (non-blocking)
            self._process_queries(loop)
            try:
                uri, data = self._queue.get(timeout=0.1)
                try:
                    loop.run_until_complete(self._async_put(uri, data))
                except Exception as e:
                    logger.warning(f"Viking write failed for {uri}: {e}")
                    self._failed.append((uri, data))
                self._queue.task_done()
            except queue.Empty:
                # Process retries during idle time
                self._process_retries(loop)

    async def _async_put(self, uri: str, data: dict) -> None:
        """Actual write to OpenViking via save_to_uri."""
        await self._viking.save_to_uri(uri, data)

    def put(self, uri: str, data: dict) -> None:
        """Synchronous, non-blocking. Enqueues for background write."""
        self._queue.put((uri, data))

    def _process_retries(self, loop: asyncio.AbstractEventLoop) -> None:
        """Retry failed writes during idle periods."""
        if not self._failed:
            return
        retries = self._failed[:]
        self._failed.clear()
        for uri, data in retries:
            try:
                loop.run_until_complete(self._async_put(uri, data))
            except Exception:
                self._failed.append((uri, data))

    def query_sync(self, coro: Any) -> Any:
        """Submit an async coroutine and block until result.  For read operations.

        The coroutine is executed on the background worker's event loop.
        Raises TimeoutError if no result within 5 seconds.
        """
        future: concurrent.futures.Future = concurrent.futures.Future()
        self._query_queue.put((coro, future))
        return future.result(timeout=5.0)

    def _process_queries(self, loop: asyncio.AbstractEventLoop) -> None:
        """Drain pending query requests (non-blocking)."""
        while True:
            try:
                coro, future = self._query_queue.get_nowait()
            except queue.Empty:
                break
            try:
                result = loop.run_until_complete(coro)
                future.set_result(result)
            except Exception as e:
                future.set_exception(e)

    @property
    def pending_count(self) -> int:
        """Number of items still queued or in retry buffer."""
        return self._queue.qsize() + len(self._failed)
