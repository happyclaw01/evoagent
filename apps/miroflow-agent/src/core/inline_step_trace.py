# Copyright 2026 EvoAgent Contributors
# SPDX-License-Identifier: MIT
"""
Inline Step Trace (IST) — 运行时痕迹采集与路径摘要生成模块。

在运行时每一步留下结构化痕迹，路径执行完毕自动生成摘要，
反思和进化只读摘要不读原始 log，实现零额外 API 调用的 97% token 压缩。

Implements:
  IST-001: StepTrace 数据结构
  IST-002~006: TracingToolWrapper + key_info 提取策略
  IST-007, IST-009: ConclusionExtractor (标签解析 + 清理)
  IST-008: TRACE_INSTRUCTION (system prompt 注入)
  IST-010~012: StepTraceCollector (收集 + pending 匹配 + token 累计)
  IST-101, IST-106: PathDigest + L0/L1/L2 分层输出
  IST-102~105: finalize 汇总逻辑 (reasoning_chain, key_findings, potential_issues)
  IST-107, IST-108: TaskDigestBundle + 多路径对比视图
  IST-201~206: DigestStore (本地 JSON 后端)
"""

from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# ────────────────────────────────────────────────────────────
# IST-008: System Prompt 注入内容
# ────────────────────────────────────────────────────────────

TRACE_INSTRUCTION = """

## Execution Trace Protocol

After each tool use, before deciding your next action, output:

<conclusion>One-sentence takeaway from this step (max 120 chars)</conclusion>
<confidence>0.0-1.0 your current confidence in the final answer</confidence>

Rules:
- conclusion: focus on what you LEARNED, not what you did
- confidence: how close you are to a reliable answer
- Output these after EVERY tool result
- These tags will be stripped from visible output
"""


# ────────────────────────────────────────────────────────────
# IST-001: StepTrace 数据结构
# ────────────────────────────────────────────────────────────


@dataclass
class StepTrace:
    """单步执行痕迹。"""

    step: int                              # 步骤序号 (1-indexed)
    action: str                            # 动作类型: search | browse | calculate | reason | tool_call
    query: str                             # 输入 (搜索词 / URL / 表达式)
    key_info: Optional[str] = None         # 工具层自动提取 (≤80 chars)
    conclusion: Optional[str] = None       # 模型当步结论 (≤120 chars)
    confidence: Optional[float] = None     # 当前置信度 0.0-1.0
    timestamp: Optional[float] = None      # Unix timestamp
    tool_name: Optional[str] = None        # 具体工具名
    tokens_used: Optional[int] = None      # 该步 token 消耗

    def to_dict(self) -> dict:
        d: dict = {
            "step": self.step,
            "action": self.action,
            "query": self.query,
        }
        if self.key_info is not None:
            d["key_info"] = self.key_info
        if self.conclusion is not None:
            d["conclusion"] = self.conclusion
        if self.confidence is not None:
            d["confidence"] = self.confidence
        if self.timestamp is not None:
            d["timestamp"] = self.timestamp
        if self.tool_name is not None:
            d["tool_name"] = self.tool_name
        if self.tokens_used is not None:
            d["tokens_used"] = self.tokens_used
        return d

    def to_l1_dict(self) -> dict:
        """L1 简化版：省略 timestamp 和 tokens_used。"""
        d: dict = {
            "step": self.step,
            "action": self.action,
            "query": self.query,
        }
        if self.key_info is not None:
            d["key_info"] = self.key_info
        if self.conclusion is not None:
            d["conclusion"] = self.conclusion
        if self.confidence is not None:
            d["confidence"] = self.confidence
        return d

    @classmethod
    def from_dict(cls, data: dict) -> StepTrace:
        return cls(
            step=data["step"],
            action=data["action"],
            query=data["query"],
            key_info=data.get("key_info"),
            conclusion=data.get("conclusion"),
            confidence=data.get("confidence"),
            timestamp=data.get("timestamp"),
            tool_name=data.get("tool_name"),
            tokens_used=data.get("tokens_used"),
        )


