# Copyright 2026 EvoAgent Contributors
# SPDX-License-Identifier: MIT
"""
Weighted Voting & Strategy Evaluation — 加权投票与策略评估模块 (WV)。

实现功能：
- WV-001~008: StrategyMetrics / record_result / get_fitness (策略评估记录层)
- WV-101~108: PathVoteInput / VoteResult / weighted_vote (加权投票层)
- WV-201~207: 结构化输出格式定义与解析 (结构化输出层)

核心流程：
1. 多路径执行后，收集各路径的 PathVoteInput (answer + confidence + evidence + risk)
2. weighted_majority_vote() 加权投票 → 共识则直接采用，分裂则触发 Judge 仲裁
3. record_result() 记录策略胜负，更新 StrategyMetrics
4. get_fitness() 返回题型条件化适应度，供岛内排名使用
"""

from __future__ import annotations

import logging
import re
import uuid
from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


# ════════════════════════════════════════════════════════════
#  Layer 1: 策略评估记录 (WV-001 ~ WV-008)
# ════════════════════════════════════════════════════════════

# WV-006: 最小样本阈值
MIN_TYPE_SAMPLES: int = 3

# WV-007: 零样本默认 fitness
DEFAULT_FITNESS: float = 0.5


@dataclass
class StrategyMetrics:
    """WV-001: 策略评估指标数据结构。

    Attributes:
        overall: 全局统计 {total, wins, rate}
        by_type: 按题型拆分的统计 {question_type → {total, wins, rate}}
    """

    overall: Dict[str, Any] = field(default_factory=lambda: {
        "total": 0,
        "wins": 0,
        "rate": 0.0,
    })
    by_type: Dict[str, Dict[str, Any]] = field(default_factory=dict)

    def to_dict(self) -> dict:
        """序列化为 dict，用于 JSON 存储 (WV-008)。"""
        return {
            "overall": dict(self.overall),
            "by_type": {k: dict(v) for k, v in self.by_type.items()},
        }

    @classmethod
    def from_dict(cls, data: dict) -> StrategyMetrics:
        """从 dict 反序列化。"""
        return cls(
            overall=data.get("overall", {"total": 0, "wins": 0, "rate": 0.0}),
            by_type=data.get("by_type", {}),
        )


def record_result(
    strategy_id: str,
    island_id: str,
    question_type: str,
    won: bool,
    adopted: bool,
    metrics: StrategyMetrics,
) -> StrategyMetrics:
    """WV-002: 记录单次任务结果，更新策略指标。

    Args:
        strategy_id: 策略唯一标识
        island_id: 所属岛 ID
        question_type: 题型（来自 ParsedQuestion.question_type）
        won: 该策略的答案是否是最终被采纳的正确答案
        adopted: 该策略的答案是否被投票选中
        metrics: 当前策略的 StrategyMetrics（就地更新）

    Returns:
        更新后的 StrategyMetrics
    """
    # WV-004: 更新 overall
    metrics.overall["total"] += 1
    if won:
        metrics.overall["wins"] += 1
    total = metrics.overall["total"]
    metrics.overall["rate"] = metrics.overall["wins"] / total if total > 0 else 0.0

    # WV-005: 更新 by_type
    if question_type not in metrics.by_type:
        metrics.by_type[question_type] = {"total": 0, "wins": 0, "rate": 0.0}
    ts = metrics.by_type[question_type]
    ts["total"] += 1
    if won:
        ts["wins"] += 1
    ts["rate"] = ts["wins"] / ts["total"] if ts["total"] > 0 else 0.0

    logger.debug(
        f"WV record_result: strategy={strategy_id}, island={island_id}, "
        f"type={question_type}, won={won}, adopted={adopted}, "
        f"overall_rate={metrics.overall['rate']:.3f}"
    )

    return metrics


def get_fitness(
    metrics: StrategyMetrics,
    question_type: Optional[str] = None,
) -> float:
    """WV-003: 获取策略适应度。

    Args:
        metrics: 策略的 StrategyMetrics
        question_type: 当前题型（None 时直接返回全局胜率）

    Returns:
        fitness 值 (0.0 ~ 1.0)

    逻辑:
        1. question_type 存在且 by_type 样本 >= MIN_TYPE_SAMPLES → 题型胜率
        2. 否则 → 全局胜率
        3. WV-007: overall.total == 0 → DEFAULT_FITNESS (0.5)
    """
    # WV-007: 零样本保护
    if metrics.overall["total"] == 0:
        return DEFAULT_FITNESS

    # 尝试题型胜率
    if question_type is not None:
        type_stats = metrics.by_type.get(question_type)
        if type_stats is not None and type_stats["total"] >= MIN_TYPE_SAMPLES:
            return type_stats["rate"]

    # 退回全局胜率
    return metrics.overall["rate"]


