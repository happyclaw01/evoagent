# Copyright 2026 EvoAgent Contributors
# SPDX-License-Identifier: MIT
"""
Tests for Inline Step Trace (IST) module.

Covers:
  IST-401: StepTrace 数据结构 (创建、序列化、反序列化)
  IST-402: PathDigest 三层输出 (L0/L1/L2 字段正确性)
  IST-403: ConclusionExtractor (标准提取 / 无标签 / 畸形标签 / 标签移除)
  IST-404: TracingToolWrapper (4 种 key_info 提取策略 + 兜底)
  IST-405: StepTraceCollector (记录 → 补填 → finalize → 汇总)
  IST-406: DigestStore 读写 (保存 / 加载 / 层级过滤 / 文件不存在)
  IST-407: 集成测试 — 完整单路径 trace
  IST-408: 集成测试 — 多路径 bundle + 对比视图
"""

import asyncio
import json
import os
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.core.inline_step_trace import (
    TOOL_ACTION_MAP,
    TRACE_INSTRUCTION,
    ConclusionExtractor,
    DigestStore,
    PathDigest,
    StepTrace,
    StepTraceCollector,
    TaskDigestBundle,
    TracingToolWrapper,
    extract_key_info,
    _extract_key_info_browse,
    _extract_key_info_calculate,
    _extract_key_info_default,
    _extract_key_info_search,
    _extract_query,
)


# ════════════════════════════════════════════════════════════
# IST-401: StepTrace 数据结构
# ════════════════════════════════════════════════════════════


class TestStepTrace:
    """IST-401: StepTrace 创建、序列化、反序列化。"""

    def test_create_minimal(self):
        t = StepTrace(step=1, action="search", query="test query")
        assert t.step == 1
        assert t.action == "search"
        assert t.query == "test query"
        assert t.key_info is None
        assert t.conclusion is None
        assert t.confidence is None

    def test_create_full(self):
        t = StepTrace(
            step=3,
            action="browse",
            query="https://example.com",
            key_info="Example page | content here",
            conclusion="Found relevant info",
            confidence=0.85,
            timestamp=1700000000.0,
            tool_name="browse_webpage",
            tokens_used=150,
        )
        assert t.step == 3
        assert t.confidence == 0.85
        assert t.tokens_used == 150

    def test_to_dict_omits_none(self):
        t = StepTrace(step=1, action="search", query="q")
        d = t.to_dict()
        assert "key_info" not in d
        assert "conclusion" not in d
        assert d["step"] == 1

    def test_to_dict_includes_present(self):
        t = StepTrace(step=1, action="search", query="q", key_info="info", confidence=0.5)
        d = t.to_dict()
        assert d["key_info"] == "info"
        assert d["confidence"] == 0.5

    def test_to_l1_dict_omits_timestamp_tokens(self):
        t = StepTrace(
            step=1, action="search", query="q",
            key_info="info", timestamp=123.0, tokens_used=50,
        )
        d = t.to_l1_dict()
        assert "timestamp" not in d
        assert "tokens_used" not in d
        assert d["key_info"] == "info"

    def test_roundtrip(self):
        t = StepTrace(
            step=2, action="calculate", query="1+1",
            key_info="2", conclusion="Sum is 2", confidence=0.99,
            timestamp=1700000000.0, tool_name="python_exec", tokens_used=10,
        )
        d = t.to_dict()
        t2 = StepTrace.from_dict(d)
        assert t2.step == t.step
        assert t2.action == t.action
        assert t2.key_info == t.key_info
        assert t2.conclusion == t.conclusion
        assert t2.confidence == t.confidence
        assert t2.timestamp == t.timestamp
        assert t2.tool_name == t.tool_name
        assert t2.tokens_used == t.tokens_used


# ════════════════════════════════════════════════════════════
# IST-402: PathDigest 三层输出
# ════════════════════════════════════════════════════════════