# ────────────────────────────────────────────────────────────
# IST-101, IST-106: PathDigest 数据结构 + L0/L1/L2 分层输出
# ────────────────────────────────────────────────────────────


@dataclass
class PathDigest:
    """一条路径的完整执行摘要。"""

    # 身份
    task_id: str
    path_index: int
    island_id: Optional[str] = None
    strategy_name: Optional[str] = None

    # 执行结果
    answer: str = ""
    confidence: str = "medium"         # high / medium / low
    total_steps: int = 0
    total_tokens: int = 0

    # 步骤痕迹
    traces: List[StepTrace] = field(default_factory=list)

    # 自动汇总 (IST-103~105)
    reasoning_chain: str = ""
    key_findings: List[str] = field(default_factory=list)
    potential_issues: List[str] = field(default_factory=list)
    tools_used: List[str] = field(default_factory=list)

    # 时间
    start_time: Optional[float] = None
    end_time: Optional[float] = None

    # ── IST-106: 分层输出 ────────────────────────

    def to_l0(self) -> dict:
        """L0: ~30 tokens — answer + confidence + 统计。"""
        return {
            "answer": self.answer,
            "confidence": self.confidence,
            "total_steps": self.total_steps,
            "total_tokens": self.total_tokens,
        }

    def to_l1(self) -> dict:
        """L1: ~300-400 tokens — 推理链 + 关键发现 + traces 简化版。"""
        return {
            "task_id": self.task_id,
            "path_index": self.path_index,
            "strategy_name": self.strategy_name,
            "answer": self.answer,
            "confidence": self.confidence,
            "total_steps": self.total_steps,
            "reasoning_chain": self.reasoning_chain,
            "key_findings": self.key_findings,
            "potential_issues": self.potential_issues,
            "tools_used": self.tools_used,
            "traces": [t.to_l1_dict() for t in self.traces],
        }

    def to_l2(self) -> dict:
        """L2: 完整版含 timestamp/tokens_used/时间范围。"""
        d = self.to_l1()
        d["island_id"] = self.island_id
        d["total_tokens"] = self.total_tokens
        d["start_time"] = self.start_time
        d["end_time"] = self.end_time
        d["traces"] = [t.to_dict() for t in self.traces]
        return d

    def to_dict(self) -> dict:
        """完整序列化 (等同 L2)。"""
        return self.to_l2()

    @classmethod
    def from_dict(cls, data: dict) -> PathDigest:
        traces = [StepTrace.from_dict(t) for t in data.get("traces", [])]
        return cls(
            task_id=data["task_id"],
            path_index=data["path_index"],
            island_id=data.get("island_id"),
            strategy_name=data.get("strategy_name"),
            answer=data.get("answer", ""),
            confidence=data.get("confidence", "medium"),
            total_steps=data.get("total_steps", 0),
            total_tokens=data.get("total_tokens", 0),
            traces=traces,
            reasoning_chain=data.get("reasoning_chain", ""),
            key_findings=data.get("key_findings", []),
            potential_issues=data.get("potential_issues", []),
            tools_used=data.get("tools_used", []),
            start_time=data.get("start_time"),
            end_time=data.get("end_time"),
        )


# ────────────────────────────────────────────────────────────
# IST-107, IST-108: TaskDigestBundle + 多路径对比视图
# ────────────────────────────────────────────────────────────


