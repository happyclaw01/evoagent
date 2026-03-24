# Copyright 2026 EvoAgent Contributors
# SPDX-License-Identifier: MIT
"""
Integration tests for Inline Step Trace (IST) module.

IST-409: TracingToolWrapper in real pipeline
IST-410: Full trace → digest → store round trip
IST-413: DigestStore concurrent read/write
"""

import asyncio
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

from src.core.inline_step_trace import (
    ConclusionExtractor,
    DigestStore,
    PathDigest,
    StepTrace,
    StepTraceCollector,
    TaskDigestBundle,
    TracingToolWrapper,
    TRACE_INSTRUCTION,
    extract_key_info,
)


class TestIST409_TracingToolWrapperPipeline(unittest.TestCase):
    """IST-409: TracingToolWrapper in real pipeline.

    Verify that TracingToolWrapper correctly wraps a ToolManager,
    transparently proxies calls, and records traces to the collector.
    """

    def test_wrapper_proxies_attributes(self):
        """Wrapper should proxy attributes from the underlying tool manager."""
        mock_tm = MagicMock()
        mock_tm.some_attribute = "test_value"
        mock_tm.some_method = MagicMock(return_value=42)

        collector = StepTraceCollector(
            task_id="test_task", path_index=0, strategy_name="test"
        )
        wrapper = TracingToolWrapper(mock_tm, collector)

        self.assertEqual(wrapper.some_attribute, "test_value")
        self.assertEqual(wrapper.some_method(), 42)

    def test_wrapper_records_trace_on_execute(self):
        """execute_tool should record a trace in the collector."""

        async def run():
            mock_tm = MagicMock()
            mock_tm.execute_tool_call = AsyncMock(return_value="search result: Paris is capital")

            collector = StepTraceCollector(
                task_id="test_task", path_index=0, strategy_name="breadth_first"
            )
            wrapper = TracingToolWrapper(mock_tm, collector)

            result = await wrapper.execute_tool_call("server", 
                "web_search", {"query": "capital of France"}
            )

            # Tool result should be passed through unchanged (DD-007)
            self.assertEqual(result, "search result: Paris is capital")

            # Collector should have recorded one step
            self.assertEqual(collector.step_count, 1)

            # Check the pending/recorded trace
            traces = collector.traces
            # The trace is pending (not finalized), so it might be in _pending
            # After finalize, all pending traces get flushed
            digest = collector.finalize(answer="Paris", final_confidence="high")
            self.assertEqual(digest.total_steps, 1)
            self.assertEqual(digest.traces[0].action, "search")
            self.assertIn("capital of France", digest.traces[0].query)
            self.assertIsNotNone(digest.traces[0].key_info)

        asyncio.run(run())

    def test_wrapper_multiple_tool_calls(self):
        """Multiple tool calls should all be recorded."""

        async def run():
            mock_tm = MagicMock()
            mock_tm.execute_tool_call = AsyncMock(
                side_effect=["result1", "result2", "result3"]
            )

            collector = StepTraceCollector(
                task_id="multi_test", path_index=1, strategy_name="depth_first"
            )
            wrapper = TracingToolWrapper(mock_tm, collector)

            await wrapper.execute_tool_call("server", "web_search", {"query": "q1"})
            await wrapper.execute_tool_call("server", "browse_webpage", {"url": "http://example.com"})
            await wrapper.execute_tool_call("server", "python_exec", {"code": "print(42)"})

            digest = collector.finalize(answer="42")
            self.assertEqual(digest.total_steps, 3)
            self.assertEqual(digest.traces[0].action, "search")
            self.assertEqual(digest.traces[1].action, "browse")
            self.assertEqual(digest.traces[2].action, "calculate")

        asyncio.run(run())

    def test_wrapper_with_conclusion_matching(self):
        """Conclusions should be matched to pending tool traces."""

        async def run():
            mock_tm = MagicMock()
            mock_tm.execute_tool_call = AsyncMock(return_value="data found")

            collector = StepTraceCollector(
                task_id="conc_test", path_index=0, strategy_name="test"
            )
            wrapper = TracingToolWrapper(mock_tm, collector)

            await wrapper.execute_tool_call("server", "web_search", {"query": "test"})
            # Simulate agent outputting a conclusion after tool result
            collector.record_conclusion("Found relevant data about topic", confidence=0.7)

            digest = collector.finalize(answer="answer")
            self.assertEqual(digest.traces[0].conclusion, "Found relevant data about topic")
            self.assertAlmostEqual(digest.traces[0].confidence, 0.7)

        asyncio.run(run())

    def test_trace_instruction_content(self):
        """TRACE_INSTRUCTION should contain expected protocol elements."""
        self.assertIn("<conclusion>", TRACE_INSTRUCTION)
        self.assertIn("<confidence>", TRACE_INSTRUCTION)
        self.assertIn("tool use", TRACE_INSTRUCTION.lower())


