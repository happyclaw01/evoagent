# Copyright 2026 EvoAgent Contributors
# SPDX-License-Identifier: MIT
"""
Evolution Engine — 进化引擎模块 (EE)。

实现 IslandEvolver (EE-503)、DirectionGenerator (EE-502)、
EvolutionConfig、MigrationRecord、SpawnRecord、EvolutionReport，
以及 Refine/Diverge/Spawn prompt 模板。

核心流程：
1. 一轮评测结束后收集 round_stats
2. IslandEvolver.evolve_round() 被触发
3. 对每个岛执行 Refine（微调） + Diverge（变异）
4. 执行环形迁移（Migration）
5. 检查是否需要动态开岛（Spawn）
6. 返回 EvolutionReport
"""

from __future__ import annotations

import copy
import json
import logging
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

from .strategy_definition import (
    STRATEGY_DIMENSIONS,
    StrategyDefinition,
    strategy_distance,
)
from .strategy_island import IslandConfig, IslandPool, StrategyIsland

logger = logging.getLogger(__name__)


# ────────────────────────────────────────────────────────────
# EE-102: REFINE_PROMPT
# ────────────────────────────────────────────────────────────

REFINE_PROMPT = """You are an AI strategy optimizer. Your task is to REFINE an existing problem-solving strategy by making small, targeted improvements.

## Current Best Strategy (7 dimensions)
{strategy_json}

## Performance by Question Type
{type_win_rates}

## Recent Failure Cases
{failure_cases}

## Reflector Experience Insights
{experience_insights}

## Instructions
1. Analyze the failure cases, reflector experience insights, and low-performing question types
2. Identify which 1-{max_dims} dimensions to adjust to address the weaknesses
3. Make MINIMAL changes — only modify what's necessary
4. Keep the strategy's core approach intact
5. Pay special attention to the reflector insights — they capture WHY failures happened (e.g. outdated info, wrong reasoning, insufficient search)

## Output Format
Return ONLY a JSON object with all 7 dimensions:

```json
{{
  "hypothesis_framing": "...",
  "query_policy": "...",
  "evidence_source": "...",
  "retrieval_depth": "...",
  "update_policy": "...",
  "audit_policy": "...",
  "termination_policy": "..."
}}
```

IMPORTANT: Change at most {max_dims} dimensions. The rest MUST remain identical to the original."""

# ────────────────────────────────────────────────────────────
# EE-202: DIVERGE_PROMPT
# ────────────────────────────────────────────────────────────

DIVERGE_PROMPT = """You are an AI strategy designer. Your task is to create a COMPLETELY NEW problem-solving strategy that explores uncharted territory.

## Island Perspective
{perspective}

## Existing Strategies on This Island
{existing_strategies}

## Instructions
1. Design a fundamentally different strategy that fits the island's perspective
2. The new strategy must differ from ALL existing strategies in at least {min_different_dims} dimensions
3. Be creative — explore approaches that existing strategies haven't tried
4. The strategy should still be practical and effective

## Output Format
Return ONLY a JSON object with all 7 dimensions:

```json
{{
  "hypothesis_framing": "...",
  "query_policy": "...",
  "evidence_source": "...",
  "retrieval_depth": "...",
  "update_policy": "...",
  "audit_policy": "...",
  "termination_policy": "..."
}}
```

IMPORTANT: At least {min_different_dims} dimensions must be SUBSTANTIALLY different from every existing strategy."""

# ────────────────────────────────────────────────────────────
# EE-402: SPAWN_PROMPT
# ────────────────────────────────────────────────────────────