# ════════════════════════════════════════════════════════════
#  Layer 2: 加权投票 (WV-101 ~ WV-108)
# ════════════════════════════════════════════════════════════

# WV-101: 权重映射常量
CONFIDENCE_WEIGHTS: Dict[str, int] = {
    "high": 3,
    "medium": 2,
    "low": 1,
}

# WV-103: 共识阈值
CONSENSUS_THRESHOLD: float = 0.6


@dataclass
class PathVoteInput:
    """单条路径的投票输入。"""

    path_index: int
    answer: str
    confidence: str = "medium"          # high / medium / low
    strategy_name: str = ""
    summary: str = ""
    evidence: List[str] = field(default_factory=list)
    risk: str = ""


@dataclass
class VoteResult:
    """WV-107: 投票结果元数据。"""

    winner_answer: str
    winner_path_index: int
    winner_strategy: str
    method: str                          # "weighted_majority" | "judge"
    total_weight: int
    weight_distribution: Dict[str, Dict[str, Any]]
    consensus_ratio: float
    judge_used: bool = False
    judge_reason: str = ""


def normalize_answer(answer: str) -> str:
    r"""WV-106: 答案归一化。

    处理:
        - strip 前后空白
        - lower case
        - 移除 \boxed{} 包装
        - 移除多余标点
    """
    text = answer.strip().lower()

    # 移除 \boxed{...}
    boxed_match = re.search(r"\\boxed\{(.+?)\}", text)
    if boxed_match:
        text = boxed_match.group(1).strip()

    # 移除多余标点（保留字母、数字、中文、空格）
    text = re.sub(r"[^\w\s\u4e00-\u9fff]", "", text)
    text = re.sub(r"\s+", " ", text).strip()

    return text


def get_weight(confidence: str) -> int:
    """WV-101/108: 获取置信度对应权重。未知置信度默认返回 1（向后兼容）。"""
    return CONFIDENCE_WEIGHTS.get(confidence.lower() if confidence else "", 1)


def weighted_majority_vote(
    inputs: List[PathVoteInput],
) -> Tuple[Optional[VoteResult], bool]:
    """WV-102~104: 加权多数投票。

    Args:
        inputs: 各路径的投票输入列表

    Returns:
        (VoteResult, needs_judge): 投票结果 和 是否需要 Judge 仲裁
    """
    if not inputs:
        return None, False

    # WV-106: 归一化答案
    normalized = [(normalize_answer(inp.answer), inp) for inp in inputs]

    # WV-102: 按归一化答案分组，累加权重
    answer_weights: Dict[str, int] = {}
    answer_paths: Dict[str, List[PathVoteInput]] = {}
    answer_confidences: Dict[str, List[str]] = {}

    for norm_answer, inp in normalized:
        weight = get_weight(inp.confidence)
        answer_weights[norm_answer] = answer_weights.get(norm_answer, 0) + weight
        answer_paths.setdefault(norm_answer, []).append(inp)
        answer_confidences.setdefault(norm_answer, []).append(inp.confidence)

    total_weight = sum(answer_weights.values())
    if total_weight == 0:
        return None, False

    # 找到最高权重的答案
    best_answer = max(answer_weights, key=answer_weights.get)  # type: ignore[arg-type]
    best_weight = answer_weights[best_answer]
    consensus_ratio = best_weight / total_weight

    # 构建 weight_distribution
    weight_distribution: Dict[str, Dict[str, Any]] = {}
    for norm_answer, weight in answer_weights.items():
        paths = answer_paths[norm_answer]
        weight_distribution[norm_answer] = {
            "weight": weight,
            "paths": [p.path_index for p in paths],
            "confidences": answer_confidences[norm_answer],
        }

    # 选取 winner 的原始信息（用归一化前的第一个匹配）
    winner_inp = answer_paths[best_answer][0]

    result = VoteResult(
        winner_answer=winner_inp.answer,  # 返回原始答案（非归一化）
        winner_path_index=winner_inp.path_index,
        winner_strategy=winner_inp.strategy_name,
        method="weighted_majority",
        total_weight=total_weight,
        weight_distribution=weight_distribution,
        consensus_ratio=consensus_ratio,
        judge_used=False,
    )

    # WV-103/104: 共识 vs 分裂判定
    needs_judge = consensus_ratio <= CONSENSUS_THRESHOLD

    logger.info(
        f"WV weighted_majority_vote: winner='{best_answer}', "
        f"ratio={consensus_ratio:.3f}, needs_judge={needs_judge}, "
        f"distribution={answer_weights}"
    )

    return result, needs_judge


