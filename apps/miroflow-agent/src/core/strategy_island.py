# Copyright 2026 EvoAgent Contributors
# SPDX-License-Identifier: MIT
"""
Strategy Island — 策略岛模块。

实现 IslandConfig (SI-001~003)、StrategyRecord、StrategyIsland (SI-101~108)、
IslandPool (SI-201~206)、LocalJsonBackend + IslandStore (SI-301~304)。
"""

from __future__ import annotations

import copy
import json
import math
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from .strategy_definition import StrategyDefinition, strategy_distance

logger = logging.getLogger(__name__)

# ────────────────────────────────────────────────────────────
# SI-001: IslandConfig dataclass
# ────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class IslandConfig:
    """单个策略岛的配置（不可变）。

    Attributes:
        name: 岛名称，如 "信息追踪"
        perspective: 岛的分析视角描述
        max_size: 岛内最大策略数量，默认 10
        elite_ratio: 精英比例，top N% 受保护，默认 0.2
        fitness_weight: 适应度权重，默认 0.6
        novelty_weight: 新颖度权重，默认 0.4
    """

    name: str
    perspective: str
    max_size: int = 10
    elite_ratio: float = 0.2
    fitness_weight: float = 0.6
    novelty_weight: float = 0.4

    def __post_init__(self) -> None:
        if self.max_size < 1:
            raise ValueError(f"max_size must be >= 1, got {self.max_size}")
        if not (0.0 <= self.elite_ratio <= 1.0):
            raise ValueError(f"elite_ratio must be in [0, 1], got {self.elite_ratio}")
        if not (0.0 <= self.fitness_weight <= 1.0):
            raise ValueError(f"fitness_weight must be in [0, 1], got {self.fitness_weight}")
        if not (0.0 <= self.novelty_weight <= 1.0):
            raise ValueError(f"novelty_weight must be in [0, 1], got {self.novelty_weight}")
        total = self.fitness_weight + self.novelty_weight
        if abs(total - 1.0) > 1e-6:
            raise ValueError(
                f"fitness_weight + novelty_weight must equal 1.0, got {total}"
            )

    @property
    def elite_count(self) -> int:
        """精英策略数量（向上取整，至少 1）。"""
        return max(1, math.ceil(self.max_size * self.elite_ratio))

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "perspective": self.perspective,
            "max_size": self.max_size,
            "elite_ratio": self.elite_ratio,
            "fitness_weight": self.fitness_weight,
            "novelty_weight": self.novelty_weight,
        }

    @classmethod
    def from_dict(cls, data: dict) -> IslandConfig:
        return cls(
            name=data["name"],
            perspective=data["perspective"],
            max_size=data.get("max_size", 10),
            elite_ratio=data.get("elite_ratio", 0.2),
            fitness_weight=data.get("fitness_weight", 0.6),
            novelty_weight=data.get("novelty_weight", 0.4),
        )


# ────────────────────────────────────────────────────────────
# SI-002: 初始 5 岛定义
# ────────────────────────────────────────────────────────────

DEFAULT_ISLAND_CONFIGS: List[IslandConfig] = [
    IslandConfig(
        name="信息追踪",
        perspective="从信息源头出发，追踪关键数据流向和信号传播路径",
    ),
    IslandConfig(
        name="机制分析",
        perspective="拆解底层运作机制，理解因果链条和反馈环路",
    ),
    IslandConfig(
        name="历史类比",
        perspective="寻找历史相似情境，借鉴已知模式预测可能走向",
    ),
    IslandConfig(
        name="市场信号",
        perspective="聚焦市场行为和价格信号，捕捉供需变化和情绪转折",
    ),
    IslandConfig(
        name="对抗验证",
        perspective="主动寻找反面证据和替代解释，压力测试当前假设",
    ),
]


# ────────────────────────────────────────────────────────────
# StrategyRecord — 岛内策略运行时记录
# ────────────────────────────────────────────────────────────


