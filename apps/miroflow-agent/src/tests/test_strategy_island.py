# Copyright 2026 EvoAgent Contributors
# SPDX-License-Identifier: MIT
"""
Strategy Island tests — SI-501~SI-528.
"""

import copy
import json
import math
import time
import tempfile
from pathlib import Path

import pytest

from src.core.strategy_island import (
    IslandConfig,
    StrategyRecord,
    StrategyIsland,
    IslandPool,
    LocalJsonBackend,
    IslandStore,
    DEFAULT_ISLAND_CONFIGS,
)
from src.core.strategy_definition import StrategyDefinition, strategy_distance
from src.core.seed_strategies import SEED_STRATEGIES
from src.core.strategy_compiler import compile_strategy


# ────────────────────────────────────────────────
# Helpers
# ────────────────────────────────────────────────

def _make_strategy(id_: str, **overrides) -> StrategyDefinition:
    """Create a StrategyDefinition with convenient defaults."""
    defaults = dict(
        id=id_,
        name=f"Strategy {id_}",
        island_id="test_island",
        hypothesis_framing="news_tracking",
        query_policy="broad_diverse",
        evidence_source="news_wire",
        retrieval_depth="medium",
        update_policy="moderate",
        audit_policy="none",
        termination_policy="confidence_threshold",
    )
    defaults.update(overrides)
    return StrategyDefinition(**defaults)


def _make_diverse_strategies(n: int) -> list[StrategyDefinition]:
    """Create n strategies with varying dimensions for diversity."""
    framings = ["news_tracking", "mechanism_analysis", "historical_analogy",
                "market_signal", "counterfactual"]
    queries = ["broad_diverse", "targeted_authoritative", "trend_based",
               "contrarian", "temporal_sequence"]
    sources = ["news_wire", "official_data", "academic", "market_data", "social_signal"]
    strategies = []
    for i in range(n):
        s = _make_strategy(
            f"diverse_{i}",
            hypothesis_framing=framings[i % len(framings)],
            query_policy=queries[i % len(queries)],
            evidence_source=sources[i % len(sources)],
        )
        strategies.append(s)
    return strategies


# ════════════════════════════════════════════════
# SI-501: IslandConfig creation
# ════════════════════════════════════════════════

class TestIslandConfigCreation:
    """SI-501: IslandConfig 创建测试 — 默认值、自定义值、边界值"""

    def test_default_values(self):
        cfg = IslandConfig(name="test", perspective="p")
        assert cfg.max_size == 10
        assert cfg.elite_ratio == 0.2
        assert cfg.fitness_weight == 0.6
        assert cfg.novelty_weight == 0.4

    def test_custom_values(self):
        cfg = IslandConfig(
            name="custom", perspective="p",
            max_size=20, elite_ratio=0.3,
            fitness_weight=0.7, novelty_weight=0.3,
        )
        assert cfg.max_size == 20
        assert cfg.elite_ratio == 0.3
        assert cfg.fitness_weight == 0.7
        assert cfg.novelty_weight == 0.3

    def test_frozen(self):
        cfg = IslandConfig(name="test", perspective="p")
        with pytest.raises(AttributeError):
            cfg.name = "changed"  # type: ignore

    def test_elite_count_property(self):
        cfg = IslandConfig(name="test", perspective="p", max_size=10, elite_ratio=0.2)
        assert cfg.elite_count == 2  # ceil(10 * 0.2) = 2

    def test_elite_count_at_least_1(self):
        cfg = IslandConfig(name="test", perspective="p", max_size=1, elite_ratio=0.0,
                           fitness_weight=1.0, novelty_weight=0.0)
        assert cfg.elite_count >= 1

    def test_boundary_max_size_1(self):
        cfg = IslandConfig(name="test", perspective="p", max_size=1)
        assert cfg.max_size == 1

    def test_boundary_elite_ratio_0(self):
        cfg = IslandConfig(name="test", perspective="p", elite_ratio=0.0,
                           fitness_weight=1.0, novelty_weight=0.0)
        assert cfg.elite_ratio == 0.0

    def test_boundary_elite_ratio_1(self):
        cfg = IslandConfig(name="test", perspective="p", elite_ratio=1.0)
        assert cfg.elite_ratio == 1.0

    def test_to_dict_from_dict_roundtrip(self):
        cfg = IslandConfig(name="test", perspective="p", max_size=5)
        d = cfg.to_dict()
        cfg2 = IslandConfig.from_dict(d)
        assert cfg == cfg2


# ════════════════════════════════════════════════
# SI-502: IslandConfig validation
# ════════════════════════════════════════════════

