# Copyright 2026 EvoAgent Contributors
# SPDX-License-Identifier: MIT
"""
StrategyCompiler 单元测试 — QP-407, QP-409, QP-410.

测试 compile_strategy() 输出格式、种子策略完整性和多样性。
"""

import pytest
from src.core.strategy_compiler import (
    compile_strategy,
    StrategyCompiler,
    TEMPLATES,
    FRAMING_TEMPLATES,
    QUERY_TEMPLATES,
    EVIDENCE_TEMPLATES,
    RETRIEVAL_TEMPLATES,
    UPDATE_TEMPLATES,
    AUDIT_TEMPLATES,
    TERMINATION_TEMPLATES,
)
from src.core.strategy_definition import (
    StrategyDefinition,
    strategy_distance,
    STRATEGY_DIMENSIONS,
)
from src.core.seed_strategies import (
    SEED_STRATEGIES,
    SEED_NEWS_EXPERT,
    SEED_MECHANISM_EXPERT,
    SEED_HISTORICAL_EXPERT,
    SEED_MARKET_EXPERT,
    SEED_COUNTERFACTUAL_EXPERT,
)


class TestTemplatesMasterDict:
    """QP-201: 测试 TEMPLATES 主字典"""

    def test_templates_has_all_dimensions(self):
        """TEMPLATES 应包含所有 7 个维度"""
        for dim in STRATEGY_DIMENSIONS:
            assert dim in TEMPLATES, f"Missing dimension: {dim}"

    def test_templates_maps_to_correct_dicts(self):
        """TEMPLATES 应映射到正确的模板字典"""
        assert TEMPLATES["hypothesis_framing"] is FRAMING_TEMPLATES
        assert TEMPLATES["query_policy"] is QUERY_TEMPLATES
        assert TEMPLATES["evidence_source"] is EVIDENCE_TEMPLATES
        assert TEMPLATES["retrieval_depth"] is RETRIEVAL_TEMPLATES
        assert TEMPLATES["update_policy"] is UPDATE_TEMPLATES
        assert TEMPLATES["audit_policy"] is AUDIT_TEMPLATES
        assert TEMPLATES["termination_policy"] is TERMINATION_TEMPLATES

    def test_templates_count(self):
        """TEMPLATES 应恰好有 7 个维度"""
        assert len(TEMPLATES) == 7


class TestCompileStrategyOutput:
    """QP-407: 测试 compile_strategy() 输出格式正确"""

    def test_output_has_required_keys(self):
        """编译输出应包含 name, prompt_suffix, max_turns"""
        sd = StrategyDefinition(id="test_v1", name="测试", max_turns=100)
        result = compile_strategy(sd)
        assert "name" in result
        assert "prompt_suffix" in result
        assert "max_turns" in result

    def test_output_has_description(self):
        """编译输出应包含 description"""
        sd = StrategyDefinition(id="test_v1", name="测试策略")
        result = compile_strategy(sd)
        assert "description" in result
        assert result["description"] == "测试策略"

    def test_output_has_strategy_def(self):
        """编译输出应包含 _strategy_def 引用"""
        sd = StrategyDefinition(id="test_v1", name="测试")
        result = compile_strategy(sd)
        assert "_strategy_def" in result
        assert result["_strategy_def"] is sd

    def test_output_name_is_strategy_id(self):
        """编译输出的 name 应为策略 id"""
        sd = StrategyDefinition(id="my_strategy_v1", name="我的策略")
        result = compile_strategy(sd)
        assert result["name"] == "my_strategy_v1"

    def test_output_max_turns(self):
        """编译输出的 max_turns 应与策略定义一致"""
        sd = StrategyDefinition(id="test", max_turns=200)
        result = compile_strategy(sd)
        assert result["max_turns"] == 200

    def test_prompt_suffix_contains_all_dimensions(self):
        """prompt_suffix 应包含所有 7 个维度的模板内容"""
        sd = SEED_NEWS_EXPERT
        result = compile_strategy(sd)
        suffix = result["prompt_suffix"]
        # Should contain content from each dimension's template
        assert "信息追踪" in suffix  # framing
        assert "搜索策略" in suffix  # query
        assert "证据来源" in suffix  # evidence
        assert "搜索深度" in suffix  # retrieval
        assert "更新策略" in suffix  # update
        assert "自审策略" in suffix  # audit
        assert "停止条件" in suffix  # termination

    def test_prompt_suffix_contains_strategy_name(self):
        """prompt_suffix 应包含策略名称"""
        sd = StrategyDefinition(id="test", name="我的策略")
        result = compile_strategy(sd)
        assert "我的策略" in result["prompt_suffix"]

    def test_compile_compatible_with_strategy_variants_format(self):
        """QP-303: 编译输出应兼容 STRATEGY_VARIANTS dict 格式"""
        sd = SEED_NEWS_EXPERT
        result = compile_strategy(sd)
        # Must have the same keys as STRATEGY_VARIANTS entries
        assert isinstance(result["name"], str)
        assert isinstance(result["prompt_suffix"], str)
        assert isinstance(result["max_turns"], int)
        assert len(result["name"]) > 0
        assert len(result["prompt_suffix"]) > 0
        assert result["max_turns"] > 0