async def judge_with_evidence(
    inputs: List[PathVoteInput],
    task_description: str,
    judge_callable: Callable,
) -> VoteResult:
    """WV-105: 带证据的 Judge 仲裁。

    Args:
        inputs: 各路径的投票输入（含 confidence, evidence, risk）
        task_description: 原始任务描述
        judge_callable: LLM Judge 调用函数，接受 prompt 返回响应字符串。
                        设计为可 mock 的依赖（与 EE 模块一致的 callable 模式）。

    Returns:
        VoteResult (method="judge")
    """
    # 构建增强 Judge prompt
    judge_prompt = _build_judge_prompt(inputs, task_description)

    # 调用 Judge
    try:
        response = await judge_callable(judge_prompt)
        chosen_idx, reason = _parse_judge_response(response, len(inputs))
    except Exception as e:
        logger.warning(f"WV judge_with_evidence failed: {e}, falling back to first input")
        chosen_idx = 0
        reason = f"Judge failed: {e}"

    chosen = inputs[chosen_idx]

    # 重新计算 weight_distribution（与 majority_vote 一致）
    normalized = [(normalize_answer(inp.answer), inp) for inp in inputs]
    answer_weights: Dict[str, int] = {}
    answer_paths: Dict[str, List[PathVoteInput]] = {}
    answer_confidences: Dict[str, List[str]] = {}

    for norm_answer, inp in normalized:
        weight = get_weight(inp.confidence)
        answer_weights[norm_answer] = answer_weights.get(norm_answer, 0) + weight
        answer_paths.setdefault(norm_answer, []).append(inp)
        answer_confidences.setdefault(norm_answer, []).append(inp.confidence)

    total_weight = sum(answer_weights.values())
    weight_distribution: Dict[str, Dict[str, Any]] = {}
    for norm_answer, weight in answer_weights.items():
        paths = answer_paths[norm_answer]
        weight_distribution[norm_answer] = {
            "weight": weight,
            "paths": [p.path_index for p in paths],
            "confidences": answer_confidences[norm_answer],
        }

    chosen_norm = normalize_answer(chosen.answer)
    consensus_ratio = (
        answer_weights.get(chosen_norm, 0) / total_weight if total_weight > 0 else 0.0
    )

    return VoteResult(
        winner_answer=chosen.answer,
        winner_path_index=chosen.path_index,
        winner_strategy=chosen.strategy_name,
        method="judge",
        total_weight=total_weight,
        weight_distribution=weight_distribution,
        consensus_ratio=consensus_ratio,
        judge_used=True,
        judge_reason=reason,
    )


async def weighted_vote(
    inputs: List[PathVoteInput],
    task_description: str,
    judge_callable: Optional[Callable] = None,
) -> VoteResult:
    """加权投票入口：综合 weighted_majority_vote + judge_with_evidence。

    Args:
        inputs: 各路径的投票输入
        task_description: 原始任务描述
        judge_callable: 可选的 Judge LLM 调用函数（None 时分裂也直接用 majority 结果）

    Returns:
        VoteResult
    """
    if not inputs:
        return VoteResult(
            winner_answer="",
            winner_path_index=0,
            winner_strategy="",
            method="weighted_majority",
            total_weight=0,
            weight_distribution={},
            consensus_ratio=0.0,
        )

    result, needs_judge = weighted_majority_vote(inputs)

    if result is None:
        return VoteResult(
            winner_answer=inputs[0].answer,
            winner_path_index=inputs[0].path_index,
            winner_strategy=inputs[0].strategy_name,
            method="weighted_majority",
            total_weight=0,
            weight_distribution={},
            consensus_ratio=0.0,
        )

    if needs_judge and judge_callable is not None:
        logger.info("WV weighted_vote: split detected, invoking Judge")
        return await judge_with_evidence(inputs, task_description, judge_callable)

    return result


# ════════════════════════════════════════════════════════════
#  Layer 3: 结构化输出 (WV-201 ~ WV-207)
# ════════════════════════════════════════════════════════════

# WV-201: 结构化输出格式（追加到 Agent system prompt）
STRUCTURED_OUTPUT_INSTRUCTION = """
在你给出最终答案时，请使用以下格式：

答案：\\boxed{你的答案}
置信度：high / medium / low
关键证据：[来源1: 一句话摘要, 来源2: 一句话摘要]
主要风险：这个答案可能错在哪里（一句话）

置信度说明：
- high: 多个可靠来源交叉验证，证据充分
- medium: 有一定证据支持，但未完全确认
- low: 证据不足或相互矛盾，不太确定
"""

# WV-203: 与 IST trace 要求合并后的统一 prompt 块
COMBINED_TRACE_AND_OUTPUT_INSTRUCTION = """
## 执行过程追踪

每次使用工具后，用一句话总结你的发现：
<conclusion>你从这步中得出的关键结论</conclusion>
<confidence>0.0-1.0</confidence>

## 最终答案格式

在你给出最终答案时，请使用以下格式：

答案：\\boxed{你的答案}
置信度：high / medium / low
关键证据：[来源1: 一句话摘要, 来源2: 一句话摘要]
主要风险：这个答案可能错在哪里（一句话）
"""


