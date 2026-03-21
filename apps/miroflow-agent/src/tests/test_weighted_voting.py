# Copyright 2026 EvoAgent Contributors
# SPDX-License-Identifier: MIT
"""
Tests for WV (Weighted Voting & Strategy Evaluation) module.

Covers:
- WV-401: record_result 更新正确性
- WV-402: get_fitness 优先级逻辑
- WV-403: 权重映射
- WV-404: 加权投票计算
- WV-405: 共识判定
- WV-406: 答案归一化
- WV-407: 向后兼容降级
- WV-408: VoteResult 元数据
- WV-409: 5 路径加权投票端到端
- WV-410: Judge 带证据仲裁
- WV-411: 题型统计积累
- WV-412: fitness 与 island 对接
- WV-413: 回归测试 — 现有投票测试适配
- WV-415/416: 性能测试
"""

import asyncio
import time
from unittest.mock import AsyncMock

import pytest

from src.core.weighted_voting import (
    CONFIDENCE_WEIGHTS,
    CONSENSUS_THRESHOLD,
    DEFAULT_FITNESS,
    MIN_TYPE_SAMPLES,
    PathVoteInput,
    StrategyMetrics,
    StructuredOutput,
    VoteResult,
    get_fitness,
    get_weight,
    normalize_answer,
    parse_confidence,
    parse_evidence,
    parse_risk,
    parse_structured_output,
    record_result,
    weighted_majority_vote,
    weighted_vote,
    judge_with_evidence,
    STRUCTURED_OUTPUT_INSTRUCTION,
    COMBINED_TRACE_AND_OUTPUT_INSTRUCTION,
)


# ════════════════════════════════════════════════════════════
#  WV-401: record_result 更新正确性
# ════════════════════════════════════════════════════════════


class TestRecordResult:
    """WV-401: 验证 overall 和 by_type 统计在各种输入下正确更新。"""

    def test_single_win(self):
        metrics = StrategyMetrics()
        record_result("s1", "island1", "politics", won=True, adopted=True, metrics=metrics)
        assert metrics.overall["total"] == 1
        assert metrics.overall["wins"] == 1
        assert metrics.overall["rate"] == 1.0
        assert metrics.by_type["politics"]["total"] == 1
        assert metrics.by_type["politics"]["wins"] == 1
        assert metrics.by_type["politics"]["rate"] == 1.0

    def test_single_loss(self):
        metrics = StrategyMetrics()
        record_result("s1", "island1", "sports", won=False, adopted=False, metrics=metrics)
        assert metrics.overall["total"] == 1
        assert metrics.overall["wins"] == 0
        assert metrics.overall["rate"] == 0.0
        assert metrics.by_type["sports"]["total"] == 1
        assert metrics.by_type["sports"]["wins"] == 0

    def test_multiple_types(self):
        metrics = StrategyMetrics()
        record_result("s1", "i1", "politics", won=True, adopted=True, metrics=metrics)
        record_result("s1", "i1", "sports", won=False, adopted=False, metrics=metrics)
        record_result("s1", "i1", "politics", won=True, adopted=True, metrics=metrics)
        assert metrics.overall["total"] == 3
        assert metrics.overall["wins"] == 2
        assert abs(metrics.overall["rate"] - 2 / 3) < 1e-9
        assert metrics.by_type["politics"]["total"] == 2
        assert metrics.by_type["politics"]["wins"] == 2
        assert metrics.by_type["politics"]["rate"] == 1.0
        assert metrics.by_type["sports"]["total"] == 1
        assert metrics.by_type["sports"]["wins"] == 0

    def test_adopted_vs_won_independent(self):
        """WV-DD-10: adopted 和 won 独立记录。"""
        metrics = StrategyMetrics()
        # adopted but didn't win (final answer was wrong)
        record_result("s1", "i1", "tech", won=False, adopted=True, metrics=metrics)
        assert metrics.overall["wins"] == 0
        assert metrics.overall["total"] == 1

    def test_twenty_consecutive_records(self):
        """验收标准: record_result 连续调用 20 次统计正确。"""
        metrics = StrategyMetrics()
        wins = 0
        for i in range(20):
            won = i % 3 == 0  # wins on 0, 3, 6, 9, 12, 15, 18 → 7 wins
            if won:
                wins += 1
            record_result("s1", "i1", "finance", won=won, adopted=True, metrics=metrics)
        assert metrics.overall["total"] == 20
        assert metrics.overall["wins"] == wins
        assert abs(metrics.overall["rate"] - wins / 20) < 1e-9
        assert metrics.by_type["finance"]["total"] == 20