@dataclass
class StrategyRecord:
    """岛内策略的运行时记录。"""

    strategy: StrategyDefinition
    wins: Dict[str, int] = field(default_factory=dict)
    attempts: Dict[str, int] = field(default_factory=dict)
    total_wins: int = 0
    total_attempts: int = 0

    def win_rate(self, question_type: Optional[str] = None) -> float:
        """计算胜率。None → 全局胜率。"""
        if question_type is not None:
            attempts = self.attempts.get(question_type, 0)
            if attempts >= 3:
                return self.wins.get(question_type, 0) / attempts
        # 退回全局
        if self.total_attempts == 0:
            return 0.0
        return self.total_wins / self.total_attempts

    def record_result(self, question_type: str, won: bool) -> None:
        self.total_attempts += 1
        if won:
            self.total_wins += 1
        self.attempts[question_type] = self.attempts.get(question_type, 0) + 1
        if won:
            self.wins[question_type] = self.wins.get(question_type, 0) + 1

    def to_dict(self) -> dict:
        return {
            "strategy": self.strategy.to_dict(),
            "wins": dict(self.wins),
            "attempts": dict(self.attempts),
            "total_wins": self.total_wins,
            "total_attempts": self.total_attempts,
        }

    @classmethod
    def from_dict(cls, data: dict) -> StrategyRecord:
        return cls(
            strategy=StrategyDefinition.from_dict(data["strategy"]),
            wins=data.get("wins", {}),
            attempts=data.get("attempts", {}),
            total_wins=data.get("total_wins", 0),
            total_attempts=data.get("total_attempts", 0),
        )


# ────────────────────────────────────────────────────────────
# SI-101~108: StrategyIsland
# ────────────────────────────────────────────────────────────