@dataclass
class StructuredOutput:
    """WV-204: 解析后的结构化输出。"""

    answer: str = ""
    confidence: str = "medium"        # WV-207: 默认 medium
    evidence: List[str] = field(default_factory=list)  # WV-207: 默认 []
    risk: str = ""                    # WV-207: 默认 ""


def parse_structured_output(text: str) -> StructuredOutput:
    r"""WV-204: 从 Agent 输出文本中解析结构化输出。

    解析规则:
        - 答案：\boxed{...} 或 "答案：..." 行
        - 置信度：high / medium / low
        - 关键证据：[...] 列表
        - 主要风险：一句话

    WV-207: 任何字段解析失败时使用默认值。
    """
    return StructuredOutput(
        answer=_parse_answer(text),
        confidence=parse_confidence(text),
        evidence=parse_evidence(text),
        risk=parse_risk(text),
    )


def _parse_answer(text: str) -> str:
    r"""从文本中提取答案。优先匹配 \boxed{...}，其次匹配 "答案：..." 行。"""
    # 优先匹配 \boxed{...}
    boxed = re.search(r"\\boxed\{(.+?)\}", text)
    if boxed:
        return boxed.group(1).strip()

    # 匹配 "答案：..." 或 "答案:" 行
    answer_line = re.search(r"答案[：:]\s*(.+)", text)
    if answer_line:
        ans = answer_line.group(1).strip()
        # 去除可能的 \boxed{} 包装
        boxed2 = re.search(r"\\boxed\{(.+?)\}", ans)
        if boxed2:
            return boxed2.group(1).strip()
        return ans

    return ""


def parse_confidence(text: str) -> str:
    """WV-206: 从文本中提取置信度。返回 high/medium/low，默认 medium。"""
    match = re.search(
        r"(?:置信度|confidence)[：:\s]*\b(high|medium|low)\b", text, re.IGNORECASE
    )
    if match:
        return match.group(1).lower()
    return "medium"


def parse_evidence(text: str) -> List[str]:
    """WV-206: 从文本中提取关键证据列表。"""
    match = re.search(r"关键证据[：:]\s*\[(.+?)\]", text, re.DOTALL)
    if match:
        raw = match.group(1)
        # 按逗号分割（但不在 URL 内的逗号）
        items = re.split(r",\s*(?=[^\]]*(?:\[|$))", raw)
        if not items or len(items) == 1:
            items = raw.split(",")
        return [item.strip() for item in items if item.strip()]
    return []


def parse_risk(text: str) -> str:
    """WV-206: 从文本中提取主要风险。"""
    match = re.search(r"主要风险[：:]\s*(.+)", text)
    if match:
        return match.group(1).strip()
    return ""


# ════════════════════════════════════════════════════════════
#  Internal helpers
# ════════════════════════════════════════════════════════════


def _build_judge_prompt(
    inputs: List[PathVoteInput], task_description: str
) -> str:
    """构建增强版 Judge prompt（WV-105），包含 confidence + evidence + risk。"""
    parts = [
        "You are evaluating multiple answers to the same question. "
        "Pick the best answer.\n\n"
        f"Question: {task_description}\n"
    ]

    for i, inp in enumerate(inputs, 1):
        parts.append(f"--- Path {i} (Strategy: {inp.strategy_name}) ---")
        parts.append(f"Answer: {inp.answer}")
        parts.append(f"Confidence: {inp.confidence}")
        if inp.evidence:
            parts.append(f"Key Evidence: {inp.evidence}")
        if inp.risk:
            parts.append(f"Risk Analysis: {inp.risk}")
        if inp.summary:
            parts.append(f"Summary: {inp.summary[:2000]}")
        parts.append("")

    parts.append(
        "Consider each path's confidence level, evidence quality, and risk assessment.\n"
        "Which answer is most likely correct and well-supported?\n"
        "Format: BEST: <number>\n"
        "Reason: <brief explanation>"
    )

    return "\n".join(parts)


def _parse_judge_response(response: str, num_inputs: int) -> Tuple[int, str]:
    """解析 Judge 响应，返回 (chosen_index, reason)。"""
    match = re.search(r"BEST:\s*(\d+)", response)
    reason_match = re.search(r"Reason:\s*(.+)", response, re.DOTALL)
    reason = reason_match.group(1).strip() if reason_match else ""

    if match:
        idx = int(match.group(1)) - 1  # 1-based → 0-based
        if 0 <= idx < num_inputs:
            return idx, reason

    # 无法解析 → 默认选第一个
    return 0, reason or "Could not parse judge response"