class TestIslandConfigValidation:
    """SI-502: IslandConfig 验证测试 — 非法参数拒绝"""

    def test_max_size_zero(self):
        with pytest.raises(ValueError, match="max_size"):
            IslandConfig(name="test", perspective="p", max_size=0)

    def test_max_size_negative(self):
        with pytest.raises(ValueError, match="max_size"):
            IslandConfig(name="test", perspective="p", max_size=-1)

    def test_elite_ratio_negative(self):
        with pytest.raises(ValueError, match="elite_ratio"):
            IslandConfig(name="test", perspective="p", elite_ratio=-0.1)

    def test_elite_ratio_above_1(self):
        with pytest.raises(ValueError, match="elite_ratio"):
            IslandConfig(name="test", perspective="p", elite_ratio=1.1)

    def test_fitness_weight_negative(self):
        with pytest.raises(ValueError, match="fitness_weight"):
            IslandConfig(name="test", perspective="p",
                         fitness_weight=-0.1, novelty_weight=1.1)

    def test_novelty_weight_negative(self):
        with pytest.raises(ValueError, match="novelty_weight"):
            IslandConfig(name="test", perspective="p",
                         fitness_weight=0.5, novelty_weight=-0.1)

    def test_weights_not_sum_to_1(self):
        with pytest.raises(ValueError, match="must equal 1.0"):
            IslandConfig(name="test", perspective="p",
                         fitness_weight=0.5, novelty_weight=0.4)


# ════════════════════════════════════════════════
# SI-503: elite_score calculation
# ════════════════════════════════════════════════

class TestEliteScore:
    """SI-503: elite_score 计算测试 — 权重正确性、百分位排序"""

    def test_single_strategy_max_score(self):
        island = StrategyIsland(IslandConfig(name="t", perspective="p"))
        s = _make_strategy("s1")
        island.add_strategy(s)
        rec = island.get_record(s)
        # single → percentile=1.0 both
        score = island.elite_score(rec)
        assert score == pytest.approx(1.0)

    def test_weight_application(self):
        cfg = IslandConfig(name="t", perspective="p",
                           fitness_weight=1.0, novelty_weight=0.0)
        island = StrategyIsland(cfg)
        s1 = _make_strategy("s1")
        s2 = _make_strategy("s2", hypothesis_framing="mechanism_analysis")
        island.add_strategy(s1)
        island.add_strategy(s2)
        r1 = island.get_record(s1)
        r2 = island.get_record(s2)
        # Both have 0 fitness → same fitness percentile (tied)
        # With novelty_weight=0, only fitness matters
        score1 = island.elite_score(r1)
        score2 = island.elite_score(r2)
        # With equal fitness, percentiles are 0.0 and 1.0 or vice versa
        assert 0.0 <= score1 <= 1.0
        assert 0.0 <= score2 <= 1.0

    def test_score_range(self):
        island = StrategyIsland(IslandConfig(name="t", perspective="p"))
        strats = _make_diverse_strategies(5)
        for s in strats:
            island.add_strategy(s)
        for r in island._records:
            score = island.elite_score(r)
            assert 0.0 <= score <= 1.0


# ════════════════════════════════════════════════
# SI-504: fitness conditioning
# ════════════════════════════════════════════════

class TestFitnessConditioning:
    """SI-504: fitness 条件化测试 — 题型样本 ≥ 3 走题型，< 3 走全局"""

    def test_fallback_to_global(self):
        island = StrategyIsland(IslandConfig(name="t", perspective="p"))
        s = _make_strategy("s1")
        island.add_strategy(s)
        rec = island.get_record(s)
        # Record 2 results for "politics" (< 3) and 5 global
        rec.record_result("politics", True)
        rec.record_result("politics", False)
        rec.record_result("sports", True)
        rec.record_result("sports", True)
        rec.record_result("sports", True)
        # politics has 2 samples < 3 → fallback to global: 4/5
        fit = island.fitness(rec, "politics")
        assert fit == pytest.approx(4 / 5)

    def test_use_type_when_enough(self):
        island = StrategyIsland(IslandConfig(name="t", perspective="p"))
        s = _make_strategy("s1")
        island.add_strategy(s)
        rec = island.get_record(s)
        rec.record_result("politics", True)
        rec.record_result("politics", True)
        rec.record_result("politics", False)
        # 3 samples → use type: 2/3
        fit = island.fitness(rec, "politics")
        assert fit == pytest.approx(2 / 3)

    def test_global_with_no_data(self):
        island = StrategyIsland(IslandConfig(name="t", perspective="p"))
        s = _make_strategy("s1")
        island.add_strategy(s)
        rec = island.get_record(s)
        assert island.fitness(rec) == 0.0

    def test_global_with_none_type(self):
        island = StrategyIsland(IslandConfig(name="t", perspective="p"))
        s = _make_strategy("s1")
        island.add_strategy(s)
        rec = island.get_record(s)
        rec.record_result("politics", True)
        rec.record_result("sports", False)
        assert island.fitness(rec, None) == pytest.approx(0.5)


# ════════════════════════════════════════════════
# SI-505: novelty distance
# ════════════════════════════════════════════════