class StrategyIsland:
    """单个策略岛，管理一组同视角策略的生命周期。"""

    def __init__(self, config: IslandConfig) -> None:
        self.config: IslandConfig = config
        self._records: List[StrategyRecord] = []

    # ── 核心属性 ─────────────────────────────────

    @property
    def size(self) -> int:
        return len(self._records)

    @property
    def is_full(self) -> bool:
        return self.size >= self.config.max_size

    @property
    def strategies(self) -> List[StrategyDefinition]:
        return [r.strategy for r in self._records]

    # ── SI-103: fitness ──────────────────────────

    def fitness(self, record: StrategyRecord,
                question_type: Optional[str] = None) -> float:
        """题型条件化胜率。样本 >= 3 用题型，否则全局。"""
        if question_type is not None:
            attempts = record.attempts.get(question_type, 0)
            if attempts >= 3:
                return record.wins.get(question_type, 0) / attempts
        if record.total_attempts == 0:
            return 0.0
        return record.total_wins / record.total_attempts

    def _fitness_percentile(self, record: StrategyRecord,
                            question_type: Optional[str] = None) -> float:
        """百分位排名 [0.0, 1.0]。"""
        if len(self._records) <= 1:
            return 1.0
        target_fit = self.fitness(record, question_type)
        lower = sum(
            1 for r in self._records
            if self.fitness(r, question_type) < target_fit
        )
        return lower / (len(self._records) - 1)

    # ── SI-104: novelty ──────────────────────────

    def novelty(self, record: StrategyRecord) -> float:
        """与岛内其他策略的平均 strategy_distance。仅 1 策略返回 1.0。"""
        others = [r for r in self._records if r is not record]
        if not others:
            return 1.0
        total = sum(
            strategy_distance(record.strategy, o.strategy) for o in others
        )
        return total / len(others)

    def _novelty_percentile(self, record: StrategyRecord) -> float:
        if len(self._records) <= 1:
            return 1.0
        target_nov = self.novelty(record)
        lower = sum(
            1 for r in self._records
            if self.novelty(r) < target_nov
        )
        return lower / (len(self._records) - 1)

    # ── SI-102: elite_score ──────────────────────

    def elite_score(self, record: StrategyRecord,
                    question_type: Optional[str] = None) -> float:
        """fitness_weight × fitness_percentile + novelty_weight × novelty_percentile"""
        fp = self._fitness_percentile(record, question_type)
        np_ = self._novelty_percentile(record)
        return (self.config.fitness_weight * fp +
                self.config.novelty_weight * np_)

    # ── SI-108: 精英列表 ─────────────────────────

    def _get_elite_records(self,
                           question_type: Optional[str] = None) -> List[StrategyRecord]:
        """按 elite_score 降序取 top elite_count。"""
        if not self._records:
            return []
        scored = sorted(
            self._records,
            key=lambda r: self.elite_score(r, question_type),
            reverse=True,
        )
        return scored[: self.config.elite_count]

    # ── SI-105: 淘汰机制 ─────────────────────────

    def _find_most_similar_non_elite(
        self, strategy: StrategyDefinition,
        question_type: Optional[str] = None,
    ) -> Optional[StrategyRecord]:
        elites = set(id(r) for r in self._get_elite_records(question_type))
        non_elites = [r for r in self._records if id(r) not in elites]
        if not non_elites:
            return None
        return min(
            non_elites,
            key=lambda r: strategy_distance(strategy, r.strategy),
        )

    def add_strategy(self, strategy: StrategyDefinition,
                     question_type: Optional[str] = None) -> bool:
        """向岛中添加策略，必要时触发淘汰。"""
        if not self.is_full:
            self._records.append(StrategyRecord(strategy=strategy))
            return True
        # 岛已满 — 确定性拥挤淘汰
        new_record = StrategyRecord(strategy=strategy)
        self._records.append(new_record)  # 临时加入以计算 score
        new_score = self.elite_score(new_record, question_type)
        victim = self._find_most_similar_non_elite(strategy, question_type)
        if victim is None:
            # 全是精英，拒绝
            self._records.remove(new_record)
            return False
        victim_score = self.elite_score(victim, question_type)
        if new_score > victim_score:
            self._records.remove(victim)
            return True
        else:
            self._records.remove(new_record)
            return False

    # ── SI-106: 采样 ─────────────────────────────

    def sample(self, question_type: Optional[str] = None) -> Optional[StrategyDefinition]:
        """题型最高胜率策略。空岛返回 None。"""
        if not self._records:
            return None
        best = max(
            self._records,
            key=lambda r: r.win_rate(question_type),
        )
        return best.strategy

    # ── 记录管理 ──────────────────────────────────

    def record_result(self, strategy: StrategyDefinition,
                      question_type: str, won: bool) -> None:
        rec = self.get_record(strategy)
        if rec is not None:
            rec.record_result(question_type, won)

    def get_record(self, strategy: StrategyDefinition) -> Optional[StrategyRecord]:
        for r in self._records:
            if r.strategy.id == strategy.id:
                return r
        return None

    # ── 序列化 ────────────────────────────────────

    def to_dict(self) -> dict:
        return {
            "config": self.config.to_dict(),
            "records": [r.to_dict() for r in self._records],
        }

    @classmethod
    def from_dict(cls, data: dict) -> StrategyIsland:
        config = IslandConfig.from_dict(data["config"])
        island = cls(config)
        island._records = [
            StrategyRecord.from_dict(r) for r in data.get("records", [])
        ]
        return island


# ────────────────────────────────────────────────────────────
# SI-201~206: IslandPool
# ────────────────────────────────────────────────────────────