# ════════════════════════════════════════════════════════════
#  WV-402: get_fitness 优先级逻辑
# ════════════════════════════════════════════════════════════


class TestGetFitness:
    """WV-402: 样本≥3 用题型胜率；样本<3 退回全局；全零返回 0.5。"""

    def test_zero_samples_returns_default(self):
        """WV-007: overall.total == 0 时返回 0.5。"""
        metrics = StrategyMetrics()
        assert get_fitness(metrics) == DEFAULT_FITNESS
        assert get_fitness(metrics, "politics") == DEFAULT_FITNESS

    def test_type_samples_sufficient(self):
        """样本 ≥ 3 时返回题型胜率。"""
        metrics = StrategyMetrics()
        for _ in range(3):
            record_result("s1", "i1", "politics", won=True, adopted=True, metrics=metrics)
        record_result("s1", "i1", "politics", won=False, adopted=True, metrics=metrics)
        # politics: 3/4 = 0.75
        assert abs(get_fitness(metrics, "politics") - 0.75) < 1e-9

    def test_type_samples_insufficient_fallback(self):
        """样本 < 3 时退回全局胜率。"""
        metrics = StrategyMetrics()
        record_result("s1", "i1", "politics", won=True, adopted=True, metrics=metrics)
        record_result("s1", "i1", "politics", won=True, adopted=True, metrics=metrics)
        # politics has 2 samples (< 3), should use overall rate
        record_result("s1", "i1", "sports", won=False, adopted=False, metrics=metrics)
        record_result("s1", "i1", "sports", won=False, adopted=False, metrics=metrics)
        # overall: 2/4 = 0.5, politics: 2/2 but insufficient
        assert abs(get_fitness(metrics, "politics") - 0.5) < 1e-9

    def test_no_question_type_returns_overall(self):
        """question_type=None 时直接返回全局胜率。"""
        metrics = StrategyMetrics()
        for _ in range(5):
            record_result("s1", "i1", "tech", won=True, adopted=True, metrics=metrics)
        assert get_fitness(metrics) == 1.0

    def test_unknown_question_type_fallback(self):
        """未知题型退回全局。"""
        metrics = StrategyMetrics()
        record_result("s1", "i1", "politics", won=True, adopted=True, metrics=metrics)
        assert abs(get_fitness(metrics, "nonexistent") - 1.0) < 1e-9


# ════════════════════════════════════════════════════════════
#  WV-403: 权重映射
# ════════════════════════════════════════════════════════════


class TestWeightMapping:
    """WV-403: high→3, medium→2, low→1, 未知→1。"""

    def test_high(self):
        assert get_weight("high") == 3

    def test_medium(self):
        assert get_weight("medium") == 2

    def test_low(self):
        assert get_weight("low") == 1

    def test_unknown_defaults_to_1(self):
        """WV-108: 未知置信度默认权重 1。"""
        assert get_weight("unknown") == 1
        assert get_weight("") == 1

    def test_case_insensitive(self):
        assert get_weight("HIGH") == 3
        assert get_weight("Medium") == 2
        assert get_weight("LOW") == 1

    def test_constants(self):
        assert CONFIDENCE_WEIGHTS == {"high": 3, "medium": 2, "low": 1}


# ════════════════════════════════════════════════════════════
#  WV-404: 加权投票计算
# ════════════════════════════════════════════════════════════