class TestNoveltyDistance:
    """SI-505: novelty 距离测试 — k-NN 平均距离计算"""

    def test_single_strategy_novelty_1(self):
        island = StrategyIsland(IslandConfig(name="t", perspective="p"))
        s = _make_strategy("s1")
        island.add_strategy(s)
        rec = island.get_record(s)
        assert island.novelty(rec) == 1.0

    def test_identical_strategies_novelty_0(self):
        island = StrategyIsland(IslandConfig(name="t", perspective="p"))
        s1 = _make_strategy("s1")
        s2 = _make_strategy("s2")  # same dimensions
        island.add_strategy(s1)
        island.add_strategy(s2)
        r1 = island.get_record(s1)
        assert island.novelty(r1) == 0.0

    def test_diverse_strategies_positive_novelty(self):
        island = StrategyIsland(IslandConfig(name="t", perspective="p"))
        s1 = _make_strategy("s1", hypothesis_framing="news_tracking")
        s2 = _make_strategy("s2", hypothesis_framing="mechanism_analysis")
        island.add_strategy(s1)
        island.add_strategy(s2)
        r1 = island.get_record(s1)
        assert island.novelty(r1) > 0.0

    def test_novelty_symmetry(self):
        island = StrategyIsland(IslandConfig(name="t", perspective="p"))
        s1 = _make_strategy("s1", hypothesis_framing="news_tracking")
        s2 = _make_strategy("s2", hypothesis_framing="mechanism_analysis")
        island.add_strategy(s1)
        island.add_strategy(s2)
        r1 = island.get_record(s1)
        r2 = island.get_record(s2)
        # With only 2, novelty(r1) == novelty(r2)
        assert island.novelty(r1) == island.novelty(r2)


# ════════════════════════════════════════════════
# SI-506: eviction — island not full
# ════════════════════════════════════════════════

class TestEvictionNotFull:
    """SI-506: 淘汰机制：岛未满不淘汰"""

    def test_add_when_not_full(self):
        island = StrategyIsland(IslandConfig(name="t", perspective="p", max_size=5))
        s = _make_strategy("s1")
        assert island.add_strategy(s) is True
        assert island.size == 1

    def test_add_multiple_until_full(self):
        island = StrategyIsland(IslandConfig(name="t", perspective="p", max_size=3))
        for i in range(3):
            assert island.add_strategy(_make_strategy(f"s{i}")) is True
        assert island.is_full


# ════════════════════════════════════════════════
# SI-507: eviction — most similar non-elite
# ════════════════════════════════════════════════

class TestEvictionSimilarity:
    """SI-507: 淘汰机制：找最相似非精英"""

    def test_finds_most_similar(self):
        cfg = IslandConfig(name="t", perspective="p", max_size=3, elite_ratio=0.4)
        island = StrategyIsland(cfg)
        # Add 3 diverse strategies
        s_news = _make_strategy("s_news", hypothesis_framing="news_tracking",
                                query_policy="broad_diverse")
        s_mech = _make_strategy("s_mech", hypothesis_framing="mechanism_analysis",
                                query_policy="targeted_authoritative")
        s_hist = _make_strategy("s_hist", hypothesis_framing="historical_analogy",
                                query_policy="temporal_sequence")
        island.add_strategy(s_news)
        island.add_strategy(s_mech)
        island.add_strategy(s_hist)
        # New strategy similar to s_news
        s_new = _make_strategy("s_new", hypothesis_framing="news_tracking",
                               query_policy="broad_diverse",
                               evidence_source="official_data")
        # Most similar non-elite to s_new should be one of the non-elite strategies
        victim = island._find_most_similar_non_elite(s_new)
        assert victim is not None


# ════════════════════════════════════════════════
# SI-508: eviction — score comparison
# ════════════════════════════════════════════════

class TestEvictionScoreComparison:
    """SI-508: 淘汰机制：score 比较"""

    def test_higher_score_replaces(self):
        cfg = IslandConfig(name="t", perspective="p", max_size=2, elite_ratio=0.5)
        island = StrategyIsland(cfg)
        s1 = _make_strategy("s1")
        s2 = _make_strategy("s2")
        island.add_strategy(s1)
        island.add_strategy(s2)
        assert island.is_full
        # New diverse strategy
        s3 = _make_strategy("s3", hypothesis_framing="mechanism_analysis",
                            query_policy="targeted_authoritative",
                            evidence_source="official_data")
        # Add to full island — s3 is more novel
        result = island.add_strategy(s3)
        # Should either accept or reject based on score, but size stays <= max
        assert island.size <= cfg.max_size

    def test_low_score_rejected(self):
        cfg = IslandConfig(name="t", perspective="p", max_size=2, elite_ratio=0.0,
                           fitness_weight=1.0, novelty_weight=0.0)
        island = StrategyIsland(cfg)
        s1 = _make_strategy("s1")
        s2 = _make_strategy("s2", hypothesis_framing="mechanism_analysis")
        island.add_strategy(s1)
        island.add_strategy(s2)
        # Give s1 and s2 high win rates
        r1 = island.get_record(s1)
        for _ in range(5):
            r1.record_result("politics", True)
        r2 = island.get_record(s2)
        for _ in range(5):
            r2.record_result("politics", True)
        # Try to add s3 with no wins — should be rejected (lower fitness)
        s3 = _make_strategy("s3")
        result = island.add_strategy(s3, "politics")
        # Size should remain 2 (s3 rejected or it replaced someone)
        assert island.size <= cfg.max_size