@dataclass
class TaskDigestBundle:
    """任务级聚合：所有路径的 PathDigest + 投票结果 + 正确性。"""

    task_id: str
    question: str
    question_type: Optional[str] = None
    ground_truth: Optional[str] = None

    path_digests: List[PathDigest] = field(default_factory=list)

    voted_answer: Optional[str] = None
    vote_method: str = "majority"
    was_correct: Optional[bool] = None

    def to_dict(self) -> dict:
        return {
            "task_id": self.task_id,
            "question": self.question,
            "question_type": self.question_type,
            "ground_truth": self.ground_truth,
            "path_digests": [d.to_dict() for d in self.path_digests],
            "voted_answer": self.voted_answer,
            "vote_method": self.vote_method,
            "was_correct": self.was_correct,
        }

    @classmethod
    def from_dict(cls, data: dict) -> TaskDigestBundle:
        return cls(
            task_id=data["task_id"],
            question=data["question"],
            question_type=data.get("question_type"),
            ground_truth=data.get("ground_truth"),
            path_digests=[
                PathDigest.from_dict(d) for d in data.get("path_digests", [])
            ],
            voted_answer=data.get("voted_answer"),
            vote_method=data.get("vote_method", "majority"),
            was_correct=data.get("was_correct"),
        )

    # IST-108: 多路径对比视图
    def get_comparison_view(self) -> str:
        """生成多路径对比文本，供进化模块使用 (~800-1200 tokens for 5 paths)。"""
        lines: List[str] = []
        lines.append(f"Task: {self.question[:200]}")
        if self.ground_truth:
            lines.append(f"Ground truth: {self.ground_truth}")
        lines.append(f"Voted answer: {self.voted_answer or '(none)'}")
        lines.append(f"Correct: {self.was_correct}")
        lines.append("")
        for d in self.path_digests:
            lines.append(f"--- Path {d.path_index} ({d.strategy_name or 'unknown'}) ---")
            lines.append(f"Answer: {d.answer}")
            lines.append(f"Confidence: {d.confidence}")
            lines.append(f"Steps: {d.total_steps}")
            lines.append(f"Reasoning: {d.reasoning_chain}")
            if d.key_findings:
                lines.append(f"Key findings: {'; '.join(d.key_findings)}")
            if d.potential_issues:
                lines.append(f"Issues: {'; '.join(d.potential_issues)}")
            lines.append("")
        return "\n".join(lines)


# ────────────────────────────────────────────────────────────
# IST-002~006: TracingToolWrapper + key_info 提取策略
# ────────────────────────────────────────────────────────────

# IST-003~006: 工具分类映射
TOOL_ACTION_MAP: Dict[str, str] = {
    # 搜索类
    "web_search": "search",
    "searching_with_google": "search",
    "duckduckgo_search": "search",
    "searching_with_sougou": "search",
    "google_search": "search",
    "baidu_search": "search",
    "sougou_search": "search",
    "serpapi_search": "search",
    # 浏览类
    "browse_webpage": "browse",
    "read_webpage": "browse",
    "reading_content": "browse",
    "scrape_website": "browse",
    "jina_scrape": "browse",
    # 代码执行类
    "python_exec": "calculate",
    "code_execution": "calculate",
    # 推理类
    "reasoning": "reason",
    "deep_think": "reason",
}


def _extract_query(tool_name: str, arguments: dict) -> str:
    """从工具参数中提取查询内容 (IST-002)。"""
    for key in ("query", "url", "code", "question", "input"):
        if key in arguments:
            return str(arguments[key])[:100]
    return str(arguments)[:100]


def _extract_key_info_search(result: Any) -> str:
    """IST-003: 搜索结果取第一条 title + snippet。"""
    # Try JSON array directly
    if isinstance(result, list) and result:
        first = result[0]
        if isinstance(first, dict):
            title = first.get("title", "")
            snippet = first.get("snippet", first.get("description", ""))
            return f"{title}: {snippet}"[:80]
    # Try parsing JSON string (ToolManager returns text content)
    if isinstance(result, str):
        try:
            import json as _json
            parsed = _json.loads(result)
            # Google search format: {"searchParameters":..., "organic":[...]}
            if isinstance(parsed, dict) and "organic" in parsed:
                organic = parsed["organic"]
                if organic and isinstance(organic[0], dict):
                    title = organic[0].get("title", "")
                    snippet = organic[0].get("snippet", organic[0].get("description", ""))
                    return f"{title}: {snippet}"[:80]
            # Direct list of results
            if isinstance(parsed, list) and parsed and isinstance(parsed[0], dict):
                title = parsed[0].get("title", "")
                snippet = parsed[0].get("snippet", parsed[0].get("description", ""))
                return f"{title}: {snippet}"[:80]
        except (ValueError, TypeError, KeyError):
            pass
    # Fallback: first line of text
    text = str(result)
    lines = text.strip().split("\n")
    return lines[0][:80] if lines else text[:80]