SPAWN_PROMPT = """You are an AI research strategist. A question type is consistently failing across ALL existing strategy islands. Your task is to design a completely new island with a fresh perspective to tackle this weakness.

## Failing Question Type
{question_type}

## Current Performance Per Island
{per_island_performance}

## Failure Cases (from this question type)
{failure_cases}

## Existing Island Perspectives (DO NOT duplicate these)
{existing_perspectives}

## Instructions
1. Analyze WHY all existing perspectives fail on this question type
2. Design a NEW perspective that addresses the root cause
3. Create an initial seed strategy aligned with this perspective
4. Explain your rationale

## Output Format
Return ONLY a JSON object:

```json
{{
  "name": "A short name for the new island",
  "perspective": "A concise description of the new island's unique angle/philosophy",
  "initial_strategy": {{
    "hypothesis_framing": "...",
    "query_policy": "...",
    "evidence_source": "...",
    "retrieval_depth": "...",
    "update_policy": "...",
    "audit_policy": "...",
    "termination_policy": "..."
  }},
  "rationale": "Why this perspective and strategy should succeed where others failed"
}}
```

IMPORTANT: The perspective must be DISTINCT from all existing perspectives. Think outside the box."""


# ────────────────────────────────────────────────────────────
# Data classes
# ────────────────────────────────────────────────────────────


@dataclass
class EvolutionConfig:
    """进化引擎配置。"""

    max_refine_dims: int = 2
    min_diverge_dims: int = 3
    migration_distance_threshold: float = 0.3
    migration_elite_score_threshold: float = 0.5
    spawn_win_rate_threshold: float = 0.4
    spawn_min_samples: int = 5
    max_islands: int = 10


@dataclass
class MigrationRecord:
    """记录一次迁移操作 (EE-301)。"""

    source_island_idx: int
    target_island_idx: int
    strategy_id: str
    elite_score: float
    distance_to_nearest: float
    accepted: bool


@dataclass
class SpawnRecord:
    """记录一次开岛操作 (EE-401)。"""

    trigger_question_type: str
    trigger_round: int
    new_island_name: str
    perspective: str
    rationale: str
    seed_strategy_id: str


@dataclass
class EvolutionReport:
    """一轮进化的完整报告 (EE-003)。"""

    round_number: int
    refined_strategies: List[StrategyDefinition] = field(default_factory=list)
    diverged_strategies: List[StrategyDefinition] = field(default_factory=list)
    migrations: List[MigrationRecord] = field(default_factory=list)
    spawned_islands: List[SpawnRecord] = field(default_factory=list)
    total_llm_calls: int = 0

    @property
    def total_new_strategies(self) -> int:
        return len(self.refined_strategies) + len(self.diverged_strategies)


# ────────────────────────────────────────────────────────────
# EE-502: DirectionGenerator
# ────────────────────────────────────────────────────────────