class IslandPool:
    """多岛管理器，统一调度所有策略岛。"""

    def __init__(self, configs: Optional[List[IslandConfig]] = None) -> None:
        self._islands: List[StrategyIsland] = [
            StrategyIsland(cfg) for cfg in (configs or DEFAULT_ISLAND_CONFIGS)
        ]

    @property
    def island_count(self) -> int:
        return len(self._islands)

    @property
    def islands(self) -> List[StrategyIsland]:
        return list(self._islands)

    def get_island(self, name: str) -> Optional[StrategyIsland]:
        for island in self._islands:
            if island.config.name == name:
                return island
        return None

    # ── SI-202: sample_all ───────────────────────

    def sample_all(self, question_type: Optional[str] = None) -> List[Optional[StrategyDefinition]]:
        return [island.sample(question_type) for island in self._islands]

    # ── SI-203/204: 环形迁移 ─────────────────────

    def migrate_ring(self, question_type: Optional[str] = None) -> List[dict]:
        """0→1→2→…→N-1→0 环形迁移。"""
        log: List[dict] = []
        n = len(self._islands)
        if n < 2:
            return log

        # 收集每个源岛的精英策略（迁移候选）
        candidates: List[List[StrategyRecord]] = []
        for island in self._islands:
            candidates.append(island._get_elite_records(question_type))

        for src_idx in range(n):
            dst_idx = (src_idx + 1) % n
            target = self._islands[dst_idx]
            for rec in candidates[src_idx]:
                can = self._can_migrate(rec.strategy, target, min_distance=0.3)
                entry = {
                    "from": src_idx,
                    "to": dst_idx,
                    "strategy": rec.strategy.id,
                    "accepted": False,
                }
                if can:
                    accepted = target.add_strategy(
                        copy.deepcopy(rec.strategy), question_type
                    )
                    entry["accepted"] = accepted
                log.append(entry)
        return log

    def _can_migrate(self, strategy: StrategyDefinition,
                     target_island: StrategyIsland,
                     min_distance: float = 0.3) -> bool:
        if not target_island._records:
            return True
        for r in target_island._records:
            if strategy_distance(strategy, r.strategy) < min_distance:
                return False
        return True

    # ── SI-205: 动态开岛 ─────────────────────────

    def add_island(self, config: IslandConfig) -> StrategyIsland:
        for island in self._islands:
            if island.config.name == config.name:
                raise ValueError(f"Island '{config.name}' already exists")
        island = StrategyIsland(config)
        self._islands.append(island)
        return island

    def remove_island(self, name: str) -> bool:
        for i, island in enumerate(self._islands):
            if island.config.name == name:
                self._islands.pop(i)
                return True
        return False

    # ── 批量操作 ──────────────────────────────────

    def add_strategy(self, island_name: str,
                     strategy: StrategyDefinition,
                     question_type: Optional[str] = None) -> bool:
        island = self.get_island(island_name)
        if island is None:
            return False
        return island.add_strategy(strategy, question_type)

    def record_result(self, island_name: str,
                      strategy: StrategyDefinition,
                      question_type: str, won: bool) -> None:
        island = self.get_island(island_name)
        if island is not None:
            island.record_result(strategy, question_type, won)

    def broadcast_strategy(self, strategy: StrategyDefinition,
                           question_type: Optional[str] = None) -> Dict[str, bool]:
        result: Dict[str, bool] = {}
        for island in self._islands:
            result[island.config.name] = island.add_strategy(
                copy.deepcopy(strategy), question_type
            )
        return result

    # ── 统计 ──────────────────────────────────────

    def stats(self) -> dict:
        islands_info = []
        total_strategies = 0
        for island in self._islands:
            size = island.size
            total_strategies += size
            avg_fit = 0.0
            if size > 0:
                avg_fit = sum(
                    island.fitness(r) for r in island._records
                ) / size
            islands_info.append({
                "name": island.config.name,
                "size": size,
                "avg_fitness": round(avg_fit, 4),
            })
        return {
            "island_count": len(self._islands),
            "total_strategies": total_strategies,
            "islands": islands_info,
        }

    # ── 序列化 ────────────────────────────────────

    def to_dict(self) -> dict:
        return {
            "islands": [island.to_dict() for island in self._islands],
        }

    @classmethod
    def from_dict(cls, data: dict) -> IslandPool:
        pool = cls.__new__(cls)
        pool._islands = [
            StrategyIsland.from_dict(d) for d in data.get("islands", [])
        ]
        return pool


# ────────────────────────────────────────────────────────────
# SI-301~304: Storage (LocalJsonBackend + IslandStore)
# ────────────────────────────────────────────────────────────