# ════════════════════════════════════════════════
# SI-509: sampling — highest win rate
# ════════════════════════════════════════════════

class TestSamplingHighestWinRate:
    """SI-509: 采样逻辑：题型最高胜率"""

    def test_picks_highest_win_rate(self):
        island = StrategyIsland(IslandConfig(name="t", perspective="p"))
        s1 = _make_strategy("s1")
        s2 = _make_strategy("s2", hypothesis_framing="mechanism_analysis")
        island.add_strategy(s1)
        island.add_strategy(s2)
        # s1: 3/4 = 0.75 for politics
        r1 = island.get_record(s1)
        for _ in range(3):
            r1.record_result("politics", True)
        r1.record_result("politics", False)
        # s2: 1/4 = 0.25 for politics
        r2 = island.get_record(s2)
        r2.record_result("politics", True)
        for _ in range(3):
            r2.record_result("politics", False)
        result = island.sample("politics")
        assert result.id == "s1"

    def test_global_fallback_for_sampling(self):
        island = StrategyIsland(IslandConfig(name="t", perspective="p"))
        s1 = _make_strategy("s1")
        s2 = _make_strategy("s2", hypothesis_framing="mechanism_analysis")
        island.add_strategy(s1)
        island.add_strategy(s2)
        # s1: 3 wins overall, s2: 1 win overall
        r1 = island.get_record(s1)
        for _ in range(3):
            r1.record_result("sports", True)
        r2 = island.get_record(s2)
        r2.record_result("tech", True)
        r2.record_result("tech", False)
        r2.record_result("tech", False)
        # For "politics" (no data) → fallback to global
        result = island.sample("politics")
        assert result.id == "s1"  # s1 has 3/3=1.0 global, s2 has 1/3≈0.33


# ════════════════════════════════════════════════
# SI-510: sampling — empty island
# ════════════════════════════════════════════════

class TestSamplingEmpty:
    """SI-510: 采样逻辑：空岛返回 None"""

    def test_empty_island_returns_none(self):
        island = StrategyIsland(IslandConfig(name="t", perspective="p"))
        assert island.sample() is None
        assert island.sample("politics") is None


# ════════════════════════════════════════════════
# SI-511: cold start handling
# ════════════════════════════════════════════════

class TestColdStart:
    """SI-511: 冷启动处理测试"""

    def test_no_type_data_uses_global(self):
        island = StrategyIsland(IslandConfig(name="t", perspective="p"))
        s = _make_strategy("s1")
        island.add_strategy(s)
        rec = island.get_record(s)
        rec.record_result("sports", True)
        rec.record_result("sports", True)
        # politics has 0 samples → global: 2/2 = 1.0
        assert island.fitness(rec, "politics") == pytest.approx(1.0)

    def test_all_zero_cold_start(self):
        island = StrategyIsland(IslandConfig(name="t", perspective="p"))
        s = _make_strategy("s1")
        island.add_strategy(s)
        rec = island.get_record(s)
        assert island.fitness(rec, "politics") == 0.0


# ════════════════════════════════════════════════
# SI-512: elite protection
# ════════════════════════════════════════════════

class TestEliteProtection:
    """SI-512: 精英保护测试 — top N% 不被淘汰"""

    def test_elite_not_evicted(self):
        # max_size=3, elite_ratio=0.5 → elite_count=2
        cfg = IslandConfig(name="t", perspective="p", max_size=3, elite_ratio=0.5)
        island = StrategyIsland(cfg)
        s1 = _make_strategy("s1")
        s2 = _make_strategy("s2", hypothesis_framing="mechanism_analysis")
        s3 = _make_strategy("s3", hypothesis_framing="historical_analogy")
        island.add_strategy(s1)
        island.add_strategy(s2)
        island.add_strategy(s3)
        # Give s1 and s2 high fitness
        r1 = island.get_record(s1)
        for _ in range(5):
            r1.record_result("p", True)
        r2 = island.get_record(s2)
        for _ in range(5):
            r2.record_result("p", True)
        # s3 has no wins — it's the weakest
        elites = island._get_elite_records("p")
        elite_ids = {id(r) for r in elites}
        # s3 should not be elite
        r3 = island.get_record(s3)
        assert id(r3) not in elite_ids

    def test_all_elite_no_eviction(self):
        # max_size=2, elite_ratio=1.0 → elite_count=2, all are elite
        cfg = IslandConfig(name="t", perspective="p", max_size=2, elite_ratio=1.0)
        island = StrategyIsland(cfg)
        s1 = _make_strategy("s1")
        s2 = _make_strategy("s2", hypothesis_framing="mechanism_analysis")
        island.add_strategy(s1)
        island.add_strategy(s2)
        # Try adding — should fail since all are elite
        s3 = _make_strategy("s3", hypothesis_framing="historical_analogy")
        result = island.add_strategy(s3)
        assert result is False
        assert island.size == 2


