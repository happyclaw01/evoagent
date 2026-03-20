# Copyright 2026 EvoAgent Contributors
# SPDX-License-Identifier: MIT
"""
Seed Strategies — 5 个初始种子策略常量。

定义 5 个种子策略 (QP-014)，代表 5 种不同的专家视角，
作为策略进化的初始种群。
"""

from .strategy_definition import StrategyDefinition


# ──── QP-014: 5 个初始种子策略 ────

SEED_NEWS_EXPERT = StrategyDefinition(
    id="news_expert_v1",
    name="信息追踪专家",
    island_id="island_0_news",
    hypothesis_framing="news_tracking",
    query_policy="broad_diverse",
    evidence_source="news_wire",
    retrieval_depth="shallow",
    update_policy="fast",
    audit_policy="source_triangulation",
    termination_policy="evidence_saturation",
    max_turns=100,
)

SEED_MECHANISM_EXPERT = StrategyDefinition(
    id="mechanism_expert_v1",
    name="机制分析专家",
    island_id="island_1_mechanism",
    hypothesis_framing="mechanism_analysis",
    query_policy="targeted_authoritative",
    evidence_source="official_data",
    retrieval_depth="deep",
    update_policy="conservative",
    audit_policy="assumption_audit",
    termination_policy="confidence_threshold",
    max_turns=200,
)

SEED_HISTORICAL_EXPERT = StrategyDefinition(
    id="historical_expert_v1",
    name="历史类比专家",
    island_id="island_2_historical",
    hypothesis_framing="historical_analogy",
    query_policy="temporal_sequence",
    evidence_source="academic",
    retrieval_depth="deep",
    update_policy="conservative",
    audit_policy="base_rate_check",
    termination_policy="confidence_threshold",
    max_turns=200,
)

SEED_MARKET_EXPERT = StrategyDefinition(
    id="market_expert_v1",
    name="市场信号专家",
    island_id="island_3_market",
    hypothesis_framing="market_signal",
    query_policy="trend_based",
    evidence_source="market_data",
    retrieval_depth="medium",
    update_policy="fast",
    audit_policy="source_triangulation",
    termination_policy="evidence_saturation",
    max_turns=150,
)

SEED_COUNTERFACTUAL_EXPERT = StrategyDefinition(
    id="counterfactual_expert_v1",
    name="对抗验证专家",
    island_id="island_4_counterfactual",
    hypothesis_framing="counterfactual",
    query_policy="contrarian",
    evidence_source="news_wire",
    retrieval_depth="medium",
    update_policy="moderate",
    audit_policy="devil_advocate",
    termination_policy="adversarial_stable",
    max_turns=150,
)


# 种子策略列表
SEED_STRATEGIES = [
    SEED_NEWS_EXPERT,
    SEED_MECHANISM_EXPERT,
    SEED_HISTORICAL_EXPERT,
    SEED_MARKET_EXPERT,
    SEED_COUNTERFACTUAL_EXPERT,
]
