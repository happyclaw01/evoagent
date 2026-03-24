# Copyright 2026 EvoAgent Contributors
# SPDX-License-Identifier: MIT
"""
StrategyDefinition 和 strategy_distance 单元测试 — QP-405, QP-406, QP-408。

测试 StrategyDefinition dataclass 的创建、metrics、序列化和距离计算。
"""

import pytest
import copy
from src.core.strategy_definition import (
    StrategyDefinition,
    strategy_distance,
    STRATEGY_DIMENSIONS,
)


class TestStrategyDefinitionCreation:
    """QP-405: 测试 StrategyDefinition 正确创建、metrics 初始值、get_rate_for_type()"""

    def test_default_creation(self):
        """默认创建应有正确的初始值"""
        sd = StrategyDefinition()
        assert sd.id == ""
        assert sd.name == ""
        assert sd.island_id == ""
        assert sd.hypothesis_framing == "news_tracking"
        assert sd.query_policy == "broad_diverse"
        assert sd.evidence_source == "news_wire"
        assert sd.retrieval_depth == "medium"
        assert sd.update_policy == "moderate"
        assert sd.audit_policy == "none"
        assert sd.termination_policy == "confidence_threshold"
        assert sd.max_turns == 100
        assert sd.parent_id is None
        assert sd.iteration_found == 0

    def test_metrics_initial_values(self):
        """metrics 初始值应为零"""
        sd = StrategyDefinition()
        assert sd.metrics["overall"]["wins"] == 0
        assert sd.metrics["overall"]["total"] == 0
        assert sd.metrics["overall"]["rate"] == 0.0
        assert sd.metrics["by_type"] == {}

    def test_metrics_not_shared(self):
        """不同实例的 metrics 不应共享引用"""
        sd1 = StrategyDefinition()
        sd2 = StrategyDefinition()
        sd1.record_result("politics", True)
        assert sd2.metrics["overall"]["total"] == 0

    def test_creation_with_values(self):
        """传入具体值应正确设置"""
        sd = StrategyDefinition(
            id="test_v1",
            name="测试策略",
            island_id="island_test",
            hypothesis_framing="mechanism_analysis",
            max_turns=200,
        )
        assert sd.id == "test_v1"
        assert sd.name == "测试策略"
        assert sd.hypothesis_framing == "mechanism_analysis"
        assert sd.max_turns == 200

    def test_get_rate_for_type_no_data(self):
        """无数据时 get_rate_for_type 应返回 overall rate (0.0)"""
        sd = StrategyDefinition()
        assert sd.get_rate_for_type("politics") == 0.0

    def test_get_rate_for_type_insufficient_samples(self):
        """样本数不足 min_samples 时应退回 overall rate"""
        sd = StrategyDefinition()
        # 2 个样本 < min_samples(3)
        sd.record_result("politics", True)
        sd.record_result("politics", True)
        # overall rate = 2/2 = 1.0, by_type politics 也是 1.0 但样本不足
        assert sd.get_rate_for_type("politics", min_samples=3) == 1.0  # 退回 overall

    def test_get_rate_for_type_sufficient_samples(self):
        """样本数 >= min_samples 时应返回该题型的 rate"""
        sd = StrategyDefinition()
        sd.record_result("politics", True)
        sd.record_result("politics", False)
        sd.record_result("politics", True)
        sd.record_result("finance", True)  # 增加 overall 分母
        # politics: 2/3 ≈ 0.667, overall: 3/4 = 0.75
        rate = sd.get_rate_for_type("politics", min_samples=3)
        assert abs(rate - 2 / 3) < 1e-9

    def test_record_result_updates_overall(self):
        """record_result 应正确更新 overall 统计"""
        sd = StrategyDefinition()
        sd.record_result("politics", True)
        assert sd.metrics["overall"]["wins"] == 1
        assert sd.metrics["overall"]["total"] == 1
        assert sd.metrics["overall"]["rate"] == 1.0

        sd.record_result("politics", False)
        assert sd.metrics["overall"]["wins"] == 1
        assert sd.metrics["overall"]["total"] == 2
        assert sd.metrics["overall"]["rate"] == 0.5

    def test_record_result_updates_by_type(self):
        """record_result 应正确更新 by_type 统计"""
        sd = StrategyDefinition()
        sd.record_result("politics", True)
        sd.record_result("finance", False)
        assert sd.metrics["by_type"]["politics"]["wins"] == 1
        assert sd.metrics["by_type"]["politics"]["total"] == 1
        assert sd.metrics["by_type"]["politics"]["rate"] == 1.0
        assert sd.metrics["by_type"]["finance"]["wins"] == 0
        assert sd.metrics["by_type"]["finance"]["total"] == 1
        assert sd.metrics["by_type"]["finance"]["rate"] == 0.0

    def test_get_dimensions(self):
        """get_dimensions 应返回 7 个维度的当前值"""
        sd = StrategyDefinition(
            hypothesis_framing="mechanism_analysis",
            query_policy="targeted_authoritative",
        )
        dims = sd.get_dimensions()
        assert len(dims) == 7
        assert dims["hypothesis_framing"] == "mechanism_analysis"
        assert dims["query_policy"] == "targeted_authoritative"
        for d in STRATEGY_DIMENSIONS:
            assert d in dims