class LocalJsonBackend:
    """本地 JSON 存储后端 (SI-301)。"""

    def __init__(self, base_dir: Path) -> None:
        self.base_dir = Path(base_dir)
        self.islands_dir = self.base_dir / "islands"
        self.results_dir = self.base_dir / "results"

    def save_island(self, island_id: int, island: StrategyIsland) -> None:
        island_dir = self.islands_dir / f"island_{island_id}"
        island_dir.mkdir(parents=True, exist_ok=True)
        meta = {
            "version": "1.0",
            "island_id": island_id,
            "config": island.config.to_dict(),
            "stats": {
                "current_size": island.size,
                "total_evaluations": sum(
                    r.total_attempts for r in island._records
                ),
                "avg_fitness": round(
                    sum(island.fitness(r) for r in island._records) / island.size
                    if island.size > 0
                    else 0.0,
                    4,
                ),
                "last_updated": datetime.now(timezone.utc).isoformat(),
            },
        }
        (island_dir / "_meta.json").write_text(
            json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        strategies_data = [r.to_dict() for r in island._records]
        (island_dir / "strategies.json").write_text(
            json.dumps(strategies_data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def load_island(self, island_id: int) -> Optional[dict]:
        island_dir = self.islands_dir / f"island_{island_id}"
        meta_file = island_dir / "_meta.json"
        strat_file = island_dir / "strategies.json"
        if not meta_file.exists():
            return None
        meta = json.loads(meta_file.read_text(encoding="utf-8"))
        records = []
        if strat_file.exists():
            records = json.loads(strat_file.read_text(encoding="utf-8"))
        return {
            "config": meta["config"],
            "records": records,
        }

    def save_pool(self, pool: IslandPool) -> None:
        for i, island in enumerate(pool.islands):
            self.save_island(i, island)

    def load_pool(self) -> Optional[dict]:
        if not self.islands_dir.exists():
            return None
        island_dirs = sorted(self.islands_dir.iterdir())
        if not island_dirs:
            return None
        islands = []
        for i, d in enumerate(island_dirs):
            if d.is_dir() and d.name.startswith("island_"):
                idx = int(d.name.split("_")[1])
                data = self.load_island(idx)
                if data is not None:
                    islands.append(data)
        if not islands:
            return None
        return {"islands": islands}

    def save_result(self, result: dict) -> None:
        self.results_dir.mkdir(parents=True, exist_ok=True)
        results_file = self.results_dir / "task_results.jsonl"
        with open(results_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(result, ensure_ascii=False) + "\n")

    def load_results(self, limit: Optional[int] = None) -> List[dict]:
        results_file = self.results_dir / "task_results.jsonl"
        if not results_file.exists():
            return []
        lines = results_file.read_text(encoding="utf-8").strip().split("\n")
        lines = [l for l in lines if l.strip()]
        if limit is not None:
            lines = lines[-limit:]
        return [json.loads(line) for line in lines]


class IslandStore:
    """岛存储管理器 (SI-301~304)。"""

    def __init__(self, primary: LocalJsonBackend,
                 fallback: Optional[Any] = None,
                 viking_storage=None,
                 viking_context=None) -> None:
        self.primary = primary
        self.fallback = fallback
        self._viking = viking_storage
        self._viking_context = viking_context

    def save(self, pool: IslandPool) -> None:
        self.primary.save_pool(pool)
        # Viking write-through: PUT each island
        if self._viking is not None:
            for island in pool.islands:
                island_name = island.config.name
                self._viking.put(
                    f"viking://agent/skills/islands/{island_name}",
                    island.to_dict(),
                )

    def load(self, level: int = 2) -> Optional[IslandPool]:
        data = self.primary.load_pool()
        if data is None and self.fallback is not None:
            try:
                data = self.fallback.load_pool()
            except Exception:
                pass
        # Viking fallback: try loading from OpenViking if local/fallback empty
        if data is None and self._viking_context is not None and self._viking is not None:
            try:
                import asyncio
                remote_islands = self._viking.query_sync(
                    self._viking_context.list_by_prefix("viking://agent/skills/islands/")
                )
                if remote_islands:
                    islands_data = [hit["data"] for hit in remote_islands if "data" in hit]
                    if islands_data:
                        data = {"islands": islands_data}
            except Exception as e:
                logger.warning(f"Viking island load failed: {e}")
        if data is None:
            return None
        return IslandPool.from_dict(data)

    def save_result(self, result: dict) -> None:
        self.primary.save_result(result)
        # Viking write-through
        if self._viking is not None:
            task_id = result.get("task_id", "unknown")
            self._viking.put(
                f"viking://agent/memory/results/{task_id}",
                result,
            )

    def load_results(self, limit: Optional[int] = None) -> List[dict]:
        return self.primary.load_results(limit)