class TestWeightedMajorityVote:
    """WV-404: 5 路径加权后答案累计正确性。"""

    def test_five_paths_weighted(self):
        """验收标准: 3×high选A + 2×medium选B → A胜 (9 vs 4)。"""
        inputs = [
            PathVoteInput(path_index=0, answer="A", confidence="high", strategy_name="s0"),
            PathVoteInput(path_index=1, answer="B", confidence="medium", strategy_name="s1"),
            PathVoteInput(path_index=2, answer="A", confidence="high", strategy_name="s2"),
            PathVoteInput(path_index=3, answer="B", confidence="medium", strategy_name="s3"),
            PathVoteInput(path_index=4, answer="A", confidence="high", strategy_name="s4"),
        ]
        result, needs_judge = weighted_majority_vote(inputs)
        assert result is not None
        assert normalize_answer(result.winner_answer) == "a"
        assert result.total_weight == 13  # 3*3 + 2*2
        assert not needs_judge  # 9/13 ≈ 0.69 > 0.6

    def test_empty_inputs(self):
        result, needs_judge = weighted_majority_vote([])
        assert result is None
        assert not needs_judge

    def test_single_input(self):
        inputs = [PathVoteInput(path_index=0, answer="X", confidence="low")]
        result, needs_judge = weighted_majority_vote(inputs)
        assert result is not None
        assert result.winner_answer == "X"
        assert result.consensus_ratio == 1.0
        assert not needs_judge

    def test_all_same_answer(self):
        inputs = [
            PathVoteInput(path_index=i, answer="Yes", confidence="medium")
            for i in range(3)
        ]
        result, needs_judge = weighted_majority_vote(inputs)
        assert result is not None
        assert result.consensus_ratio == 1.0
        assert not needs_judge


# ════════════════════════════════════════════════════════════
#  WV-405: 共识判定
# ════════════════════════════════════════════════════════════


class TestConsensusJudgment:
    """WV-405: 权重占比 > 0.6 → 共识；≤ 0.6 → 分裂。"""

    def test_clear_consensus(self):
        """3 high for A, 1 low for B → 9/10 > 0.6 → consensus."""
        inputs = [
            PathVoteInput(path_index=0, answer="A", confidence="high"),
            PathVoteInput(path_index=1, answer="A", confidence="high"),
            PathVoteInput(path_index=2, answer="A", confidence="high"),
            PathVoteInput(path_index=3, answer="B", confidence="low"),
        ]
        result, needs_judge = weighted_majority_vote(inputs)
        assert not needs_judge
        assert result.consensus_ratio == 9 / 10

    def test_split_vote(self):
        """2 medium for A, 2 medium for B → 4/8 = 0.5 ≤ 0.6 → split."""
        inputs = [
            PathVoteInput(path_index=0, answer="A", confidence="medium"),
            PathVoteInput(path_index=1, answer="A", confidence="medium"),
            PathVoteInput(path_index=2, answer="B", confidence="medium"),
            PathVoteInput(path_index=3, answer="B", confidence="medium"),
        ]
        result, needs_judge = weighted_majority_vote(inputs)
        assert needs_judge
        assert result.consensus_ratio == 0.5

    def test_exactly_at_threshold(self):
        """Exactly 0.6 → split (≤ 0.6)."""
        # 3 weight for A, 2 weight for B → 3/5 = 0.6 → split
        inputs = [
            PathVoteInput(path_index=0, answer="A", confidence="high"),    # 3
            PathVoteInput(path_index=1, answer="B", confidence="medium"),  # 2
        ]
        result, needs_judge = weighted_majority_vote(inputs)
        assert needs_judge
        assert result.consensus_ratio == 0.6

    def test_just_above_threshold(self):
        """Just above 0.6 → consensus."""
        # 7 for A, 4 for B → 7/11 ≈ 0.636 > 0.6 → consensus
        inputs = [
            PathVoteInput(path_index=0, answer="A", confidence="high"),    # 3
            PathVoteInput(path_index=1, answer="A", confidence="medium"),  # 2
            PathVoteInput(path_index=2, answer="A", confidence="medium"),  # 2
            PathVoteInput(path_index=3, answer="B", confidence="medium"),  # 2
            PathVoteInput(path_index=4, answer="B", confidence="medium"),  # 2
        ]
        result, needs_judge = weighted_majority_vote(inputs)
        assert not needs_judge
        assert abs(result.consensus_ratio - 7 / 11) < 1e-9