class DirectionGenerator:
    """进化方向生成器。

    封装所有与 LLM 交互的 prompt 构建和输出解析逻辑。
    提供三种生成模式：Refine、Diverge、Spawn。
    """

    def __init__(
        self,
        llm_call: Callable[[str], str],
        max_refine_dims: int = 2,
        min_diverge_dims: int = 3,
    ) -> None:
        """
        Args:
            llm_call: 同步 LLM 调用函数，接受 prompt 字符串，返回响应字符串。
                      设计为可 mock 的依赖。
            max_refine_dims: Refine 允许变化的最大维度数。
            min_diverge_dims: Diverge 要求至少不同的维度数。
        """
        self.llm_call = llm_call
        self.max_refine_dims = max_refine_dims
        self.min_diverge_dims = min_diverge_dims

    # ── EE-101/102/103: Refine ──────────────────

    def build_refine_prompt(
        self,
        best_strategy: StrategyDefinition,
        type_stats: Dict[str, float],
        failures: List[Dict],
        experience_insights: str = "",
    ) -> str:
        """构建 Refine prompt (EE-102)。"""
        return REFINE_PROMPT.format(
            strategy_json=json.dumps(
                best_strategy.get_dimensions(), indent=2, ensure_ascii=False
            ),
            type_win_rates=json.dumps(type_stats, indent=2),
            failure_cases=self._format_failures(failures),
            experience_insights=experience_insights or "(No reflector experiences available)",
            max_dims=self.max_refine_dims,
        )

    def generate_refine(
        self,
        best_strategy: StrategyDefinition,
        type_stats: Dict[str, float],
        failures: List[Dict],
        experience_insights: str = "",
    ) -> StrategyDefinition:
        """生成 Refine 策略 (EE-101)。

        基于最优策略微调 1-2 个维度。
        """
        prompt = self.build_refine_prompt(best_strategy, type_stats, failures, experience_insights)
        response = self.llm_call(prompt)
        new_strategy = self._parse_strategy_response(response, parent=best_strategy)

        # EE-104: 验证变异幅度
        changed_dims = count_changed_dims(best_strategy, new_strategy)
        if changed_dims > self.max_refine_dims:
            new_strategy = truncate_changes(
                best_strategy, new_strategy, self.max_refine_dims
            )

        return new_strategy

    # ── EE-201/202/203: Diverge ─────────────────

    def build_diverge_prompt(
        self,
        island_perspective: str,
        existing_strategies: List[StrategyDefinition],
    ) -> str:
        """构建 Diverge prompt (EE-202)。"""
        return DIVERGE_PROMPT.format(
            perspective=island_perspective,
            existing_strategies=self._summarize_strategies(existing_strategies),
            min_different_dims=self.min_diverge_dims,
        )

    def generate_diverge(
        self,
        island_perspective: str,
        existing_strategies: List[StrategyDefinition],
    ) -> StrategyDefinition:
        """生成 Diverge 策略 (EE-201)。

        在岛视角内生成全新变种，要求 ≥ min_diverge_dims 维不同。
        """
        prompt = self.build_diverge_prompt(island_perspective, existing_strategies)
        response = self.llm_call(prompt)
        new_strategy = self._parse_strategy_response(response)

        # EE-204: 验证多样性，不满足则重试一次
        if not verify_diversity(
            new_strategy, existing_strategies, self.min_diverge_dims
        ):
            retry_prompt = (
                prompt
                + "\n\n⚠️ 上次生成的策略多样性不足，请确保至少"
                + f"{self.min_diverge_dims}个维度与现有策略不同。"
            )
            response = self.llm_call(retry_prompt)
            new_strategy = self._parse_strategy_response(response)

        return new_strategy

    # ── EE-402: Spawn ───────────────────────────

    def build_spawn_prompt(
        self,
        question_type: str,
        per_island_rates: Dict[str, float],
        failures: List[Dict],
        existing_perspectives: List[str],
    ) -> str:
        """构建 Spawn prompt (EE-402)。"""
        return SPAWN_PROMPT.format(
            question_type=question_type,
            per_island_performance=json.dumps(per_island_rates, indent=2),
            failure_cases=self._format_failures(failures),
            existing_perspectives=json.dumps(
                existing_perspectives, indent=2, ensure_ascii=False
            ),
        )

    def generate_spawn(
        self,
        question_type: str,
        per_island_rates: Dict[str, float],
        failures: List[Dict],
        existing_perspectives: List[str],
    ) -> Tuple[IslandConfig, StrategyDefinition, str]:
        """生成新岛配置和种子策略 (EE-402/403)。

        Returns:
            (IslandConfig, StrategyDefinition, rationale) 三元组
        """
        prompt = self.build_spawn_prompt(
            question_type, per_island_rates, failures, existing_perspectives
        )
        response = self.llm_call(prompt)
        parsed = json.loads(self._extract_json(response))

        island_config = IslandConfig(
            name=parsed["name"],
            perspective=parsed["perspective"],
        )
        seed_dict = parsed["initial_strategy"]
        seed_strategy = StrategyDefinition.from_dict(
            {
                "id": f"spawn_{question_type}_{uuid.uuid4().hex[:8]}",
                "name": f"Spawn seed for {question_type}",
                "island_id": parsed["name"],
                **seed_dict,
            }
        )
        rationale = parsed.get("rationale", "")

        return island_config, seed_strategy, rationale

    # ── 内部辅助方法 ────────────────────────────

    def _parse_strategy_response(
        self,
        response: str,
        parent: Optional[StrategyDefinition] = None,
    ) -> StrategyDefinition:
        """从 LLM 响应中提取 JSON 并转为 StrategyDefinition (EE-103/203)。"""
        json_str = self._extract_json(response)
        data = json.loads(json_str)

        # 保留元数据
        strategy_id = f"evolved_{uuid.uuid4().hex[:8]}"
        parent_id = parent.id if parent else None
        return StrategyDefinition.from_dict(
            {
                "id": strategy_id,
                "name": f"Evolved from {parent_id or 'diverge'}",
                "parent_id": parent_id,
                **data,
            }
        )

    @staticmethod
    def _extract_json(text: str) -> str:
        """从可能包含 markdown 代码块的文本中提取 JSON。"""
        if "```json" in text:
            start = text.index("```json") + 7
            end = text.index("```", start)
            return text[start:end].strip()
        elif "```" in text:
            start = text.index("```") + 3
            end = text.index("```", start)
            return text[start:end].strip()
        return text.strip()

    @staticmethod
    def _format_failures(failures: List[Dict]) -> str:
        """格式化失败案例为可读文本。"""
        if not failures:
            return "(无失败案例)"
        lines = []
        for i, f in enumerate(failures, 1):
            lines.append(f"案例{i}: 题目={f.get('question', 'N/A')}")
            lines.append(f"  预期={f.get('expected', 'N/A')}")
            lines.append(f"  实际={f.get('actual', 'N/A')}")
        return "\n".join(lines)

    @staticmethod
    def _summarize_strategies(strategies: List[StrategyDefinition]) -> str:
        """生成现有策略的摘要文本。"""
        if not strategies:
            return "(无现有策略)"
        summaries = []
        for s in strategies:
            summaries.append(
                json.dumps(s.get_dimensions(), indent=2, ensure_ascii=False)
            )
        return "\n---\n".join(summaries)