class TestPathDigest:
    """IST-402: PathDigest L0/L1/L2 字段正确性和 token 大小。"""

    def _make_digest(self) -> PathDigest:
        traces = [
            StepTrace(
                step=1, action="search", query="Nobel 2024",
                key_info="Hopfield & Hinton won Nobel Physics",
                conclusion="Two winners confirmed",
                confidence=0.7, timestamp=100.0, tool_name="web_search", tokens_used=50,
            ),
            StepTrace(
                step=2, action="browse", query="nobelprize.org",
                key_info="John Hopfield, Geoffrey Hinton",
                conclusion="Official source confirms names",
                confidence=0.9, timestamp=110.0, tool_name="browse_webpage", tokens_used=80,
            ),
        ]
        return PathDigest(
            task_id="test123",
            path_index=0,
            island_id="info_tracking",
            strategy_name="breadth_first",
            answer="Hopfield & Hinton",
            confidence="high",
            total_steps=2,
            total_tokens=130,
            traces=traces,
            reasoning_chain="Two winners confirmed → Official source confirms names",
            key_findings=["Hopfield & Hinton won 2024 Nobel Physics"],
            potential_issues=[],
            tools_used=["web_search", "browse_webpage"],
            start_time=100.0,
            end_time=120.0,
        )

    def test_l0_fields(self):
        d = self._make_digest()
        l0 = d.to_l0()
        assert set(l0.keys()) == {"answer", "confidence", "total_steps", "total_tokens"}
        assert l0["answer"] == "Hopfield & Hinton"
        assert l0["confidence"] == "high"

    def test_l1_fields(self):
        d = self._make_digest()
        l1 = d.to_l1()
        assert "reasoning_chain" in l1
        assert "key_findings" in l1
        assert "traces" in l1
        # L1 traces should NOT have timestamp/tokens_used
        for t in l1["traces"]:
            assert "timestamp" not in t
            assert "tokens_used" not in t

    def test_l2_fields(self):
        d = self._make_digest()
        l2 = d.to_l2()
        assert "island_id" in l2
        assert "start_time" in l2
        assert "end_time" in l2
        # L2 traces SHOULD have timestamp/tokens_used
        for t in l2["traces"]:
            assert "timestamp" in t

    def test_l1_is_smaller_than_l2(self):
        d = self._make_digest()
        l1_json = json.dumps(d.to_l1())
        l2_json = json.dumps(d.to_l2())
        assert len(l1_json) < len(l2_json)

    def test_roundtrip(self):
        d = self._make_digest()
        data = d.to_dict()
        d2 = PathDigest.from_dict(data)
        assert d2.task_id == d.task_id
        assert d2.path_index == d.path_index
        assert d2.answer == d.answer
        assert len(d2.traces) == 2
        assert d2.traces[0].action == "search"


# ════════════════════════════════════════════════════════════
# IST-403: ConclusionExtractor
# ════════════════════════════════════════════════════════════


class TestConclusionExtractor:
    """IST-403: 标准提取 / 无标签 / 畸形标签 / 标签移除。"""

    def test_standard_extract(self):
        text = "blah <conclusion>Found X</conclusion> <confidence>0.8</confidence> blah"
        conc, conf = ConclusionExtractor.extract(text)
        assert conc == "Found X"
        assert conf == 0.8

    def test_no_tags(self):
        text = "no tags here"
        conc, conf = ConclusionExtractor.extract(text)
        assert conc is None
        assert conf is None

    def test_unclosed_tag(self):
        text = "<conclusion>Unclosed tag"
        conc, conf = ConclusionExtractor.extract(text)
        assert conc is None
        assert conf is None

    def test_empty_conclusion(self):
        text = "<conclusion></conclusion>"
        conc, conf = ConclusionExtractor.extract(text)
        assert conc is None  # empty → treated as None

    def test_case_insensitive(self):
        text = "<CONCLUSION>Case insensitive</CONCLUSION>"
        conc, conf = ConclusionExtractor.extract(text)
        assert conc == "Case insensitive"
        assert conf is None

    def test_confidence_out_of_range(self):
        text = "<conclusion>OK</conclusion> <confidence>1.5</confidence>"
        conc, conf = ConclusionExtractor.extract(text)
        assert conc == "OK"
        assert conf is None  # 1.5 > 1.0

    def test_confidence_invalid(self):
        text = "<conclusion>OK</conclusion> <confidence>abc</confidence>"
        conc, conf = ConclusionExtractor.extract(text)
        assert conc == "OK"
        assert conf is None

    def test_conclusion_truncated_to_120(self):
        long = "A" * 200
        text = f"<conclusion>{long}</conclusion>"
        conc, _ = ConclusionExtractor.extract(text)
        assert len(conc) == 120

    def test_clean_tags(self):
        text = "Start <conclusion>Found X</conclusion> middle <confidence>0.8</confidence> end"
        cleaned = ConclusionExtractor.clean_tags(text)
        assert "<conclusion>" not in cleaned
        assert "<confidence>" not in cleaned
        assert "Start" in cleaned
        assert "middle" in cleaned
        assert "end" in cleaned

    def test_clean_tags_no_tags(self):
        text = "no tags here"
        assert ConclusionExtractor.clean_tags(text) == text

    def test_multiline_conclusion(self):
        text = "<conclusion>Line 1\nLine 2</conclusion>"
        conc, _ = ConclusionExtractor.extract(text)
        assert "Line 1" in conc
        assert "Line 2" in conc