# ════════════════════════════════════════════════════════════
#  WV-406: 答案归一化
# ════════════════════════════════════════════════════════════


class TestAnswerNormalization:
    """WV-406: strip/lower/格式差异消除。"""

    def test_strip_whitespace(self):
        assert normalize_answer("  hello  ") == "hello"

    def test_lowercase(self):
        assert normalize_answer("YES") == "yes"

    def test_boxed_removal(self):
        assert normalize_answer("\\boxed{42}") == "42"

    def test_boxed_with_surrounding_text(self):
        assert normalize_answer("答案是 \\boxed{A} 无疑") == "a"

    def test_punctuation_removal(self):
        assert normalize_answer("Yes!") == "yes"

    def test_combined_normalization(self):
        """Different formats of same answer normalize to same string."""
        assert normalize_answer("\\boxed{Yes}") == normalize_answer("  yes  ")
        assert normalize_answer("YES!") == normalize_answer("yes")


# ════════════════════════════════════════════════════════════
#  WV-407: 向后兼容降级
# ════════════════════════════════════════════════════════════


class TestBackwardCompatibility:
    """WV-407: 无 confidence 时等同简单多数投票。"""

    def test_no_confidence_defaults_medium(self):
        """PathVoteInput 默认 confidence='medium'。"""
        inp = PathVoteInput(path_index=0, answer="X")
        assert inp.confidence == "medium"

    def test_equal_weights_simple_majority(self):
        """所有 confidence='medium' → 等权 → 简单多数投票行为。"""
        inputs = [
            PathVoteInput(path_index=0, answer="A", confidence="medium"),
            PathVoteInput(path_index=1, answer="A", confidence="medium"),
            PathVoteInput(path_index=2, answer="B", confidence="medium"),
        ]
        result, _ = weighted_majority_vote(inputs)
        assert result is not None
        assert normalize_answer(result.winner_answer) == "a"
        # A: 4 weight, B: 2 weight → 4/6 = 0.667 > 0.6 → consensus
        assert result.total_weight == 6

    def test_unknown_confidence_weight_1(self):
        """未知 confidence 给权重 1，退化为每票等权。"""
        inputs = [
            PathVoteInput(path_index=0, answer="X", confidence="unknown_value"),
            PathVoteInput(path_index=1, answer="X", confidence=""),
            PathVoteInput(path_index=2, answer="Y", confidence="whatever"),
        ]
        result, _ = weighted_majority_vote(inputs)
        assert result is not None
        assert normalize_answer(result.winner_answer) == "x"
        assert result.total_weight == 3  # all weight 1


# ════════════════════════════════════════════════════════════
#  WV-408: VoteResult 元数据
# ════════════════════════════════════════════════════════════


class TestVoteResultMetadata:
    """WV-408: 返回结果包含完整投票元信息。"""

    def test_result_fields(self):
        inputs = [
            PathVoteInput(path_index=0, answer="A", confidence="high", strategy_name="breadth_first"),
            PathVoteInput(path_index=1, answer="B", confidence="low", strategy_name="depth_first"),
        ]
        result, _ = weighted_majority_vote(inputs)
        assert result is not None
        assert result.winner_answer == "A"
        assert result.winner_path_index == 0
        assert result.winner_strategy == "breadth_first"
        assert result.method == "weighted_majority"
        assert result.total_weight == 4  # 3 + 1
        assert result.consensus_ratio == 3 / 4
        assert not result.judge_used

    def test_weight_distribution_contents(self):
        inputs = [
            PathVoteInput(path_index=0, answer="A", confidence="high"),
            PathVoteInput(path_index=1, answer="A", confidence="medium"),
            PathVoteInput(path_index=2, answer="B", confidence="low"),
        ]
        result, _ = weighted_majority_vote(inputs)
        dist = result.weight_distribution
        # Normalized answers are keys
        assert "a" in dist
        assert "b" in dist
        assert dist["a"]["weight"] == 5  # 3 + 2
        assert dist["b"]["weight"] == 1
        assert 0 in dist["a"]["paths"]
        assert 1 in dist["a"]["paths"]