class TestIST410_TraceDigestStoreRoundTrip(unittest.TestCase):
    """IST-410: Full trace → digest → store round trip.

    Verify end-to-end: tool calls → collector → finalize → DigestStore → reload.
    """

    def test_full_round_trip(self):
        """Full pipeline: record traces → finalize → save → load → verify."""

        async def run():
            with tempfile.TemporaryDirectory() as tmpdir:
                # Phase 1: Record traces
                collector = StepTraceCollector(
                    task_id="roundtrip_task",
                    path_index=0,
                    island_id="信息追踪",
                    strategy_name="news_expert_v1",
                )

                mock_tm = MagicMock()
                mock_tm.execute_tool_call = AsyncMock(
                    side_effect=[
                        [{"title": "Breaking News", "snippet": "Important finding"}],
                        {"title": "Article", "content": "Detailed analysis of the topic"},
                        "42",
                    ]
                )
                wrapper = TracingToolWrapper(mock_tm, collector)

                await wrapper.execute_tool_call("server", "web_search", {"query": "test query"})
                collector.record_conclusion("Found relevant news article", confidence=0.6)

                await wrapper.execute_tool_call("server", "browse_webpage", {"url": "http://example.com"})
                collector.record_conclusion("Article confirms initial hypothesis", confidence=0.8)

                await wrapper.execute_tool_call("server", "python_exec", {"code": "print(42)"})
                collector.record_conclusion("Computation verified the number", confidence=0.9)

                collector.record_tokens(1500)

                # Phase 2: Finalize
                digest = collector.finalize(answer="42", final_confidence="high")
                self.assertIsInstance(digest, PathDigest)
                self.assertEqual(digest.task_id, "roundtrip_task")
                self.assertEqual(digest.path_index, 0)
                self.assertEqual(digest.answer, "42")
                self.assertEqual(digest.confidence, "high")
                self.assertEqual(digest.total_steps, 3)
                self.assertEqual(digest.island_id, "信息追踪")
                self.assertEqual(digest.strategy_name, "news_expert_v1")
                self.assertGreater(len(digest.reasoning_chain), 0)
                self.assertGreater(len(digest.key_findings), 0)
                self.assertEqual(len(digest.traces), 3)

                # Phase 3: Save to DigestStore
                store = DigestStore(base_dir=tmpdir)
                await store.save_path_digest(digest)

                # Verify file was created
                digest_file = Path(tmpdir) / "roundtrip_task_path0.json"
                self.assertTrue(digest_file.exists())

                # Phase 4: Reload and verify
                loaded_l0 = await store.load_path_digest("roundtrip_task", 0, depth="l0")
                self.assertIsNotNone(loaded_l0)
                self.assertEqual(loaded_l0["answer"], "42")
                self.assertEqual(loaded_l0["confidence"], "high")
                self.assertEqual(loaded_l0["total_steps"], 3)

                loaded_l1 = await store.load_path_digest("roundtrip_task", 0, depth="l1")
                self.assertIsNotNone(loaded_l1)
                self.assertEqual(loaded_l1["answer"], "42")
                self.assertIn("reasoning_chain", loaded_l1)
                self.assertIn("key_findings", loaded_l1)
                self.assertIn("traces", loaded_l1)
                self.assertEqual(len(loaded_l1["traces"]), 3)

                loaded_l2 = await store.load_path_digest("roundtrip_task", 0, depth="l2")
                self.assertIsNotNone(loaded_l2)
                self.assertIn("total_tokens", loaded_l2)
                self.assertIn("start_time", loaded_l2)

        asyncio.run(run())

    def test_task_bundle_round_trip(self):
        """Save and load TaskDigestBundle."""

        async def run():
            with tempfile.TemporaryDirectory() as tmpdir:
                # Create multiple path digests
                digests = []
                for i in range(3):
                    collector = StepTraceCollector(
                        task_id="bundle_test",
                        path_index=i,
                        strategy_name=f"strategy_{i}",
                    )
                    mock_tm = MagicMock()
                    mock_tm.execute_tool_call = AsyncMock(return_value="result")
                    wrapper = TracingToolWrapper(mock_tm, collector)
                    await wrapper.execute_tool_call("server", "web_search", {"query": f"query_{i}"})
                    digest = collector.finalize(
                        answer=f"answer_{i}", final_confidence="medium"
                    )
                    digests.append(digest)

                # Create bundle
                bundle = TaskDigestBundle(
                    task_id="bundle_test",
                    question="What is the meaning of life?",
                    question_type="science",
                    ground_truth="42",
                    path_digests=digests,
                    voted_answer="answer_0",
                    vote_method="weighted_majority",
                    was_correct=True,
                )

                store = DigestStore(base_dir=tmpdir)
                await store.save_task_bundle(bundle)

                # Verify file exists
                bundle_file = Path(tmpdir) / "bundle_test_bundle.json"
                self.assertTrue(bundle_file.exists())

                # Load comparison view
                view = await store.load_task_comparison("bundle_test")
                self.assertIsNotNone(view)
                self.assertIn("meaning of life", view)
                self.assertIn("answer_0", view)

        asyncio.run(run())

    def test_nonexistent_digest_returns_none(self):
        """Loading nonexistent digest should return None."""

        async def run():
            with tempfile.TemporaryDirectory() as tmpdir:
                store = DigestStore(base_dir=tmpdir)
                result = await store.load_path_digest("nonexistent", 0)
                self.assertIsNone(result)

        asyncio.run(run())