# ════════════════════════════════════════════════════════════
# IST-404: TracingToolWrapper / key_info 提取策略
# ════════════════════════════════════════════════════════════


class TestKeyInfoExtraction:
    """IST-404: 4 种 key_info 提取策略 + 兜底。"""

    def test_search_with_list_result(self):
        result = [{"title": "Nobel Prize 2024", "snippet": "Hopfield and Hinton won"}]
        info = _extract_key_info_search(result)
        assert "Nobel Prize 2024" in info
        assert len(info) <= 80

    def test_search_with_string_result(self):
        result = "Hopfield & Hinton won the 2024 Nobel Prize in Physics for neural networks"
        info = _extract_key_info_search(result)
        assert len(info) <= 80

    def test_browse_with_dict_result(self):
        result = {"title": "Nobel Prize", "content": "The 2024 prize was awarded to..."}
        info = _extract_key_info_browse(result)
        assert "Nobel Prize" in info
        assert len(info) <= 80

    def test_browse_with_string_result(self):
        result = "Page title\nSome content about the page"
        info = _extract_key_info_browse(result)
        assert len(info) <= 80

    def test_calculate_result(self):
        result = "importing math\n5500000.0"
        info = _extract_key_info_calculate(result)
        assert "5500000.0" in info
        assert len(info) <= 80

    def test_default_truncates(self):
        result = "A" * 200
        info = _extract_key_info_default(result)
        assert len(info) == 80

    def test_extract_key_info_dispatch(self):
        assert len(extract_key_info("search", "result")) <= 80
        assert len(extract_key_info("browse", "result")) <= 80
        assert len(extract_key_info("calculate", "result")) <= 80
        assert len(extract_key_info("unknown_action", "result")) <= 80

    def test_extract_query_priority(self):
        assert _extract_query("web_search", {"query": "test"}) == "test"
        assert _extract_query("browse_webpage", {"url": "http://x.com"}) == "http://x.com"
        assert _extract_query("python_exec", {"code": "print(1)"}) == "print(1)"
        # Fallback to str(arguments)
        result = _extract_query("unknown", {"data": "x"})
        assert "data" in result

    def test_tool_action_map(self):
        assert TOOL_ACTION_MAP["web_search"] == "search"
        assert TOOL_ACTION_MAP["browse_webpage"] == "browse"
        assert TOOL_ACTION_MAP["python_exec"] == "calculate"
        assert TOOL_ACTION_MAP["reasoning"] == "reason"