# ════════════════════════════════════════════════════════════
#  WV-409: 5 路径加权投票端到端
# ════════════════════════════════════════════════════════════


class TestEndToEndVoting:
    """WV-409: 构造 5 个 PathVoteInput → weighted_vote → 验证结果。"""

    @pytest.mark.asyncio
    async def test_five_path_e2e_consensus(self):
        inputs = [
            PathVoteInput(0, "Answer A", "high", "s0", "summary0", ["evidence0"], "risk0"),
            PathVoteInput(1, "Answer B", "medium", "s1", "summary1", ["evidence1"], "risk1"),
            PathVoteInput(2, "answer a", "high", "s2", "summary2", ["evidence2"], "risk2"),
            PathVoteInput(3, "Answer A", "medium", "s3", "summary3", [], ""),
            PathVoteInput(4, "Answer B", "low", "s4", "summary4", [], ""),
        ]
        result = await weighted_vote(inputs, "test question")
        assert result is not None
        # A: 3+3+2=8, B: 2+1=3 → 8/11 > 0.6 → consensus
        assert normalize_answer(result.winner_answer) == "answer a"
        assert result.method == "weighted_majority"
        assert not result.judge_used

    @pytest.mark.asyncio
    async def test_five_path_e2e_split_with_judge(self):
        """分裂场景触发 Judge。"""
        inputs = [
            PathVoteInput(0, "A", "medium", "s0"),
            PathVoteInput(1, "B", "medium", "s1"),
            PathVoteInput(2, "A", "low", "s2"),
            PathVoteInput(3, "B", "medium", "s3"),
            PathVoteInput(4, "C", "medium", "s4"),
        ]

        # Mock judge that picks answer B (path 2 = index 2 in judge numbering)
        async def mock_judge(prompt):
            return "BEST: 2\nReason: B has better evidence"

        result = await weighted_vote(inputs, "test", judge_callable=mock_judge)
        assert result.method == "judge"
        assert result.judge_used

    @pytest.mark.asyncio
    async def test_five_path_e2e_no_judge_callable(self):
        """分裂但无 judge_callable → 返回 majority 结果。"""
        inputs = [
            PathVoteInput(0, "A", "medium"),
            PathVoteInput(1, "B", "medium"),
        ]
        result = await weighted_vote(inputs, "test", judge_callable=None)
        assert result.method == "weighted_majority"


# ════════════════════════════════════════════════════════════
#  WV-410: Judge 带证据仲裁
# ════════════════════════════════════════════════════════════


class TestJudgeWithEvidence:
    """WV-410: 分裂场景 → Judge 收到 confidence + evidence + risk → 输出选择。"""

    @pytest.mark.asyncio
    async def test_judge_picks_best(self):
        inputs = [
            PathVoteInput(0, "A", "high", "s0", "summary", ["ev1", "ev2"], "risk1"),
            PathVoteInput(1, "B", "low", "s1", "summary2", ["ev3"], "risk2"),
        ]

        async def mock_judge(prompt):
            # Verify prompt contains evidence and risk
            assert "ev1" in prompt
            assert "risk2" in prompt
            return "BEST: 1\nReason: Answer A has better evidence quality"

        result = await judge_with_evidence(inputs, "test q", mock_judge)
        assert result.winner_answer == "A"
        assert result.method == "judge"
        assert result.judge_used
        assert "better evidence" in result.judge_reason

    @pytest.mark.asyncio
    async def test_judge_failure_fallback(self):
        """Judge 失败时退回第一个。"""
        inputs = [
            PathVoteInput(0, "A", "medium"),
            PathVoteInput(1, "B", "high"),
        ]

        async def failing_judge(prompt):
            raise RuntimeError("LLM error")

        result = await judge_with_evidence(inputs, "test", failing_judge)
        assert result.winner_answer == "A"  # Falls back to first
        assert "failed" in result.judge_reason.lower()


# ════════════════════════════════════════════════════════════
#  WV-411: 题型统计积累
# ════════════════════════════════════════════════════════════