def _extract_key_info_browse(result: Any) -> str:
    """IST-004: 网页取标题 + 首段摘要。"""
    text = str(result)
    if isinstance(result, dict):
        title = result.get("title", "")
        content = result.get("content", result.get("text", ""))
        first_para = str(content).split("\n")[0] if content else ""
        return f"{title} | {first_para}"[:80]
    lines = text.strip().split("\n")
    return lines[0][:80] if lines else text[:80]


def _extract_key_info_calculate(result: Any) -> str:
    """IST-005: stdout 最后 2 行。"""
    text = str(result)
    lines = [l for l in text.strip().split("\n") if l.strip()]
    last_two = lines[-2:] if len(lines) >= 2 else lines
    return "\n".join(last_two)[:80]


def _extract_key_info_default(result: Any) -> str:
    """IST-006: 兜底截取前 80 字符。"""
    return str(result)[:80]


# key_info 提取策略分派
_KEY_INFO_EXTRACTORS = {
    "search": _extract_key_info_search,
    "browse": _extract_key_info_browse,
    "calculate": _extract_key_info_calculate,
}


def extract_key_info(action: str, result: Any) -> str:
    """根据 action 类型提取 key_info。"""
    extractor = _KEY_INFO_EXTRACTORS.get(action, _extract_key_info_default)
    try:
        return extractor(result)
    except Exception:
        return _extract_key_info_default(result)


class TracingToolWrapper:
    """IST-002: 包装 ToolManager，每次工具调用后自动提取 key_info。

    TracingToolWrapper 透传所有 ToolManager 属性和方法，
    仅在 ``execute_tool`` (及类似调用) 后追加一次 key_info 提取并
    记录到 StepTraceCollector。不截断工具返回值 (DD-007)。
    """

    def __init__(self, tool_manager: Any, collector: "StepTraceCollector") -> None:
        self._tool_manager = tool_manager
        self._collector = collector

    def __getattr__(self, name: str) -> Any:
        """透传所有未定义属性到底层 ToolManager。"""
        return getattr(self._tool_manager, name)

    async def execute_tool_call(self, server_name: str, tool_name: str, arguments: Any) -> Any:
        """执行工具并自动记录 trace。

        Matches ToolManager.execute_tool_call(server_name, tool_name, arguments) signature.
        """
        action = TOOL_ACTION_MAP.get(tool_name, "tool_call")
        query = _extract_query(tool_name, arguments if isinstance(arguments, dict) else {})

        result = await self._tool_manager.execute_tool_call(server_name, tool_name, arguments)

        # 提取 key_info — 解包 ToolManager 返回的 {"server_name":..., "result":...} 包装
        raw_result = result
        if isinstance(result, dict) and "result" in result:
            raw_result = result["result"]
        key_info = extract_key_info(action, raw_result)

        # 记录到 collector
        self._collector.record_tool_call(
            action=action,
            query=query,
            key_info=key_info,
            tool_name=tool_name,
        )

        # DD-007: 不截断工具返回值
        return result


# ────────────────────────────────────────────────────────────
# IST-007, IST-009: ConclusionExtractor
# ────────────────────────────────────────────────────────────

CONCLUSION_PATTERN = re.compile(r"<conclusion>(.*?)</conclusion>", re.DOTALL | re.IGNORECASE)
CONFIDENCE_PATTERN = re.compile(r"<confidence>([\d.]+)</confidence>", re.IGNORECASE)