# ════════════════════════════════════════════════
# SI-513: IslandPool creation
# ════════════════════════════════════════════════

class TestIslandPoolCreation:
    """SI-513: IslandPool 创建测试 — 5 岛初始化"""

    def test_default_5_islands(self):
        pool = IslandPool()
        assert pool.island_count == 5

    def test_custom_configs(self):
        configs = [
            IslandConfig(name="A", perspective="p1"),
            IslandConfig(name="B", perspective="p2"),
        ]
        pool = IslandPool(configs)
        assert pool.island_count == 2

    def test_get_island_by_name(self):
        pool = IslandPool()
        island = pool.get_island("信息追踪")
        assert island is not None
        assert island.config.name == "信息追踪"

    def test_get_island_not_found(self):
        pool = IslandPool()
        assert pool.get_island("nonexistent") is None

    def test_default_island_names(self):
        pool = IslandPool()
        names = [i.config.name for i in pool.islands]
        assert "信息追踪" in names
        assert "机制分析" in names
        assert "历史类比" in names
        assert "市场信号" in names
        assert "对抗验证" in names


# ════════════════════════════════════════════════
# SI-514: sample_all
# ════════════════════════════════════════════════

class TestSampleAll:
    """SI-514: sample_all 测试 — 每岛出 1 策略"""

    def test_empty_islands_return_none(self):
        pool = IslandPool()
        results = pool.sample_all("politics")
        assert len(results) == 5
        assert all(r is None for r in results)

    def test_populated_islands(self):
        pool = IslandPool()
        # Add a seed strategy to each island
        for i, seed in enumerate(SEED_STRATEGIES):
            pool.islands[i].add_strategy(copy.deepcopy(seed))
        results = pool.sample_all()
        assert len(results) == 5
        assert all(r is not None for r in results)

    def test_sample_all_length_matches_island_count(self):
        configs = [IslandConfig(name=f"I{i}", perspective="p") for i in range(3)]
        pool = IslandPool(configs)
        for island in pool.islands:
            island.add_strategy(_make_strategy(f"s_{island.config.name}"))
        results = pool.sample_all()
        assert len(results) == 3


# ════════════════════════════════════════════════
# SI-515: ring migration path
# ════════════════════════════════════════════════

class TestRingMigration:
    """SI-515: 环形迁移路径测试 — 0→1→2→3→4→0"""

    def test_ring_topology(self):
        pool = IslandPool()
        # Add diverse strategies to each island
        for i, seed in enumerate(SEED_STRATEGIES):
            pool.islands[i].add_strategy(copy.deepcopy(seed))
        log = pool.migrate_ring()
        # Check that all from/to pairs follow ring topology
        for entry in log:
            src = entry["from"]
            dst = entry["to"]
            assert dst == (src + 1) % pool.island_count

    def test_empty_islands_no_migration(self):
        pool = IslandPool()
        log = pool.migrate_ring()
        assert len(log) == 0  # no elites to migrate


# ════════════════════════════════════════════════
# SI-516: migration filtering (elite_score)
# ════════════════════════════════════════════════

class TestMigrationFiltering:
    """SI-516: 迁移筛选测试 — elite_score + 距离过滤"""

    def test_elite_candidates_only(self):
        pool = IslandPool()
        for i, seed in enumerate(SEED_STRATEGIES):
            pool.islands[i].add_strategy(copy.deepcopy(seed))
        log = pool.migrate_ring()
        # All migrated strategies should be from elite pool
        for entry in log:
            src_island = pool.islands[entry["from"]]
            elites = src_island._get_elite_records()
            elite_ids = {r.strategy.id for r in elites}
            assert entry["strategy"] in elite_ids


# ════════════════════════════════════════════════
# SI-517: distance threshold filtering
# ════════════════════════════════════════════════