class TestTypeStatsAccumulation:
    """WV-411: 连续 10 次 record_result → 验证题型胜率准确。"""

    def test_ten_records_accuracy(self):
        metrics = StrategyMetrics()
        # 10 records: 7 wins for politics
        for i in range(10):
            record_result("s1", "i1", "politics", won=(i < 7), adopted=True, metrics=metrics)
        assert metrics.by_type["politics"]["total"] == 10
        assert metrics.by_type["politics"]["wins"] == 7
        assert abs(metrics.by_type["politics"]["rate"] - 0.7) < 1e-9
        assert abs(get_fitness(metrics, "politics") - 0.7) < 1e-9

    def test_multi_type_tracking(self):
        metrics = StrategyMetrics()
        # 5 politics (4 wins), 5 sports (1 win)
        for i in range(5):
            record_result("s1", "i1", "politics", won=(i < 4), adopted=True, metrics=metrics)
            record_result("s1", "i1", "sports", won=(i == 0), adopted=True, metrics=metrics)
        assert abs(get_fitness(metrics, "politics") - 0.8) < 1e-9
        assert abs(get_fitness(metrics, "sports") - 0.2) < 1e-9
        # Overall: 5 wins / 10 total = 0.5
        assert abs(get_fitness(metrics) - 0.5) < 1e-9


# ════════════════════════════════════════════════════════════
#  WV-412: fitness 与 island 对接
# ════════════════════════════════════════════════════════════


class TestFitnessIslandIntegration:
    """WV-412: get_fitness → StrategyIsland.elite_score 链路。"""

    def test_metrics_compatible_with_strategy_definition(self):
        """StrategyMetrics 结构与 StrategyDefinition.metrics 兼容。"""
        from src.core.strategy_definition import StrategyDefinition

        sd = StrategyDefinition(id="s1", name="test")
        # StrategyDefinition has metrics field with same structure
        sm = StrategyMetrics.from_dict(sd.metrics)
        assert sm.overall["total"] == 0
        assert sm.overall["wins"] == 0

    def test_fitness_with_strategy_island_record(self):
        """WV fitness matches StrategyIsland.fitness behavior."""
        from src.core.strategy_island import StrategyIsland, IslandConfig, StrategyRecord
        from src.core.strategy_definition import StrategyDefinition

        config = IslandConfig(name="test", perspective="test")
        island = StrategyIsland(config)
        sd = StrategyDefinition(id="s1", name="test")
        island.add_strategy(sd)
        rec = island.get_record(sd)

        # Record some results via island
        for i in range(5):
            rec.record_result("politics", won=(i < 3))

        # WV get_fitness should give same result as island.fitness
        wv_metrics = StrategyMetrics()
        for i in range(5):
            record_result("s1", "i1", "politics", won=(i < 3), adopted=True, metrics=wv_metrics)

        wv_fit = get_fitness(wv_metrics, "politics")
        island_fit = island.fitness(rec, "politics")
        assert abs(wv_fit - island_fit) < 1e-9


# ════════════════════════════════════════════════════════════
#  WV-413: 回归测试 — 现有投票测试适配
# ════════════════════════════════════════════════════════════


class TestRegressionWithExistingVoting:
    """WV-413: WV 模块加入后现有行为不变。"""

    def test_simple_majority_still_works(self):
        """等权投票（所有 medium）行为与简单多数投票一致。"""
        inputs = [
            PathVoteInput(path_index=0, answer="42", confidence="medium"),
            PathVoteInput(path_index=1, answer="42", confidence="medium"),
            PathVoteInput(path_index=2, answer="43", confidence="medium"),
        ]
        result, _ = weighted_majority_vote(inputs)
        assert normalize_answer(result.winner_answer) == "42"

    def test_all_different_triggers_split(self):
        """所有答案不同 → 需要 Judge。"""
        inputs = [
            PathVoteInput(0, "A", "medium"),
            PathVoteInput(1, "B", "medium"),
            PathVoteInput(2, "C", "medium"),
        ]
        result, needs_judge = weighted_majority_vote(inputs)
        # Each has 2/6 ≈ 0.33 ≤ 0.6 → split
        assert needs_judge