class TestStrategyDefinitionSerialization:
    """QP-406: 测试 StrategyDefinition 序列化往返一致性"""

    def test_to_dict(self):
        """to_dict() 应包含所有字段"""
        sd = StrategyDefinition(
            id="test_v1",
            name="测试",
            island_id="island_0",
            max_turns=150,
        )
        d = sd.to_dict()
        assert d["id"] == "test_v1"
        assert d["name"] == "测试"
        assert d["island_id"] == "island_0"
        assert d["max_turns"] == 150
        assert "metrics" in d
        assert "overall" in d["metrics"]

    def test_roundtrip(self):
        """to_dict() → from_dict() 应保持一致"""
        original = StrategyDefinition(
            id="test_v1",
            name="测试策略",
            island_id="island_0",
            hypothesis_framing="counterfactual",
            query_policy="contrarian",
            evidence_source="market_data",
            retrieval_depth="deep",
            update_policy="fast",
            audit_policy="devil_advocate",
            termination_policy="adversarial_stable",
            max_turns=150,
            parent_id="parent_v0",
            iteration_found=3,
        )
        original.record_result("politics", True)
        original.record_result("politics", False)

        restored = StrategyDefinition.from_dict(original.to_dict())
        assert original.to_dict() == restored.to_dict()

    def test_from_dict_with_missing_fields(self):
        """from_dict() 缺少字段时应使用默认值"""
        sd = StrategyDefinition.from_dict({})
        assert sd.id == ""
        assert sd.max_turns == 100
        assert sd.parent_id is None

    def test_to_dict_metrics_deep_copy(self):
        """to_dict() 的 metrics 应是深拷贝"""
        sd = StrategyDefinition()
        sd.record_result("politics", True)
        d = sd.to_dict()
        d["metrics"]["overall"]["wins"] = 999
        assert sd.metrics["overall"]["wins"] == 1  # 原始不受影响


class TestStrategyDistance:
    """QP-408: 测试 strategy_distance 计算"""

    def test_identical_strategies(self):
        """完全相同的策略距离应为 0"""
        a = StrategyDefinition()
        b = StrategyDefinition()
        assert strategy_distance(a, b) == 0.0

    def test_completely_different_strategies(self):
        """所有 7 个维度都不同时距离应为 1"""
        a = StrategyDefinition(
            hypothesis_framing="news_tracking",
            query_policy="broad_diverse",
            evidence_source="news_wire",
            retrieval_depth="shallow",
            update_policy="fast",
            audit_policy="devil_advocate",
            termination_policy="confidence_threshold",
        )
        b = StrategyDefinition(
            hypothesis_framing="counterfactual",
            query_policy="contrarian",
            evidence_source="market_data",
            retrieval_depth="deep",
            update_policy="conservative",
            audit_policy="base_rate_check",
            termination_policy="adversarial_stable",
        )
        assert strategy_distance(a, b) == 1.0

    def test_partial_difference(self):
        """部分维度不同时应返回正确比例"""
        a = StrategyDefinition()
        b = StrategyDefinition(
            hypothesis_framing="counterfactual",  # 1 dim different
        )
        assert abs(strategy_distance(a, b) - 1 / 7) < 1e-9

    def test_three_dimensions_different(self):
        """3 个维度不同时距离应为 3/7"""
        a = StrategyDefinition()
        b = StrategyDefinition(
            hypothesis_framing="counterfactual",
            query_policy="contrarian",
            evidence_source="market_data",
        )
        assert abs(strategy_distance(a, b) - 3 / 7) < 1e-9

    def test_max_turns_not_counted(self):
        """max_turns 不应影响距离计算"""
        a = StrategyDefinition(max_turns=100)
        b = StrategyDefinition(max_turns=200)
        assert strategy_distance(a, b) == 0.0

    def test_symmetry(self):
        """距离应是对称的"""
        a = StrategyDefinition(hypothesis_framing="news_tracking")
        b = StrategyDefinition(hypothesis_framing="counterfactual")
        assert strategy_distance(a, b) == strategy_distance(b, a)