class TestSeedStrategies:
    """QP-409: 测试 5 个种子策略完整性"""

    def test_five_seed_strategies_exist(self):
        """应恰好有 5 个种子策略"""
        assert len(SEED_STRATEGIES) == 5

    def test_all_seeds_have_unique_ids(self):
        """所有种子策略的 id 应唯一"""
        ids = [s.id for s in SEED_STRATEGIES]
        assert len(ids) == len(set(ids))

    def test_all_seeds_have_unique_names(self):
        """所有种子策略的 name 应唯一"""
        names = [s.name for s in SEED_STRATEGIES]
        assert len(names) == len(set(names))

    def test_all_seeds_compile_successfully(self):
        """所有种子策略都应能成功编译"""
        for seed in SEED_STRATEGIES:
            result = compile_strategy(seed)
            assert "name" in result
            assert "prompt_suffix" in result
            assert "max_turns" in result
            assert len(result["prompt_suffix"]) > 100  # Should have substantial content

    def test_all_seeds_have_valid_dimensions(self):
        """所有种子策略的维度值应在模板中存在"""
        for seed in SEED_STRATEGIES:
            for dim in STRATEGY_DIMENSIONS:
                dim_value = getattr(seed, dim)
                assert dim_value in TEMPLATES[dim], (
                    f"Seed {seed.id}: dimension {dim}={dim_value} not in templates"
                )

    def test_all_seeds_have_island_ids(self):
        """所有种子策略都应有 island_id"""
        for seed in SEED_STRATEGIES:
            assert seed.island_id, f"Seed {seed.id} missing island_id"

    def test_seed_strategies_expected_ids(self):
        """种子策略应包含预期的 id"""
        ids = {s.id for s in SEED_STRATEGIES}
        expected = {
            "news_expert_v1",
            "mechanism_expert_v1",
            "historical_expert_v1",
            "market_expert_v1",
            "counterfactual_expert_v1",
        }
        assert ids == expected


class TestSeedStrategyDiversity:
    """QP-410: 验证 5 个种子策略之间的距离 > 0.3"""

    def test_all_pairwise_distances_above_threshold(self):
        """所有种子策略两两距离应 > 0.3"""
        for i, a in enumerate(SEED_STRATEGIES):
            for j, b in enumerate(SEED_STRATEGIES):
                if i >= j:
                    continue
                dist = strategy_distance(a, b)
                assert dist > 0.3, (
                    f"Distance between {a.id} and {b.id} is {dist:.3f}, "
                    f"expected > 0.3"
                )

    def test_max_distance_is_meaningful(self):
        """最大两两距离应 >= 0.7（策略足够多样）"""
        max_dist = 0.0
        for i, a in enumerate(SEED_STRATEGIES):
            for j, b in enumerate(SEED_STRATEGIES):
                if i >= j:
                    continue
                dist = strategy_distance(a, b)
                max_dist = max(max_dist, dist)
        assert max_dist >= 0.7, f"Max pairwise distance is {max_dist:.3f}, expected >= 0.7"