# ════════════════════════════════════════════════════════════
#  Structured Output Parsing Tests
# ════════════════════════════════════════════════════════════


class TestStructuredOutputParsing:
    """WV-204/206/207: 结构化输出解析。"""

    def test_full_structured_output(self):
        text = """
答案：\\boxed{A}
置信度：high
关键证据：[来源1: 摘要1, 来源2: 摘要2]
主要风险：数据可能过时
"""
        result = parse_structured_output(text)
        assert result.answer == "A"
        assert result.confidence == "high"
        assert len(result.evidence) == 2
        assert result.risk == "数据可能过时"

    def test_missing_fields_defaults(self):
        """WV-207: 缺失字段使用默认值。"""
        result = parse_structured_output("some random text")
        assert result.answer == ""
        assert result.confidence == "medium"
        assert result.evidence == []
        assert result.risk == ""

    def test_confidence_parsing(self):
        assert parse_confidence("置信度：high") == "high"
        assert parse_confidence("置信度：low") == "low"
        assert parse_confidence("confidence: medium") == "medium"
        assert parse_confidence("no confidence here") == "medium"

    def test_evidence_parsing(self):
        ev = parse_evidence("关键证据：[CNN: 报道A, BBC: 报道B]")
        assert len(ev) == 2
        assert "CNN: 报道A" in ev[0]

    def test_risk_parsing(self):
        assert parse_risk("主要风险：可能有偏差") == "可能有偏差"
        assert parse_risk("no risk line") == ""


class TestPromptTemplates:
    """WV-201/203: Prompt 模板存在且非空。"""

    def test_structured_output_instruction_exists(self):
        assert "\\boxed" in STRUCTURED_OUTPUT_INSTRUCTION
        assert "置信度" in STRUCTURED_OUTPUT_INSTRUCTION

    def test_combined_instruction_exists(self):
        assert "\\boxed" in COMBINED_TRACE_AND_OUTPUT_INSTRUCTION
        assert "conclusion" in COMBINED_TRACE_AND_OUTPUT_INSTRUCTION


# ════════════════════════════════════════════════════════════
#  Serialization Tests
# ════════════════════════════════════════════════════════════


class TestSerialization:
    """WV-008: StrategyMetrics 序列化。"""

    def test_round_trip(self):
        metrics = StrategyMetrics()
        record_result("s1", "i1", "politics", won=True, adopted=True, metrics=metrics)
        record_result("s1", "i1", "sports", won=False, adopted=False, metrics=metrics)

        data = metrics.to_dict()
        restored = StrategyMetrics.from_dict(data)
        assert restored.overall == metrics.overall
        assert restored.by_type == metrics.by_type

    def test_empty_round_trip(self):
        metrics = StrategyMetrics()
        restored = StrategyMetrics.from_dict(metrics.to_dict())
        assert restored.overall["total"] == 0


# ════════════════════════════════════════════════════════════
#  WV-415/416: 性能测试
# ════════════════════════════════════════════════════════════


class TestPerformance:
    """WV-415/416: 性能测试。"""

    def test_voting_overhead_under_1ms(self):
        """WV-415: 加权投票 vs 简单多数投票延迟差 < 1ms。"""
        inputs = [
            PathVoteInput(i, f"Answer{i % 3}", ["high", "medium", "low"][i % 3])
            for i in range(5)
        ]
        t0 = time.perf_counter()
        for _ in range(1000):
            weighted_majority_vote(inputs)
        elapsed = (time.perf_counter() - t0) / 1000
        assert elapsed < 0.001  # < 1ms per call

    def test_record_result_under_5ms(self):
        """WV-416: 单次 record_result 耗时 < 5ms。"""
        metrics = StrategyMetrics()
        t0 = time.perf_counter()
        for i in range(1000):
            record_result("s1", "i1", "politics", won=(i % 2 == 0), adopted=True, metrics=metrics)
        elapsed = (time.perf_counter() - t0) / 1000
        assert elapsed < 0.005  # < 5ms per call