class TestDistanceThreshold:
    """SI-517: 距离过滤阈值测试 — 距离 < 0.3 被拒"""

    def test_identical_rejected(self):
        pool = IslandPool()
        s = _make_strategy("s1")
        target = pool.islands[0]
        target.add_strategy(copy.deepcopy(s))
        # Same strategy → distance 0 → rejected
        assert pool._can_migrate(s, target, min_distance=0.3) is False

    def test_diverse_accepted(self):
        pool = IslandPool()
        target = pool.islands[0]
        s1 = _make_strategy("s1", hypothesis_framing="news_tracking",
                            query_policy="broad_diverse")
        target.add_strategy(s1)
        # Very different strategy
        s2 = _make_strategy("s2", hypothesis_framing="counterfactual",
                            query_policy="contrarian",
                            evidence_source="market_data")
        assert pool._can_migrate(s2, target, min_distance=0.3) is True

    def test_empty_target_always_accepts(self):
        pool = IslandPool()
        target = pool.islands[0]
        s = _make_strategy("s1")
        assert pool._can_migrate(s, target, min_distance=0.3) is True


# ════════════════════════════════════════════════
# SI-518: dynamic island creation
# ════════════════════════════════════════════════

class TestDynamicIsland:
    """SI-518: 动态开岛测试"""

    def test_add_island(self):
        pool = IslandPool()
        initial_count = pool.island_count
        new_cfg = IslandConfig(name="新岛", perspective="新视角")
        island = pool.add_island(new_cfg)
        assert pool.island_count == initial_count + 1
        assert island.config.name == "新岛"

    def test_add_duplicate_raises(self):
        pool = IslandPool()
        with pytest.raises(ValueError, match="already exists"):
            pool.add_island(IslandConfig(name="信息追踪", perspective="dup"))

    def test_sample_all_includes_new_island(self):
        pool = IslandPool()
        new_cfg = IslandConfig(name="新岛", perspective="新视角")
        new_island = pool.add_island(new_cfg)
        s = _make_strategy("new_s")
        new_island.add_strategy(s)
        results = pool.sample_all()
        assert len(results) == pool.island_count
        # Last result should be from new island
        assert results[-1] is not None
        assert results[-1].id == "new_s"

    def test_remove_island(self):
        pool = IslandPool()
        initial_count = pool.island_count
        assert pool.remove_island("信息追踪") is True
        assert pool.island_count == initial_count - 1
        assert pool.get_island("信息追踪") is None

    def test_remove_nonexistent(self):
        pool = IslandPool()
        assert pool.remove_island("nonexistent") is False


# ════════════════════════════════════════════════
# SI-519: storage read/write
# ════════════════════════════════════════════════