class TestTracingToolWrapper:
    """IST-404: TracingToolWrapper 包装行为。"""

    @pytest.mark.asyncio
    async def test_execute_tool_records_trace(self):
        mock_tm = AsyncMock()
        mock_tm.execute_tool_call = AsyncMock(return_value="search result text")
        collector = StepTraceCollector("task1", 0)

        wrapper = TracingToolWrapper(mock_tm, collector)
        result = await wrapper.execute_tool_call("server", "web_search", {"query": "test"})

        # Tool result is returned unchanged (DD-007)
        assert result == "search result text"
        # Trace was recorded
        assert collector.step_count == 1

    @pytest.mark.asyncio
    async def test_passthrough_attributes(self):
        mock_tm = MagicMock()
        mock_tm.some_attr = "value"
        collector = StepTraceCollector("task1", 0)
        wrapper = TracingToolWrapper(mock_tm, collector)
        assert wrapper.some_attr == "value"

    @pytest.mark.asyncio
    async def test_multiple_calls_increment_steps(self):
        mock_tm = AsyncMock()
        mock_tm.execute_tool_call = AsyncMock(return_value="result")
        collector = StepTraceCollector("task1", 0)
        wrapper = TracingToolWrapper(mock_tm, collector)

        await wrapper.execute_tool_call("server", "web_search", {"query": "q1"})
        await wrapper.execute_tool_call("server", "browse_webpage", {"url": "http://x.com"})
        await wrapper.execute_tool_call("server", "python_exec", {"code": "1+1"})

        assert collector.step_count == 3


# ════════════════════════════════════════════════════════════
# IST-405: StepTraceCollector
# ════════════════════════════════════════════════════════════


class TestStepTraceCollector:
    """IST-405: 记录 → 补填 → finalize → 汇总。"""

    def test_basic_flow(self):
        c = StepTraceCollector("task1", 0, strategy_name="breadth_first")
        c.record_tool_call("search", "query X", key_info="found Y")
        c.record_conclusion("Y confirms Z", 0.7)
        c.record_tool_call("browse", "url A", key_info="page says B")
        c.record_conclusion("B supports Z", 0.85)

        digest = c.finalize(answer="Z", final_confidence="high")

        assert digest.answer == "Z"
        assert digest.confidence == "high"
        assert digest.total_steps == 2
        assert len(digest.traces) == 2
        assert digest.traces[0].conclusion == "Y confirms Z"
        assert digest.traces[1].confidence == 0.85

    def test_orphan_conclusion_creates_reason_step(self):
        """IST-011: 孤立 conclusion → action='reason'。"""
        c = StepTraceCollector("task1", 0)
        c.record_tool_call("search", "q1", key_info="info1")
        c.record_conclusion("conclusion 1", 0.5)
        # Orphan conclusion (no preceding tool call)
        c.record_conclusion("Final synthesis", 0.9)

        digest = c.finalize(answer="ans")
        assert digest.total_steps == 2
        assert digest.traces[1].action == "reason"
        assert digest.traces[1].conclusion == "Final synthesis"

    def test_pending_trace_without_conclusion(self):
        """Pending trace without conclusion is still included in finalize."""
        c = StepTraceCollector("task1", 0)
        c.record_tool_call("search", "q1", key_info="info1")
        # No conclusion recorded for this tool call
        digest = c.finalize(answer="ans")
        assert digest.total_steps == 1
        assert digest.traces[0].conclusion is None

    def test_consecutive_tool_calls_flush_pending(self):
        """Two consecutive tool calls without conclusion in between."""
        c = StepTraceCollector("task1", 0)
        c.record_tool_call("search", "q1", key_info="info1")
        c.record_tool_call("search", "q2", key_info="info2")
        c.record_conclusion("conc2", 0.8)

        digest = c.finalize(answer="ans")
        assert digest.total_steps == 2
        assert digest.traces[0].conclusion is None
        assert digest.traces[1].conclusion == "conc2"

    def test_reasoning_chain_from_conclusions(self):
        """IST-103: reasoning_chain 取首/中/尾三条。"""
        c = StepTraceCollector("task1", 0)
        for i in range(5):
            c.record_tool_call("search", f"q{i}", key_info=f"info{i}")
            c.record_conclusion(f"Conclusion number {i} is important", 0.5 + i * 0.1)

        digest = c.finalize(answer="ans")
        # 5 conclusions, picks indices 0, 2, 4
        assert "Conclusion number 0" in digest.reasoning_chain
        assert "Conclusion number 2" in digest.reasoning_chain
        assert "Conclusion number 4" in digest.reasoning_chain
        assert " → " in digest.reasoning_chain

    def test_reasoning_chain_fallback_to_key_info(self):
        """IST-103: No conclusions → fallback to key_info."""
        c = StepTraceCollector("task1", 0)
        c.record_tool_call("search", "q1", key_info="Found important data point A")
        c.record_tool_call("search", "q2", key_info="Found important data point B")

        digest = c.finalize(answer="ans")
        assert "Found important data point A" in digest.reasoning_chain

    def test_reasoning_chain_no_data(self):
        c = StepTraceCollector("task1", 0)
        digest = c.finalize(answer="ans")
        assert digest.reasoning_chain == "(no reasoning chain captured)"

    def test_key_findings_dedup(self):
        """IST-104: key_findings 去重且 ≤5 条。"""
        c = StepTraceCollector("task1", 0)
        for i in range(8):
            c.record_tool_call("search", f"q{i}", key_info="same finding repeated" if i < 5 else f"unique finding {i}")
        digest = c.finalize(answer="ans")
        # "same finding repeated" appears only once due to dedup
        assert len(digest.key_findings) <= 5

    def test_potential_issues_low_confidence(self):
        """IST-105: Low confidence → potential issue."""
        c = StepTraceCollector("task1", 0)
        c.record_tool_call("search", "q1", key_info="info1")
        c.record_conclusion("uncertain result", 0.2)
        digest = c.finalize(answer="ans")
        assert len(digest.potential_issues) >= 1
        assert "low confidence" in digest.potential_issues[0]

    def test_potential_issues_empty_search(self):
        """IST-105: Empty search result → potential issue."""
        c = StepTraceCollector("task1", 0)
        c.record_tool_call("search", "obscure query", key_info="")
        digest = c.finalize(answer="ans")
        assert len(digest.potential_issues) >= 1
        assert "no useful results" in digest.potential_issues[0]

    def test_potential_issues_max_three(self):
        """IST-105: ≤3 issues."""
        c = StepTraceCollector("task1", 0)
        for i in range(10):
            c.record_tool_call("search", f"q{i}", key_info="")
        digest = c.finalize(answer="ans")
        assert len(digest.potential_issues) <= 3

    def test_tools_used_dedup(self):
        c = StepTraceCollector("task1", 0)
        c.record_tool_call("search", "q1", tool_name="web_search")
        c.record_tool_call("search", "q2", tool_name="web_search")
        c.record_tool_call("browse", "url", tool_name="browse_webpage")
        digest = c.finalize(answer="ans")
        assert digest.tools_used == ["web_search", "browse_webpage"]

    def test_token_accumulation(self):
        """IST-012: Token 累计。"""
        c = StepTraceCollector("task1", 0)
        c.record_tool_call("search", "q1")
        c.record_tokens(100)
        c.record_tool_call("search", "q2")
        c.record_tokens(200)
        digest = c.finalize(answer="ans")
        assert digest.total_tokens == 300


