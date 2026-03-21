# Copyright 2026 EvoAgent Contributors
# SPDX-License-Identifier: MIT
"""
Strategy Definition — 8 维策略定义数据结构。

实现 StrategyDefinition dataclass (QP-010~013) 和 strategy_distance() 函数 (QP-210)。
每个策略是一个 8 维元组，定义 Agent 的搜索行为方向。
"""

from dataclasses import dataclass, field, asdict
from typing import Optional, Dict, Any, List
import copy


STRATEGY_DIMENSIONS = [
    "hypothesis_framing",
    "query_policy",
    "evidence_source",
    "retrieval_depth",
    "update_policy",
    "audit_policy",
    "termination_policy",
]


@dataclass
class StrategyDefinition:
    """8 维策略定义 — QP-010~014

    每个策略是一个 8 维元组，定义 Agent 的搜索行为方向。
    """

    # 身份
    id: str = ""
    name: str = ""
    island_id: str = ""

    # 8 维定义
    hypothesis_framing: str = "news_tracking"
    query_policy: str = "broad_diverse"
    evidence_source: str = "news_wire"
    retrieval_depth: str = "medium"
    update_policy: str = "moderate"
    audit_policy: str = "none"
    termination_policy: str = "confidence_threshold"
    max_turns: int = 100

    # 元数据
    parent_id: Optional[str] = None
    iteration_found: int = 0

    # 按题型拆分的胜率
    metrics: Dict[str, Any] = field(default_factory=lambda: {
        "overall": {"wins": 0, "total": 0, "rate": 0.0},
        "by_type": {},
    })

    def get_rate_for_type(
        self, question_type: str, min_samples: int = 3
    ) -> float:
        """QP-012: 获取指定题型的胜率

        样本数 < min_samples 时退回 overall rate。
        """
        by_type = self.metrics.get("by_type", {})
        type_stats = by_type.get(question_type, {})
        if type_stats.get("total", 0) >= min_samples:
            return type_stats.get("rate", 0.0)
        return self.metrics.get("overall", {}).get("rate", 0.0)

    def record_result(self, question_type: str, won: bool) -> None:
        """记录一次对战结果，更新胜率统计"""
        # 更新 overall
        overall = self.metrics["overall"]
        overall["total"] += 1
        if won:
            overall["wins"] += 1
        overall["rate"] = (
            overall["wins"] / overall["total"] if overall["total"] > 0 else 0.0
        )

        # 更新 by_type
        by_type = self.metrics.setdefault("by_type", {})
        if question_type not in by_type:
            by_type[question_type] = {"wins": 0, "total": 0, "rate": 0.0}
        ts = by_type[question_type]
        ts["total"] += 1
        if won:
            ts["wins"] += 1
        ts["rate"] = ts["wins"] / ts["total"] if ts["total"] > 0 else 0.0

    def get_dimensions(self) -> Dict[str, str]:
        """返回 7 个维度的当前值"""
        return {d: getattr(self, d) for d in STRATEGY_DIMENSIONS}

    def to_dict(self) -> Dict[str, Any]:
        """QP-013: 序列化"""
        return {
            "id": self.id,
            "name": self.name,
            "island_id": self.island_id,
            "hypothesis_framing": self.hypothesis_framing,
            "query_policy": self.query_policy,
            "evidence_source": self.evidence_source,
            "retrieval_depth": self.retrieval_depth,
            "update_policy": self.update_policy,
            "audit_policy": self.audit_policy,
            "termination_policy": self.termination_policy,
            "max_turns": self.max_turns,
            "parent_id": self.parent_id,
            "iteration_found": self.iteration_found,
            "metrics": copy.deepcopy(self.metrics),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "StrategyDefinition":
        """QP-013: 反序列化"""
        return cls(
            id=data.get("id", ""),
            name=data.get("name", ""),
            island_id=data.get("island_id", ""),
            hypothesis_framing=data.get("hypothesis_framing", "news_tracking"),
            query_policy=data.get("query_policy", "broad_diverse"),
            evidence_source=data.get("evidence_source", "news_wire"),
            retrieval_depth=data.get("retrieval_depth", "medium"),
            update_policy=data.get("update_policy", "moderate"),
            audit_policy=data.get("audit_policy", "none"),
            termination_policy=data.get("termination_policy", "confidence_threshold"),
            max_turns=data.get("max_turns", 100),
            parent_id=data.get("parent_id"),
            iteration_found=data.get("iteration_found", 0),
            metrics=data.get("metrics", {
                "overall": {"wins": 0, "total": 0, "rate": 0.0},
                "by_type": {},
            }),
        )


def strategy_distance(a: StrategyDefinition, b: StrategyDefinition) -> float:
    """QP-210: 计算两个策略的维度距离

    维度差异数 / 总维度数（7 维），归一化到 [0, 1]。
    0 = 完全相同, 1 = 所有维度都不同。
    """
    diff = sum(
        1 for d in STRATEGY_DIMENSIONS
        if getattr(a, d) != getattr(b, d)
    )
    return diff / len(STRATEGY_DIMENSIONS)