# IST-009: 清理正则
TAG_CLEANUP_PATTERN = re.compile(
    r"</?(?:conclusion|confidence)[^>]*>(?:.*?</(?:conclusion|confidence)>)?",
    re.DOTALL | re.IGNORECASE,
)
# More precise: remove full conclusion/confidence tag pairs and stray tags
_FULL_CONCLUSION_TAG = re.compile(r"<conclusion>.*?</conclusion>", re.DOTALL | re.IGNORECASE)
_FULL_CONFIDENCE_TAG = re.compile(r"<confidence>.*?</confidence>", re.DOTALL | re.IGNORECASE)
_STRAY_TAG = re.compile(r"</?(?:conclusion|confidence)[^>]*>", re.IGNORECASE)


class ConclusionExtractor:
    """IST-007: 从 Agent 输出中解析 <conclusion> 和 <confidence> 标签。"""

    @staticmethod
    def extract(text: str) -> tuple[Optional[str], Optional[float]]:
        """解析 conclusion 和 confidence。

        Returns:
            (conclusion_text, confidence_value) — None 表示缺失或无效。
        """
        conclusion: Optional[str] = None
        confidence: Optional[float] = None

        m_conc = CONCLUSION_PATTERN.search(text)
        if m_conc:
            raw = m_conc.group(1).strip()
            if raw:  # 空内容视为 None
                conclusion = raw[:120]

        m_conf = CONFIDENCE_PATTERN.search(text)
        if m_conf:
            try:
                val = float(m_conf.group(1))
                if 0.0 <= val <= 1.0:
                    confidence = val
            except ValueError:
                pass

        return conclusion, confidence

    @staticmethod
    def clean_tags(text: str) -> str:
        """IST-009: 从 Agent 输出中移除 trace 标签。"""
        cleaned = _FULL_CONCLUSION_TAG.sub("", text)
        cleaned = _FULL_CONFIDENCE_TAG.sub("", cleaned)
        cleaned = _STRAY_TAG.sub("", cleaned)
        # 清理多余空白行
        cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
        return cleaned.strip()


# ────────────────────────────────────────────────────────────
# IST-010~012, IST-102~105: StepTraceCollector
# ────────────────────────────────────────────────────────────