# ════════════════════════════════════════════════════════════
# IST-406: DigestStore 读写
# ════════════════════════════════════════════════════════════


class TestDigestStore:
    """IST-406: 保存 / 加载 / 层级过滤 / 文件不存在。"""

    @pytest.fixture
    def store(self, tmp_path):
        return DigestStore(base_dir=str(tmp_path / "digests"))

    def _make_digest(self) -> PathDigest:
        return PathDigest(
            task_id="test_task",
            path_index=0,
            strategy_name="breadth_first",
            answer="42",
            confidence="high",
            total_steps=2,
            total_tokens=100,
            traces=[
                StepTrace(step=1, action="search", query="q", key_info="info",
                         conclusion="found it", confidence=0.9, timestamp=100.0),
            ],
            reasoning_chain="found it",
            key_findings=["info"],
            potential_issues=[],
            tools_used=["web_search"],
            start_time=100.0,
            end_time=110.0,
        )

    @pytest.mark.asyncio
    async def test_save_and_load_l2(self, store):
        digest = self._make_digest()
        await store.save_path_digest(digest)
        loaded = await store.load_path_digest("test_task", 0, depth="l2")
        assert loaded is not None
        assert loaded["answer"] == "42"
        assert loaded["start_time"] == 100.0
        assert len(loaded["traces"]) == 1

    @pytest.mark.asyncio
    async def test_load_l1(self, store):
        digest = self._make_digest()
        await store.save_path_digest(digest)
        loaded = await store.load_path_digest("test_task", 0, depth="l1")
        assert loaded is not None
        assert "reasoning_chain" in loaded
        # L1 traces should not have timestamp
        assert "timestamp" not in loaded["traces"][0]

    @pytest.mark.asyncio
    async def test_load_l0(self, store):
        digest = self._make_digest()
        await store.save_path_digest(digest)
        loaded = await store.load_path_digest("test_task", 0, depth="l0")
        assert loaded is not None
        assert set(loaded.keys()) == {"answer", "confidence", "total_steps", "total_tokens"}

    @pytest.mark.asyncio
    async def test_load_nonexistent(self, store):
        loaded = await store.load_path_digest("nonexistent", 0)
        assert loaded is None

    @pytest.mark.asyncio
    async def test_save_and_load_bundle(self, store):
        digest = self._make_digest()
        bundle = TaskDigestBundle(
            task_id="test_task",
            question="What is 6*7?",
            path_digests=[digest],
            voted_answer="42",
            was_correct=True,
        )
        await store.save_task_bundle(bundle)
        comparison = await store.load_task_comparison("test_task")
        assert comparison is not None
        assert "42" in comparison
        assert "Path 0" in comparison

    @pytest.mark.asyncio
    async def test_load_comparison_nonexistent(self, store):
        result = await store.load_task_comparison("nonexistent")
        assert result is None