class TestIST413_DigestStoreConcurrency(unittest.TestCase):
    """IST-413: DigestStore concurrent read/write.

    Verify that DigestStore handles concurrent operations safely.
    """

    def test_concurrent_writes(self):
        """Multiple concurrent writes should not corrupt data."""

        async def run():
            with tempfile.TemporaryDirectory() as tmpdir:
                store = DigestStore(base_dir=tmpdir)

                async def write_digest(path_index: int):
                    collector = StepTraceCollector(
                        task_id="concurrent_test",
                        path_index=path_index,
                        strategy_name=f"strategy_{path_index}",
                    )
                    mock_tm = MagicMock()
                    mock_tm.execute_tool_call = AsyncMock(return_value=f"result_{path_index}")
                    wrapper = TracingToolWrapper(mock_tm, collector)
                    await wrapper.execute_tool_call("server", "web_search", {"query": f"q_{path_index}"})
                    digest = collector.finalize(
                        answer=f"answer_{path_index}", final_confidence="medium"
                    )
                    await store.save_path_digest(digest)
                    return digest

                # Write 5 digests concurrently
                digests = await asyncio.gather(
                    *[write_digest(i) for i in range(5)]
                )

                # Verify all were saved correctly
                for i in range(5):
                    loaded = await store.load_path_digest("concurrent_test", i)
                    self.assertIsNotNone(loaded, f"Digest for path {i} not found")
                    self.assertEqual(loaded["answer"], f"answer_{i}")
                    self.assertEqual(loaded["strategy_name"], f"strategy_{i}")

        asyncio.run(run())

    def test_concurrent_read_write(self):
        """Concurrent reads and writes should not interfere."""

        async def run():
            with tempfile.TemporaryDirectory() as tmpdir:
                store = DigestStore(base_dir=tmpdir)

                # Pre-write some digests
                for i in range(3):
                    collector = StepTraceCollector(
                        task_id="rw_test", path_index=i, strategy_name=f"s_{i}"
                    )
                    mock_tm = MagicMock()
                    mock_tm.execute_tool_call = AsyncMock(return_value="r")
                    wrapper = TracingToolWrapper(mock_tm, collector)
                    await wrapper.execute_tool_call("server", "web_search", {"query": "q"})
                    digest = collector.finalize(answer=f"a_{i}")
                    await store.save_path_digest(digest)

                # Concurrent: read existing + write new
                async def read_digest(idx: int):
                    return await store.load_path_digest("rw_test", idx)

                async def write_new_digest(idx: int):
                    collector = StepTraceCollector(
                        task_id="rw_test", path_index=idx, strategy_name=f"s_{idx}"
                    )
                    mock_tm = MagicMock()
                    mock_tm.execute_tool_call = AsyncMock(return_value="r")
                    wrapper = TracingToolWrapper(mock_tm, collector)
                    await wrapper.execute_tool_call("server", "web_search", {"query": "q"})
                    digest = collector.finalize(answer=f"a_{idx}")
                    await store.save_path_digest(digest)

                results = await asyncio.gather(
                    read_digest(0),
                    read_digest(1),
                    write_new_digest(5),
                    write_new_digest(6),
                    read_digest(2),
                )

                # Reads should return correct data
                self.assertEqual(results[0]["answer"], "a_0")
                self.assertEqual(results[1]["answer"], "a_1")
                self.assertEqual(results[4]["answer"], "a_2")

                # New writes should be persisted
                loaded_5 = await store.load_path_digest("rw_test", 5)
                loaded_6 = await store.load_path_digest("rw_test", 6)
                self.assertIsNotNone(loaded_5)
                self.assertIsNotNone(loaded_6)
                self.assertEqual(loaded_5["answer"], "a_5")
                self.assertEqual(loaded_6["answer"], "a_6")

        asyncio.run(run())

    def test_concurrent_bundle_and_digest_writes(self):
        """Writing bundle and individual digests concurrently."""

        async def run():
            with tempfile.TemporaryDirectory() as tmpdir:
                store = DigestStore(base_dir=tmpdir)

                digests = []
                for i in range(3):
                    collector = StepTraceCollector(
                        task_id="mixed_test", path_index=i, strategy_name=f"s_{i}"
                    )
                    mock_tm = MagicMock()
                    mock_tm.execute_tool_call = AsyncMock(return_value="r")
                    wrapper = TracingToolWrapper(mock_tm, collector)
                    await wrapper.execute_tool_call("server", "web_search", {"query": "q"})
                    digest = collector.finalize(answer=f"a_{i}")
                    digests.append(digest)

                bundle = TaskDigestBundle(
                    task_id="mixed_test",
                    question="test question",
                    path_digests=digests,
                    voted_answer="a_0",
                )

                # Concurrent: save all digests + bundle
                await asyncio.gather(
                    store.save_path_digest(digests[0]),
                    store.save_path_digest(digests[1]),
                    store.save_path_digest(digests[2]),
                    store.save_task_bundle(bundle),
                )

                # Verify all saved
                for i in range(3):
                    loaded = await store.load_path_digest("mixed_test", i)
                    self.assertIsNotNone(loaded)

                view = await store.load_task_comparison("mixed_test")
                self.assertIsNotNone(view)

        asyncio.run(run())


class TestConclusionExtractor(unittest.TestCase):
    """Additional tests for ConclusionExtractor parsing."""

    def test_extract_both_tags(self):
        text = "some text <conclusion>Found the key data</conclusion> more <confidence>0.85</confidence>"
        conclusion, confidence = ConclusionExtractor.extract(text)
        self.assertEqual(conclusion, "Found the key data")
        self.assertAlmostEqual(confidence, 0.85)

    def test_clean_tags(self):
        text = "Hello <conclusion>test</conclusion> world <confidence>0.5</confidence> end"
        cleaned = ConclusionExtractor.clean_tags(text)
        self.assertNotIn("<conclusion>", cleaned)
        self.assertNotIn("<confidence>", cleaned)
        self.assertIn("Hello", cleaned)
        self.assertIn("world", cleaned)

    def test_extract_missing_tags(self):
        conclusion, confidence = ConclusionExtractor.extract("no tags here")
        self.assertIsNone(conclusion)
        self.assertIsNone(confidence)


if __name__ == "__main__":
    unittest.main()