class StepTraceCollector:
    """收集器：管理一条路径的所有 StepTrace 并 finalize 生成 PathDigest。

    生命周期绑定单路径 (DD-008)。

    IST-010: record_tool_call / record_conclusion / pending 匹配
    IST-011: 孤立 conclusion → action="reason"
    IST-012: token 累计
    IST-102~105: finalize → PathDigest
    """

    def __init__(
        self,
        task_id: str,
        path_index: int,
        island_id: Optional[str] = None,
        strategy_name: Optional[str] = None,
    ) -> None:
        self._task_id = task_id
        self._path_index = path_index
        self._island_id = island_id
        self._strategy_name = strategy_name
        self._traces: List[StepTrace] = []
        self._pending: Optional[StepTrace] = None
        self._step_counter: int = 0
        self._total_tokens: int = 0
        self._start_time: float = time.time()

    @property
    def traces(self) -> List[StepTrace]:
        return list(self._traces)

    @property
    def step_count(self) -> int:
        return self._step_counter

    # ── IST-010: 记录工具调用 ────────────────────

    def record_tool_call(
        self,
        action: str,
        query: str,
        key_info: Optional[str] = None,
        tool_name: Optional[str] = None,
    ) -> None:
        """记录一次工具调用，创建新 trace 并标记为 pending。"""
        # 如果之前有 pending trace 未收到 conclusion，直接完结它
        if self._pending is not None:
            self._traces.append(self._pending)
            self._pending = None

        self._step_counter += 1
        trace = StepTrace(
            step=self._step_counter,
            action=action,
            query=query,
            key_info=key_info,
            tool_name=tool_name,
            timestamp=time.time(),
        )
        self._pending = trace

    # ── IST-010: 补填 conclusion ─────────────────

    def record_conclusion(
        self,
        conclusion: Optional[str],
        confidence: Optional[float] = None,
    ) -> None:
        """补填 conclusion 到 pending trace，或创建 reason 步骤 (IST-011)。"""
        if self._pending is not None:
            self._pending.conclusion = conclusion
            self._pending.confidence = confidence
            self._traces.append(self._pending)
            self._pending = None
        else:
            # IST-011: 孤立 conclusion → 创建 reason 步骤
            self._step_counter += 1
            trace = StepTrace(
                step=self._step_counter,
                action="reason",
                query="(synthesize findings)",
                conclusion=conclusion,
                confidence=confidence,
                timestamp=time.time(),
            )
            self._traces.append(trace)

    # ── IST-012: token 累计 ──────────────────────

    def record_tokens(self, tokens: int) -> None:
        """累计 token 消耗。"""
        self._total_tokens += tokens
        # 也标记到当前 pending / 最后一条 trace
        target = self._pending or (self._traces[-1] if self._traces else None)
        if target is not None:
            target.tokens_used = (target.tokens_used or 0) + tokens

    # ── IST-102: finalize ────────────────────────

    def finalize(
        self,
        answer: str = "",
        final_confidence: str = "medium",
    ) -> PathDigest:
        """路径执行完毕 → 汇总生成 PathDigest。"""
        # 确保 pending trace 不丢失
        if self._pending is not None:
            self._traces.append(self._pending)
            self._pending = None

        end_time = time.time()

        # 去重 tools_used
        tools_used = list(dict.fromkeys(
            t.tool_name for t in self._traces if t.tool_name
        ))

        digest = PathDigest(
            task_id=self._task_id,
            path_index=self._path_index,
            island_id=self._island_id,
            strategy_name=self._strategy_name,
            answer=answer,
            confidence=final_confidence,
            total_steps=len(self._traces),
            total_tokens=self._total_tokens,
            traces=list(self._traces),
            reasoning_chain=self._build_reasoning_chain(),
            key_findings=self._extract_key_findings(),
            potential_issues=self._extract_issues(),
            tools_used=tools_used,
            start_time=self._start_time,
            end_time=end_time,
        )
        return digest

    # ── IST-103: reasoning_chain ─────────────────

    def _build_reasoning_chain(self) -> str:
        """从 conclusions 取首/中/尾三条拼接为推理链。"""
        conclusions = [
            t.conclusion for t in self._traces
            if t.conclusion and len(t.conclusion) > 10
        ]

        if not conclusions:
            # 降级：用 key_info 拼接
            key_infos = [
                t.key_info for t in self._traces
                if t.key_info and len(t.key_info) > 15
            ]
            return " → ".join(key_infos[:3]) if key_infos else "(no reasoning chain captured)"

        if len(conclusions) <= 3:
            return " → ".join(conclusions)

        # 取首、中、尾
        return " → ".join([
            conclusions[0],
            conclusions[len(conclusions) // 2],
            conclusions[-1],
        ])

    # ── IST-104: key_findings ────────────────────

    def _extract_key_findings(self) -> List[str]:
        """从 key_info 中提取有价值的发现 (≤5 条)。"""
        findings: List[str] = []
        seen: set = set()
        for t in self._traces:
            if t.key_info and len(t.key_info) > 15:
                normalized = t.key_info.strip().lower()
                if normalized not in seen:
                    seen.add(normalized)
                    findings.append(t.key_info)
                    if len(findings) >= 5:
                        break
        return findings

    # ── IST-105: potential_issues ─────────────────

    def _extract_issues(self) -> List[str]:
        """低置信度步骤 + 空/短结果 → 潜在问题 (≤3 条)。"""
        issues: List[str] = []
        for t in self._traces:
            if len(issues) >= 3:
                break
            # 低置信度
            if t.confidence is not None and t.confidence < 0.4:
                issues.append(
                    f"Step {t.step}: low confidence ({t.confidence}) — {t.conclusion or t.query}"
                )
            # 空搜索结果
            elif t.action == "search" and (not t.key_info or len(t.key_info) < 5):
                issues.append(f"Step {t.step}: search returned no useful results for '{t.query}'")
        return issues


# ────────────────────────────────────────────────────────────
# IST-201~206: DigestStore (本地 JSON 后端)
# ────────────────────────────────────────────────────────────


class DigestStore:
    """PathDigest 持久化存储。

    IST-201: 统一接口 save / load / query
    IST-202: 本地 JSON 后端
    IST-204: 按层级加载
    IST-205: TaskBundle 存储
    IST-206: 对比视图加载
    """

    def __init__(self, base_dir: str = "data/digests", viking_storage=None, viking_context=None) -> None:
        self._base_dir = Path(base_dir)
        self._viking = viking_storage
        self._viking_context = viking_context

    def _ensure_dir(self) -> None:
        self._base_dir.mkdir(parents=True, exist_ok=True)

    # ── 文件命名 ─────────────────────────────────

    def _path_digest_file(self, task_id: str, path_index: int) -> Path:
        return self._base_dir / f"{task_id}_path{path_index}.json"

    def _bundle_file(self, task_id: str) -> Path:
        return self._base_dir / f"{task_id}_bundle.json"

    # ── IST-202: save_path_digest ────────────────

    async def save_path_digest(self, digest: PathDigest) -> None:
        """保存 PathDigest (L2 完整版)。"""
        self._ensure_dir()
        path = self._path_digest_file(digest.task_id, digest.path_index)
        data = digest.to_dict()
        path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        # Viking write-through
        if self._viking is not None:
            self._viking.put(
                f"viking://agent/memory/digests/{digest.task_id}_path{digest.path_index}",
                data,
            )

    # ── IST-205: save_task_bundle ────────────────

    async def save_task_bundle(self, bundle: TaskDigestBundle) -> None:
        """保存 TaskDigestBundle。"""
        self._ensure_dir()
        path = self._bundle_file(bundle.task_id)
        data = bundle.to_dict()
        path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        # Viking write-through
        if self._viking is not None:
            self._viking.put(
                f"viking://agent/memory/digests/{bundle.task_id}_bundle",
                data,
            )

    # ── IST-204: load_path_digest ────────────────

    async def load_path_digest(
        self,
        task_id: str,
        path_index: int,
        depth: str = "l1",
    ) -> Optional[dict]:
        """按层级加载 PathDigest。

        Args:
            depth: "l0" | "l1" | "l2"
        """
        path = self._path_digest_file(task_id, path_index)
        data = None
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except Exception as e:
                logger.warning(f"Failed to load digest {path}: {e}")

        # Viking fallback when local file missing
        if data is None and self._viking_context is not None:
            try:
                data = await self._viking_context.load_from_uri(
                    f"viking://agent/memory/digests/{task_id}_path{path_index}"
                )
            except Exception as e:
                logger.warning(f"Viking digest load failed: {e}")

        if data is None:
            return None

        try:
            digest = PathDigest.from_dict(data)
            if depth == "l0":
                return digest.to_l0()
            elif depth == "l1":
                return digest.to_l1()
            else:  # l2
                return digest.to_l2()
        except Exception as e:
            logger.warning(f"Failed to parse digest: {e}")
            return None

    # ── IST-206: load_task_comparison ────────────

    async def load_task_comparison(self, task_id: str) -> Optional[str]:
        """加载任务级对比视图。"""
        bundle_path = self._bundle_file(task_id)
        data = None
        if bundle_path.exists():
            try:
                data = json.loads(bundle_path.read_text(encoding="utf-8"))
            except Exception as e:
                logger.warning(f"Failed to load bundle {bundle_path}: {e}")

        # Viking fallback
        if data is None and self._viking_context is not None:
            try:
                data = await self._viking_context.load_from_uri(
                    f"viking://agent/memory/digests/{task_id}_bundle"
                )
            except Exception as e:
                logger.warning(f"Viking bundle load failed: {e}")

        if data is None:
            return None

        try:
            bundle = TaskDigestBundle.from_dict(data)
            return bundle.get_comparison_view()
        except Exception as e:
            logger.warning(f"Failed to parse bundle: {e}")
            return None