# ════════════════════════════════════════════════════════════
# IST-407: 集成测试 — 完整单路径 trace
# ════════════════════════════════════════════════════════════


class TestIntegrationSinglePath:
    """IST-407: 端到端单路径 trace → PathDigest。"""

    @pytest.mark.asyncio
    async def test_full_single_path_trace(self):
        collector = StepTraceCollector(
            task_id="integ_test",
            path_index=0,
            island_id="info_tracking",
            strategy_name="breadth_first",
        )

        # Simulate a tool execution flow
        mock_tm = AsyncMock()
        mock_tm.execute_tool_call = AsyncMock(side_effect=[
            [{"title": "Nobel 2024", "snippet": "Hopfield and Hinton"}],
            {"title": "Nobel Prize", "content": "Official announcement page"},
            "5500000.0\n",
        ])
        wrapper = TracingToolWrapper(mock_tm, collector)

        # Step 1: search
        await wrapper.execute_tool_call("server", "web_search", {"query": "Nobel 2024"})
        collector.record_conclusion("Two winners confirmed", 0.6)

        # Step 2: browse
        await wrapper.execute_tool_call("server", "browse_webpage", {"url": "nobelprize.org"})
        collector.record_conclusion("Official source confirms", 0.8)

        # Step 3: calculate
        await wrapper.execute_tool_call("server", "python_exec", {"code": "11000000/2"})
        collector.record_conclusion("Each gets 5.5M SEK", 0.95)

        # Finalize
        digest = collector.finalize(answer="Hopfield & Hinton", final_confidence="high")

        assert digest.total_steps == 3
        assert digest.answer == "Hopfield & Hinton"
        assert digest.confidence == "high"
        assert len(digest.traces) == 3
        assert digest.traces[0].action == "search"
        assert digest.traces[1].action == "browse"
        assert digest.traces[2].action == "calculate"
        assert "Two winners confirmed" in digest.reasoning_chain
        assert len(digest.key_findings) > 0
        assert "web_search" in digest.tools_used

        # Verify L1 is smaller than L2
        l1 = json.dumps(digest.to_l1())
        l2 = json.dumps(digest.to_l2())
        assert len(l1) < len(l2)

    @pytest.mark.asyncio
    async def test_full_path_with_store(self, tmp_path):
        """End-to-end: collect → finalize → save → load."""
        store = DigestStore(base_dir=str(tmp_path / "digests"))
        collector = StepTraceCollector("e2e_task", 0, strategy_name="depth_first")

        collector.record_tool_call("search", "test query", key_info="found answer")
        collector.record_conclusion("Answer is 42", 0.99)

        digest = collector.finalize(answer="42", final_confidence="high")
        await store.save_path_digest(digest)

        loaded = await store.load_path_digest("e2e_task", 0, depth="l1")
        assert loaded is not None
        assert loaded["answer"] == "42"
        assert "Answer is 42" in loaded["reasoning_chain"]