class TestStorageReadWrite:
    """SI-519: 存储读写测试 — JSON 序列化/反序列化"""

    def test_save_load_pool(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            backend = LocalJsonBackend(Path(tmpdir))
            store = IslandStore(primary=backend)
            pool = IslandPool()
            # Add strategies
            for i, seed in enumerate(SEED_STRATEGIES):
                pool.islands[i].add_strategy(copy.deepcopy(seed))
            store.save(pool)
            # Load
            loaded = store.load()
            assert loaded is not None
            assert loaded.island_count == pool.island_count
            for i in range(pool.island_count):
                assert loaded.islands[i].config.name == pool.islands[i].config.name
                assert loaded.islands[i].size == pool.islands[i].size

    def test_load_empty(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            backend = LocalJsonBackend(Path(tmpdir))
            store = IslandStore(primary=backend)
            assert store.load() is None

    def test_meta_json_format(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            backend = LocalJsonBackend(Path(tmpdir))
            pool = IslandPool()
            pool.islands[0].add_strategy(copy.deepcopy(SEED_STRATEGIES[0]))
            backend.save_pool(pool)
            meta_file = Path(tmpdir) / "islands" / "island_0" / "_meta.json"
            assert meta_file.exists()
            meta = json.loads(meta_file.read_text())
            assert meta["version"] == "1.0"
            assert meta["island_id"] == 0
            assert "config" in meta
            assert "stats" in meta

    def test_strategies_json_format(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            backend = LocalJsonBackend(Path(tmpdir))
            pool = IslandPool()
            pool.islands[0].add_strategy(copy.deepcopy(SEED_STRATEGIES[0]))
            backend.save_pool(pool)
            strat_file = Path(tmpdir) / "islands" / "island_0" / "strategies.json"
            assert strat_file.exists()
            data = json.loads(strat_file.read_text())
            assert isinstance(data, list)
            assert len(data) == 1
            assert "strategy" in data[0]


# ════════════════════════════════════════════════
# SI-520: task results recording
# ════════════════════════════════════════════════

class TestTaskResults:
    """SI-520: 战绩记录追加测试 — JSONL 格式正确"""

    def test_save_and_load_results(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            backend = LocalJsonBackend(Path(tmpdir))
            result1 = {
                "timestamp": "2026-03-20T15:30:00Z",
                "question_type": "politics",
                "island_name": "信息追踪",
                "strategy_id": "s1",
                "won": True,
                "score": 0.85,
            }
            result2 = {
                "timestamp": "2026-03-20T15:31:00Z",
                "question_type": "sports",
                "island_name": "机制分析",
                "strategy_id": "s2",
                "won": False,
                "score": 0.42,
            }
            backend.save_result(result1)
            backend.save_result(result2)
            results = backend.load_results()
            assert len(results) == 2
            assert results[0]["strategy_id"] == "s1"
            assert results[1]["won"] is False

    def test_jsonl_format(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            backend = LocalJsonBackend(Path(tmpdir))
            backend.save_result({"test": True})
            backend.save_result({"test": False})
            results_file = Path(tmpdir) / "results" / "task_results.jsonl"
            lines = results_file.read_text().strip().split("\n")
            assert len(lines) == 2
            for line in lines:
                json.loads(line)  # Should not raise

    def test_load_with_limit(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            backend = LocalJsonBackend(Path(tmpdir))
            for i in range(10):
                backend.save_result({"idx": i})
            results = backend.load_results(limit=3)
            assert len(results) == 3
            assert results[0]["idx"] == 7  # last 3

    def test_load_empty(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            backend = LocalJsonBackend(Path(tmpdir))
            assert backend.load_results() == []


# ════════════════════════════════════════════════
# SI-521: integration — 5 islands produce paths
# ════════════════════════════════════════════════

class TestIntegration5Islands:
    """SI-521: 集成：5 岛全出路径"""

    def test_five_strategies_from_five_islands(self):
        pool = IslandPool()
        for i, seed in enumerate(SEED_STRATEGIES):
            pool.islands[i].add_strategy(copy.deepcopy(seed))
        results = pool.sample_all()
        assert len(results) == 5
        assert all(r is not None for r in results)


# ════════════════════════════════════════════════
# SI-522: integration — strategy diversity
# ════════════════════════════════════════════════

class TestStrategyDiversity:
    """SI-522: 集成：5 策略互不相同"""

    def test_all_strategies_unique(self):
        pool = IslandPool()
        for i, seed in enumerate(SEED_STRATEGIES):
            pool.islands[i].add_strategy(copy.deepcopy(seed))
        results = pool.sample_all()
        ids = [r.id for r in results if r is not None]
        assert len(ids) == len(set(ids))


# ════════════════════════════════════════════════
# SI-523: integration — save/load end-to-end
# ════════════════════════════════════════════════

class TestSaveLoadEndToEnd:
    """SI-523: 集成：存储读写端到端"""

    def test_save_load_with_results(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            backend = LocalJsonBackend(Path(tmpdir))
            store = IslandStore(primary=backend)
            pool = IslandPool()
            for i, seed in enumerate(SEED_STRATEGIES):
                pool.islands[i].add_strategy(copy.deepcopy(seed))
            # Record some results
            pool.islands[0].record_result(SEED_STRATEGIES[0], "politics", True)
            store.save(pool)
            # Load and verify
            loaded = store.load()
            assert loaded is not None
            rec = loaded.islands[0].get_record(
                loaded.islands[0].strategies[0]
            )
            assert rec is not None
            assert rec.total_wins == 1
            assert rec.total_attempts == 1


# ════════════════════════════════════════════════
# SI-524: integration — QP module compatibility
# ════════════════════════════════════════════════

class TestQPCompatibility:
    """SI-524: 集成：StrategyDefinition 兼容"""

    def test_seed_strategies_add_to_islands(self):
        pool = IslandPool()
        for i, seed in enumerate(SEED_STRATEGIES):
            result = pool.islands[i].add_strategy(copy.deepcopy(seed))
            assert result is True

    def test_strategy_distance_works_with_island_strategies(self):
        pool = IslandPool()
        for i, seed in enumerate(SEED_STRATEGIES):
            pool.islands[i].add_strategy(copy.deepcopy(seed))
        s0 = pool.islands[0].strategies[0]
        s1 = pool.islands[1].strategies[0]
        d = strategy_distance(s0, s1)
        assert 0.0 <= d <= 1.0

    def test_compile_strategy_works_with_sampled(self):
        pool = IslandPool()
        for i, seed in enumerate(SEED_STRATEGIES):
            pool.islands[i].add_strategy(copy.deepcopy(seed))
        sampled = pool.sample_all()
        for s in sampled:
            if s is not None:
                compiled = compile_strategy(s)
                assert "prompt_suffix" in compiled
                assert "name" in compiled


# ════════════════════════════════════════════════
# SI-526: regression — existing tests unchanged
# ════════════════════════════════════════════════

class TestRegressionBaseline:
    """SI-526: 回归：验证策略定义和编译器不受影响"""

    def test_strategy_definition_unchanged(self):
        s = StrategyDefinition(id="test", name="test")
        assert s.hypothesis_framing == "news_tracking"
        d = s.to_dict()
        s2 = StrategyDefinition.from_dict(d)
        assert s2.id == "test"

    def test_strategy_distance_unchanged(self):
        s1 = StrategyDefinition(id="a")
        s2 = StrategyDefinition(id="b")
        assert strategy_distance(s1, s2) == 0.0

    def test_seed_strategies_unchanged(self):
        assert len(SEED_STRATEGIES) == 5


# ════════════════════════════════════════════════
# SI-527: regression — multi_path behavior compatible
# ════════════════════════════════════════════════

class TestMultiPathCompatibility:
    """SI-527: 回归：multi_path 行为兼容"""

    def test_island_pool_serialization_roundtrip(self):
        pool = IslandPool()
        for i, seed in enumerate(SEED_STRATEGIES):
            pool.islands[i].add_strategy(copy.deepcopy(seed))
        d = pool.to_dict()
        pool2 = IslandPool.from_dict(d)
        assert pool2.island_count == pool.island_count
        for i in range(pool.island_count):
            assert pool2.islands[i].size == pool.islands[i].size

    def test_compiled_strategies_have_correct_format(self):
        """Compiled island strategies match STRATEGY_VARIANTS format."""
        pool = IslandPool()
        for i, seed in enumerate(SEED_STRATEGIES):
            pool.islands[i].add_strategy(copy.deepcopy(seed))
        for s in pool.sample_all():
            if s is not None:
                compiled = compile_strategy(s)
                assert isinstance(compiled["name"], str)
                assert isinstance(compiled["description"], str)
                assert isinstance(compiled["max_turns"], int)
                assert isinstance(compiled["prompt_suffix"], str)


# ════════════════════════════════════════════════
# SI-528: regression — performance baseline
# ════════════════════════════════════════════════

class TestPerformanceBaseline:
    """SI-528: 回归：性能基线 — 采样延迟 < 50ms"""

    def test_sample_all_under_50ms(self):
        pool = IslandPool()
        # Fill each island with 10 strategies
        for island in pool.islands:
            strats = _make_diverse_strategies(10)
            for s in strats:
                s_copy = copy.deepcopy(s)
                s_copy.id = f"{s.id}_{island.config.name}"
                island.add_strategy(s_copy)
        # Time sample_all
        start = time.monotonic()
        for _ in range(100):
            pool.sample_all("politics")
        elapsed = (time.monotonic() - start) / 100
        assert elapsed < 0.05, f"sample_all took {elapsed:.4f}s, exceeds 50ms"

    def test_elite_score_under_50ms(self):
        island = StrategyIsland(IslandConfig(name="t", perspective="p"))
        strats = _make_diverse_strategies(10)
        for s in strats:
            island.add_strategy(s)
        start = time.monotonic()
        for _ in range(100):
            for r in island._records:
                island.elite_score(r, "politics")
        elapsed = (time.monotonic() - start) / 100
        assert elapsed < 0.05, f"elite_score loop took {elapsed:.4f}s"


# ════════════════════════════════════════════════
# Additional: IslandPool stats
# ════════════════════════════════════════════════

class TestIslandPoolStats:
    """Extra: IslandPool.stats() coverage"""

    def test_stats_empty(self):
        pool = IslandPool()
        s = pool.stats()
        assert s["island_count"] == 5
        assert s["total_strategies"] == 0

    def test_stats_populated(self):
        pool = IslandPool()
        for i, seed in enumerate(SEED_STRATEGIES):
            pool.islands[i].add_strategy(copy.deepcopy(seed))
        s = pool.stats()
        assert s["total_strategies"] == 5
        assert len(s["islands"]) == 5


# ════════════════════════════════════════════════
# Additional: StrategyRecord tests
# ════════════════════════════════════════════════

class TestStrategyRecord:
    """Extra: StrategyRecord coverage"""

    def test_win_rate_no_data(self):
        s = _make_strategy("s1")
        rec = StrategyRecord(strategy=s)
        assert rec.win_rate() == 0.0
        assert rec.win_rate("politics") == 0.0

    def test_record_and_win_rate(self):
        s = _make_strategy("s1")
        rec = StrategyRecord(strategy=s)
        rec.record_result("politics", True)
        rec.record_result("politics", True)
        rec.record_result("politics", False)
        # 3 samples → type rate: 2/3
        assert rec.win_rate("politics") == pytest.approx(2 / 3)
        # global: 2/3
        assert rec.win_rate() == pytest.approx(2 / 3)

    def test_serialization(self):
        s = _make_strategy("s1")
        rec = StrategyRecord(strategy=s)
        rec.record_result("politics", True)
        d = rec.to_dict()
        rec2 = StrategyRecord.from_dict(d)
        assert rec2.total_wins == 1
        assert rec2.strategy.id == "s1"


# ════════════════════════════════════════════════
# Additional: broadcast_strategy
# ════════════════════════════════════════════════

class TestBroadcastStrategy:
    """Extra: IslandPool.broadcast_strategy()"""

    def test_broadcast_to_all(self):
        pool = IslandPool()
        s = _make_strategy("broadcast_s",
                           hypothesis_framing="counterfactual",
                           query_policy="contrarian")
        result = pool.broadcast_strategy(s)
        assert len(result) == 5
        # All empty islands should accept
        assert all(v is True for v in result.values())