# ────────────────────────────────────────────────────────────
# EE-503: IslandEvolver
# ────────────────────────────────────────────────────────────


class IslandEvolver:
    """进化引擎核心编排器。

    职责：
    1. 对每个岛执行 Refine（微调）+ Diverge（变异）
    2. 执行环形迁移
    3. 检测并执行动态开岛
    """

    def __init__(
        self,
        direction_generator: DirectionGenerator,
        config: Optional[EvolutionConfig] = None,
    ) -> None:
        self.direction_generator = direction_generator
        self.config = config or EvolutionConfig()
        self.current_round: int = 0

    def evolve_round(
        self,
        island_pool: IslandPool,
        round_stats: Dict[str, Any],
        experience_store: Any = None,
    ) -> EvolutionReport:
        """执行一轮完整进化 (EE-003)。

        Args:
            island_pool: 当前所有岛的池
            round_stats: 本轮评测统计，格式:
                {
                    "round_number": int,
                    "per_island": {
                        island_name: {
                            "best_strategy": StrategyDefinition,
                            "type_win_rates": {"algebra": 0.7, ...},
                            "failures": [{"question": ..., "expected": ..., "actual": ...}, ...]
                        }
                    },
                    "per_question_type": {
                        "algebra": {"best_win_rate": 0.8, "best_island": "信息追踪", "samples": 12},
                        "geometry": {"best_win_rate": 0.35, "best_island": "机制分析", "samples": 8},
                    }
                }

        Returns:
            EvolutionReport
        """
        self.current_round += 1
        report = EvolutionReport(round_number=self.current_round)

        islands = island_pool.islands
        if not islands:
            return report

        # Phase 1: Refine + Diverge for each island
        for island in islands:
            island_stats = round_stats.get("per_island", {}).get(
                island.config.name, {}
            )

            # Refine (EE-101) — feed reflector experiences for richer context
            refined = self._refine_island(island, island_stats, experience_store)
            if refined is not None:
                island.add_strategy(refined)
                report.refined_strategies.append(refined)
                report.total_llm_calls += 1

            # Diverge (EE-201)
            diverged = self._diverge_island(island)
            if diverged is not None:
                island.add_strategy(diverged)
                report.diverged_strategies.append(diverged)
                report.total_llm_calls += 1

        # Phase 2: Migration (EE-301)
        migration_records = self._migrate(island_pool)
        report.migrations = migration_records

        # Phase 3: Check Spawn (EE-401)
        question_type_stats = round_stats.get("per_question_type", {})
        spawn_record = self._check_spawn(island_pool, question_type_stats)
        if spawn_record is not None:
            report.spawned_islands.append(spawn_record)
            report.total_llm_calls += 1

        return report

    def _refine_island(
        self,
        island: StrategyIsland,
        island_stats: Dict[str, Any],
        experience_store: Any = None,
    ) -> Optional[StrategyDefinition]:
        """对单个岛执行 Refine 操作 (EE-101)。

        When experience_store is provided, queries relevant failure experiences
        from the reflector and includes them in the refine prompt for richer context.
        """
        best_strategy = island_stats.get("best_strategy")
        if best_strategy is None:
            return None

        type_win_rates = island_stats.get("type_win_rates", {})
        failures = island_stats.get("failures", [])[:3]

        # Pull reflector experiences for low-performing question types
        experience_insights = ""
        if experience_store is not None:
            try:
                # Find question types with low win rates
                weak_types = [
                    qt for qt, rate in type_win_rates.items()
                    if isinstance(rate, (int, float)) and rate < 0.5
                ]
                relevant_experiences = []
                # Build semantic query describing weak areas
                semantic_q = (
                    f"failures in {', '.join(weak_types)} predictions"
                    if weak_types else None
                )
                for qt in weak_types[:3]:
                    exps = experience_store.query(
                        question_type=qt,
                        was_correct=False,
                        max_count=3,
                        semantic_query=semantic_q,
                    )
                    relevant_experiences.extend(exps)
                # Also get recent failures regardless of type
                if not relevant_experiences:
                    relevant_experiences = experience_store.query(
                        was_correct=False,
                        max_count=5,
                    )
                if relevant_experiences:
                    experience_insights = experience_store.format_for_prompt(
                        relevant_experiences, max_tokens=800
                    )
            except Exception as e:
                logger.warning(f"Failed to query experience store: {e}")

        try:
            refined = self.direction_generator.generate_refine(
                best_strategy=best_strategy,
                type_stats=type_win_rates,
                failures=failures,
                experience_insights=experience_insights,
            )
            refined.island_id = island.config.name
            return refined
        except Exception as e:
            logger.warning(f"Refine failed for island '{island.config.name}': {e}")
            return None

    def _diverge_island(
        self,
        island: StrategyIsland,
    ) -> Optional[StrategyDefinition]:
        """对单个岛执行 Diverge 操作 (EE-201)。"""
        existing_strategies = island.strategies
        if not existing_strategies:
            return None

        try:
            diverged = self.direction_generator.generate_diverge(
                island_perspective=island.config.perspective,
                existing_strategies=existing_strategies,
            )
            diverged.island_id = island.config.name
            return diverged
        except Exception as e:
            logger.warning(f"Diverge failed for island '{island.config.name}': {e}")
            return None

    def _migrate(self, island_pool: IslandPool) -> List[MigrationRecord]:
        """执行环形迁移 0→1→2→...→N-1→0 (EE-301)。"""
        records: List[MigrationRecord] = []
        islands = island_pool.islands
        n = len(islands)

        if n < 2:
            return records

        for i in range(n):
            source = islands[i]
            target = islands[(i + 1) % n]

            # EE-302: 选择 elite_score 最高的策略
            candidate = self._get_top_strategy(source)
            if candidate is None:
                continue

            # EE-303: 计算与目标岛的最小距离
            min_dist = self._min_distance_to_island(candidate, target)
            candidate_score = self._compute_elite_score(source, candidate)

            accepted = (
                candidate_score >= self.config.migration_elite_score_threshold
                and min_dist >= self.config.migration_distance_threshold
            )

            record = MigrationRecord(
                source_island_idx=i,
                target_island_idx=(i + 1) % n,
                strategy_id=candidate.id,
                elite_score=candidate_score,
                distance_to_nearest=min_dist,
                accepted=accepted,
            )
            records.append(record)

            if accepted:
                migrated = copy.deepcopy(candidate)
                migrated.island_id = target.config.name
                target.add_strategy(migrated)

        return records

    def _check_spawn(
        self,
        island_pool: IslandPool,
        question_type_stats: Dict[str, Any],
    ) -> Optional[SpawnRecord]:
        """检查是否需要动态开岛 (EE-401)。"""
        # R-04: 最大岛数限制
        if island_pool.island_count >= self.config.max_islands:
            return None

        for q_type, stats in question_type_stats.items():
            best_win_rate = stats.get("best_win_rate", 1.0)
            samples = stats.get("samples", 0)

            if (
                best_win_rate < self.config.spawn_win_rate_threshold
                and samples >= self.config.spawn_min_samples
            ):
                per_island_rates = {
                    island.config.name: stats.get("best_win_rate", 0.0)
                    for island in island_pool.islands
                }
                existing_perspectives = [
                    island.config.perspective for island in island_pool.islands
                ]
                failures = stats.get("failures", [])[:5]

                try:
                    island_config, seed_strategy, rationale = (
                        self.direction_generator.generate_spawn(
                            question_type=q_type,
                            per_island_rates=per_island_rates,
                            failures=failures,
                            existing_perspectives=existing_perspectives,
                        )
                    )

                    new_island = island_pool.add_island(island_config)
                    new_island.add_strategy(seed_strategy)

                    return SpawnRecord(
                        trigger_question_type=q_type,
                        trigger_round=self.current_round,
                        new_island_name=island_config.name,
                        perspective=island_config.perspective,
                        rationale=rationale,
                        seed_strategy_id=seed_strategy.id,
                    )
                except Exception as e:
                    logger.warning(f"Spawn failed for type '{q_type}': {e}")
                    return None

        return None

    # ── 辅助方法 ─────────────────────────────────

    @staticmethod
    def _get_top_strategy(island: StrategyIsland) -> Optional[StrategyDefinition]:
        """获取岛内 elite_score 最高的策略。"""
        if not island._records:
            return None
        best_rec = max(
            island._records,
            key=lambda r: island.elite_score(r),
        )
        return best_rec.strategy

    @staticmethod
    def _compute_elite_score(
        island: StrategyIsland, strategy: StrategyDefinition
    ) -> float:
        """计算策略在岛内的 elite_score。"""
        rec = island.get_record(strategy)
        if rec is None:
            return 0.0
        return island.elite_score(rec)

    @staticmethod
    def _min_distance_to_island(
        strategy: StrategyDefinition, target: StrategyIsland
    ) -> float:
        """计算策略与目标岛内所有策略的最小距离。"""
        if not target._records:
            return 1.0  # 空岛 — 最大距离
        return min(
            strategy_distance(strategy, r.strategy) for r in target._records
        )