# ════════════════════════════════════════════════════════════
# IST-408: 集成测试 — 多路径 bundle + 对比视图
# ════════════════════════════════════════════════════════════


class TestIntegrationMultiPath:
    """IST-408: 多路径执行 → TaskDigestBundle → 对比视图。"""

    def test_multi_path_bundle(self):
        digests = []
        for i in range(3):
            c = StepTraceCollector(f"multi_task", i, strategy_name=f"strategy_{i}")
            c.record_tool_call("search", f"query_{i}", key_info=f"finding_{i} is relevant")
            c.record_conclusion(f"Path {i} conclusion is very important", 0.5 + i * 0.2)
            digests.append(c.finalize(answer=f"answer_{i}", final_confidence="medium"))

        bundle = TaskDigestBundle(
            task_id="multi_task",
            question="What is the answer?",
            path_digests=digests,
            voted_answer="answer_1",
            was_correct=True,
        )

        view = bundle.get_comparison_view()
        assert "Path 0" in view
        assert "Path 1" in view
        assert "Path 2" in view
        assert "answer_0" in view
        assert "Correct: True" in view

    @pytest.mark.asyncio
    async def test_bundle_save_and_compare(self, tmp_path):
        store = DigestStore(base_dir=str(tmp_path / "digests"))

        digests = []
        for i in range(2):
            c = StepTraceCollector("bundle_test", i, strategy_name=f"s{i}")
            c.record_tool_call("search", f"q{i}", key_info=f"info_{i} is very useful")
            c.record_conclusion(f"Concluded path {i} with findings", 0.7)
            d = c.finalize(answer=f"ans_{i}")
            await store.save_path_digest(d)
            digests.append(d)

        bundle = TaskDigestBundle(
            task_id="bundle_test",
            question="Test question",
            path_digests=digests,
            voted_answer="ans_0",
        )
        await store.save_task_bundle(bundle)

        comparison = await store.load_task_comparison("bundle_test")
        assert comparison is not None
        assert "Path 0" in comparison
        assert "Path 1" in comparison


# ════════════════════════════════════════════════════════════
# IST-408: TRACE_INSTRUCTION 存在性
# ════════════════════════════════════════════════════════════


class TestTraceInstruction:
    """IST-008: Verify TRACE_INSTRUCTION contains required elements."""

    def test_contains_conclusion_tag(self):
        assert "<conclusion>" in TRACE_INSTRUCTION

    def test_contains_confidence_tag(self):
        assert "<confidence>" in TRACE_INSTRUCTION

    def test_contains_protocol_header(self):
        assert "Execution Trace Protocol" in TRACE_INSTRUCTION


# ════════════════════════════════════════════════════════════
# IST-411~414: 回归安全性验证
# ════════════════════════════════════════════════════════════


class TestRegressionSafety:
    """IST-411~414: Module import doesn't break existing code."""

    def test_import_does_not_break(self):
        """IST-411: Importing the module should not cause errors."""
        from src.core import inline_step_trace
        assert hasattr(inline_step_trace, "StepTrace")
        assert hasattr(inline_step_trace, "PathDigest")
        assert hasattr(inline_step_trace, "TaskDigestBundle")
        assert hasattr(inline_step_trace, "TracingToolWrapper")
        assert hasattr(inline_step_trace, "ConclusionExtractor")
        assert hasattr(inline_step_trace, "StepTraceCollector")
        assert hasattr(inline_step_trace, "DigestStore")

    def test_wrapper_returns_unchanged_result(self):
        """IST-412: TracingWrapper doesn't alter tool results."""
        # Verified in TestTracingToolWrapper.test_execute_tool_records_trace
        pass

    def test_no_extra_api_calls(self):
        """IST-414: Module uses zero LLM API calls — pure code extraction."""
        # ConclusionExtractor uses regex, TracingToolWrapper uses code extraction
        # No LLM call functions exist in the module
        import inspect
        from src.core import inline_step_trace as mod
        source = inspect.getsource(mod)
        # Should not contain any LLM client creation or API call patterns
        assert "create_message" not in source
        assert "openai.ChatCompletion" not in source