# ────────────────────────────────────────────────────────────
# 公共辅助函数
# ────────────────────────────────────────────────────────────


def count_changed_dims(
    original: StrategyDefinition, modified: StrategyDefinition
) -> int:
    """计算两个策略之间有多少个维度发生了变化 (EE-104)。"""
    count = 0
    for dim in STRATEGY_DIMENSIONS:
        if getattr(original, dim, None) != getattr(modified, dim, None):
            count += 1
    return count


def truncate_changes(
    original: StrategyDefinition,
    modified: StrategyDefinition,
    max_dims: int,
) -> StrategyDefinition:
    """将变化维度截断至 max_dims 个 (EE-104)。

    保留前 max_dims 个变化（按 STRATEGY_DIMENSIONS 顺序），
    其余恢复为原值。
    """
    changes = []
    for dim in STRATEGY_DIMENSIONS:
        orig_val = getattr(original, dim, None)
        mod_val = getattr(modified, dim, None)
        if orig_val != mod_val:
            changes.append((dim, mod_val))

    # 从 modified 的副本开始，恢复超出部分
    result_dict = modified.to_dict()
    # 恢复所有维度到原值
    for dim in STRATEGY_DIMENSIONS:
        result_dict[dim] = getattr(original, dim)
    # 仅应用前 max_dims 个变化
    for dim, val in changes[:max_dims]:
        result_dict[dim] = val

    return StrategyDefinition.from_dict(result_dict)


def verify_diversity(
    new_strategy: StrategyDefinition,
    existing: List[StrategyDefinition],
    min_dims: int,
) -> bool:
    """验证新策略与所有现有策略至少有 min_dims 维不同 (EE-204)。"""
    for existing_s in existing:
        diff_count = count_changed_dims(existing_s, new_strategy)
        if diff_count < min_dims:
            return False
    return True
