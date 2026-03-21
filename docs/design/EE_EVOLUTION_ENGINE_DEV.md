# EE — Evolution Engine 开发文档

| 字段 | 值 |
|------|------|
| **模块代号** | EE (Evolution Engine) |
| **基线项目** | EvoAgent |
| **创建日期** | 2026-03-20 |
| **依赖模块** | QP → `StrategyDefinition`；SI → `StrategyIsland` / `IslandPool` |
| **预计工期** | 3 天 |
| **作者** | happyclaw01 |

---

## 1. 架构总览

```
                         ┌─────────────────────────────────────────────────┐
                         │              一轮评测结束                         │
                         │         (batch of N questions)                   │
                         └────────────────────┬────────────────────────────┘
                                              │
                                              ▼
                                   ┌─────────────────────┐
                                   │   IslandEvolver      │
                                   │   .evolve_round()    │
                                   └─────────┬───────────┘
                                             │
                          ┌──────────────────┼──────────────────┐
                          ▼                  ▼                  ▼
                    ┌──────────┐      ┌──────────┐       ┌──────────┐
                    │ Island 0 │      │ Island 1 │  ...  │ Island N │
                    └────┬─────┘      └────┬─────┘       └────┬─────┘
                         │                 │                   │
                    ┌────┴────┐       ┌────┴────┐        ┌────┴────┐
                    │ Refine  │       │ Refine  │        │ Refine  │
                    │ Diverge │       │ Diverge │        │ Diverge │
                    └────┬────┘       └────┬────┘        └────┬────┘
                         │                 │                   │
                         └────────┬────────┘                   │
                                  ▼                            │
                         ┌────────────────┐                    │
                         │   Migration    │◄───────────────────┘
                         │ (Ring Topology)│
                         │ 0→1→2→3→4→0   │
                         └───────┬────────┘
                                 │
                                 ▼
                      ┌─────────────────────┐
                      │  Check Spawn New    │
                      │  Island?            │
                      │  (win_rate < 0.4    │
                      │   && samples ≥ 5)   │
                      └─────────┬───────────┘
                                │
                       ┌────────┴────────┐
                       │ Yes             │ No
                       ▼                 ▼
                ┌─────────────┐   ┌───────────┐
                │ Spawn New   │   │   Done    │
                │ Island      │   │           │
                └─────────────┘   └───────────┘
```

**核心流程：**
1. 一轮评测（batch of N questions）结束后，收集 `round_stats`
2. `IslandEvolver.evolve_round()` 被触发
3. 对每个岛并行执行 **Refine**（微调最优策略）+ **Diverge**（生成全新变种）
4. 执行环形 **迁移**（Migration），岛间交换精英策略
5. 检查是否需要 **动态开岛**（Spawn），为薄弱题型创建专门岛
6. 返回 `EvolutionReport`

---

## 2. 功能清单与编号

### 2.1 进化触发层

| 编号 | 功能 | 描述 | 优先级 | 状态 |
|------|------|------|--------|------|
| **EE-001** | 轮次管理器 (RoundManager) | 跟踪当前轮次编号，每轮结束时触发进化流程。维护 `current_round: int`，提供 `advance_round()` 方法 | **P0** | ✅ |
| **EE-002** | 轮次定义 | 一轮 = 一批评测题（默认 batch_size=10）。轮次边界由 `main_multipath.py` 在处理完一批题后确定 | **P0** | ✅ |
| **EE-003** | 进化调度器 (EvolutionScheduler) | 协调所有岛的进化操作：遍历 `island_pool.islands`，依次调用 refine → diverge → migrate → check_spawn | **P0** | ✅ |

### 2.2 Refine 层

| 编号 | 功能 | 描述 | 优先级 | 状态 |
|------|------|------|--------|------|
| **EE-101** | RefineGenerator | 取岛内 `elite_score` 最高的策略，通过 LLM 微调其中 1-2 个维度，生成改良版策略 | **P0** | ✅ |
| **EE-102** | Refine Prompt 模板 | **输入：** best策略的8维参数 + 该岛在各题型上的胜率 + 最近失败案例（≤3条）<br>**输出：** 修改后的完整8维参数（JSON格式） | **P0** | ✅ |
| **EE-103** | Refine 输出解析 | 解析 LLM 返回的 JSON，校验字段完整性，转换为 `StrategyDefinition` 对象 | **P0** | ✅ |
| **EE-104** | Refine 变异幅度控制 | 对比原策略与新策略的8维，确保最多只有2个维度发生变化。超出则截断至变化最大的2维 | **P1** | ✅ |

### 2.3 Diverge 层

| 编号 | 功能 | 描述 | 优先级 | 状态 |
|------|------|------|--------|------|
| **EE-201** | DivergeGenerator | 在岛的 `perspective` 视角约束下，生成与现有策略截然不同的全新变种 | **P0** | ✅ |
| **EE-202** | Diverge Prompt 模板 | **输入：** `island.perspective` + 岛内所有现有策略摘要<br>**输出：** 全新8维策略，要求至少3个维度与岛内任意现有策略不同 | **P0** | ✅ |
| **EE-203** | Diverge 输出解析 | 解析 LLM 返回的 JSON，校验字段完整性，转换为 `StrategyDefinition` 对象 | **P0** | ✅ |
| **EE-204** | Diverge 多样性验证 | 对比新策略与岛内所有现有策略，确认至少有 ≥3 个维度不同。不满足则拒绝并重试（最多2次） | **P1** | ✅ |

### 2.4 迁移层

| 编号 | 功能 | 描述 | 优先级 | 状态 |
|------|------|------|--------|------|
| **EE-301** | 环形迁移执行器 | 按固定拓扑 `0→1→2→3→4→0` 执行策略迁移。岛 i 的 top1 策略复制到岛 `(i+1) % N` | **P1** | ✅ |
| **EE-302** | 迁移候选选择 | 每个岛选择 `elite_score` 最高的1个策略作为迁移候选 | **P1** | ✅ |
| **EE-303** | 迁移筛选 | 候选策略需同时满足：(1) `elite_score ≥ 阈值`（默认0.5）；(2) 与目标岛所有策略的最小距离 ≥ 0.3。不满足则跳过该迁移 | **P1** | ✅ |

### 2.5 动态开岛层

| 编号 | 功能 | 描述 | 优先级 | 状态 |
|------|------|------|--------|------|
| **EE-401** | 开岛触发检测 | 遍历所有题型，若某题型满足：所有岛的最佳胜率 < 0.4 **且** 该题型样本数 ≥ 5，则触发开岛 | **P1** | ✅ |
| **EE-402** | SpawnPrompt | **输入：** 失败题型名 + 各岛在该题型的胜率 + 失败案例（≤5条）+ 现有所有岛的 perspective 列表<br>**输出：** `{ perspective, initial_strategy(8维), rationale }` | **P1** | ✅ |
| **EE-403** | 新岛注册 | 根据 SpawnPrompt 输出创建 `IslandConfig`（含 perspective）和种子 `StrategyDefinition`，调用 `IslandPool.add_island()` 注册 | **P1** | ✅ |
| **EE-404** | 开岛日志记录 | 记录开岛事件：触发题型、触发轮次、新岛 perspective、rationale、种子策略。写入 `evolution_log.jsonl` | **P2** | ✅ |

### 2.6 集成层

| 编号 | 功能 | 描述 | 优先级 | 状态 |
|------|------|------|--------|------|
| **EE-501** | main_multipath.py 集成 | 在主循环中，每处理完一批题后调用 `island_evolver.evolve_round()`，将 `EvolutionReport` 写入日志 | **P0** | ❌ (deferred — requires runtime pipeline changes) |
| **EE-502** | 新建 direction_generator.py | 包含 `DirectionGenerator` 类，封装所有 LLM prompt 构建与调用逻辑 | **P0** | ✅ (in evolution_engine.py) |
| **EE-503** | 新建 island_evolver.py | 包含 `IslandEvolver` 类，封装进化流程编排逻辑 | **P0** | ✅ (in evolution_engine.py) |

### 2.7 测试

| 编号 | 功能 | 描述 | 优先级 | 状态 |
|------|------|------|--------|------|
| **EE-601** | test_refine_prompt_generation | 验证 Refine prompt 正确拼装8维+胜率+失败案例 | **P0** | ✅ |
| **EE-602** | test_refine_output_parsing | 验证合法 JSON → StrategyDefinition 转换 | **P0** | ✅ |
| **EE-603** | test_refine_output_parsing_malformed | 验证畸形 JSON 的错误处理 | **P0** | ✅ |
| **EE-604** | test_refine_mutation_amplitude | 验证变异幅度 ≤ 2 维的约束 | **P1** | ✅ |
| **EE-605** | test_diverge_prompt_generation | 验证 Diverge prompt 正确拼装 perspective+现有策略 | **P0** | ✅ |
| **EE-606** | test_diverge_output_parsing | 验证合法 JSON → StrategyDefinition 转换 | **P0** | ✅ |
| **EE-607** | test_diverge_output_parsing_malformed | 验证畸形 JSON 的错误处理 | **P0** | ✅ |
| **EE-608** | test_diverge_diversity_check_pass | 验证 ≥3 维不同时通过 | **P1** | ✅ |
| **EE-609** | test_diverge_diversity_check_fail | 验证 <3 维不同时拒绝 | **P1** | ✅ |
| **EE-610** | test_spawn_prompt_generation | 验证 Spawn prompt 正确拼装失败题型+各岛表现 | **P1** | ✅ |
| **EE-611** | test_spawn_output_parsing | 验证 perspective+strategy+rationale 解析 | **P1** | ✅ |
| **EE-612** | test_spawn_trigger_condition_met | 验证 win_rate<0.4 且 samples≥5 时触发 | **P1** | ✅ |
| **EE-613** | test_spawn_trigger_condition_not_met | 验证不满足条件时不触发 | **P1** | ✅ |
| **EE-614** | test_migration_distance_filter | 验证距离 ≥0.3 通过，<0.3 拒绝 | **P1** | ✅ |
| **EE-615** | test_migration_ring_topology | 验证环形拓扑 0→1→2→3→4→0 | **P1** | ✅ |
| **EE-616** | test_integration_full_round_evolution | 集成测试：5岛×(1 refine+1 diverge)=10个新策略 | **P1** | ✅ |
| **EE-617** | test_integration_evolution_with_migration | 集成测试：进化+迁移完整流程 | **P1** | ✅ |
| **EE-618** | test_integration_spawn_end_to_end | 端到端：触发检测→spawn prompt→新岛注册 | **P1** | ✅ |
| **EE-619** | test_integration_multi_round | 多轮进化稳定性（3轮连续进化） | **P1** | ✅ |
| **EE-620** | test_integration_empty_island_pool | 边界：空岛池不崩溃 | **P1** | ✅ |
| **EE-621** | test_regression_strategy_count_growth | 回归：每轮策略数量正确增长 | **P0** | ✅ |
| **EE-622** | test_regression_no_duplicate_strategies | 回归：不产生完全重复的策略 | **P1** | ✅ |
| **EE-623** | test_performance_llm_call_count | 性能：验证每轮 LLM 调用次数 = 2×岛数 + spawns | **P1** | ✅ |

---

## 3. 核心接口详细设计

### 3.1 IslandEvolver 类

**文件：** `src/evoagent/island_evolver.py`

```python
from dataclasses import dataclass, field
from typing import List, Optional, Dict
from evoagent.strategy import StrategyDefinition
from evoagent.island import StrategyIsland, IslandPool, IslandConfig


@dataclass
class MigrationRecord:
    """记录一次迁移操作"""
    source_island_id: int
    target_island_id: int
    strategy_id: str
    elite_score: float
    distance_to_nearest: float
    accepted: bool


@dataclass
class SpawnRecord:
    """记录一次开岛操作"""
    trigger_question_type: str
    trigger_round: int
    new_island_id: int
    perspective: str
    rationale: str
    seed_strategy_id: str


@dataclass
class EvolutionReport:
    """一轮进化的完整报告"""
    round_number: int
    refined_strategies: List[StrategyDefinition] = field(default_factory=list)
    diverged_strategies: List[StrategyDefinition] = field(default_factory=list)
    migrations: List[MigrationRecord] = field(default_factory=list)
    spawned_islands: List[SpawnRecord] = field(default_factory=list)
    total_llm_calls: int = 0

    @property
    def total_new_strategies(self) -> int:
        return len(self.refined_strategies) + len(self.diverged_strategies)


class IslandEvolver:
    """
    进化引擎核心编排器。
    
    职责：
    1. 对每个岛执行 Refine（微调） + Diverge（变异）
    2. 执行环形迁移
    3. 检测并执行动态开岛
    """

    def __init__(
        self,
        direction_generator: "DirectionGenerator",
        migration_distance_threshold: float = 0.3,
        spawn_win_rate_threshold: float = 0.4,
        spawn_min_samples: int = 5,
    ):
        self.direction_generator = direction_generator
        self.migration_distance_threshold = migration_distance_threshold
        self.spawn_win_rate_threshold = spawn_win_rate_threshold
        self.spawn_min_samples = spawn_min_samples
        self.current_round = 0

    def evolve_round(
        self,
        island_pool: IslandPool,
        round_stats: Dict,
    ) -> EvolutionReport:
        """
        执行一轮完整进化。
        
        Args:
            island_pool: 当前所有岛的池
            round_stats: 本轮评测统计，格式:
                {
                    "round_number": int,
                    "per_island": {
                        island_id: {
                            "best_strategy": StrategyDefinition,
                            "type_win_rates": {"algebra": 0.7, "geometry": 0.3, ...},
                            "failures": [{"question": ..., "expected": ..., "actual": ...}, ...]
                        }
                    },
                    "per_question_type": {
                        "algebra": {"best_win_rate": 0.8, "best_island": 0, "samples": 12},
                        "geometry": {"best_win_rate": 0.35, "best_island": 2, "samples": 8},
                    }
                }
        
        Returns:
            EvolutionReport: 本轮进化的完整报告
        """
        self.current_round += 1
        report = EvolutionReport(round_number=self.current_round)

        # Phase 1: Refine + Diverge for each island
        for island in island_pool.islands:
            island_stats = round_stats["per_island"].get(island.island_id, {})
            
            # Refine
            refined = self._refine_island(island, island_stats)
            if refined:
                island.add_strategy(refined)
                report.refined_strategies.append(refined)
                report.total_llm_calls += 1

            # Diverge
            diverged = self._diverge_island(island)
            if diverged:
                island.add_strategy(diverged)
                report.diverged_strategies.append(diverged)
                report.total_llm_calls += 1

        # Phase 2: Migration
        migration_records = self._migrate(island_pool)
        report.migrations = migration_records

        # Phase 3: Check Spawn
        question_type_stats = round_stats.get("per_question_type", {})
        spawn_record = self._check_spawn(island_pool, question_type_stats)
        if spawn_record:
            report.spawned_islands.append(spawn_record)
            report.total_llm_calls += 1

        return report

    def _refine_island(
        self,
        island: StrategyIsland,
        island_stats: Dict,
    ) -> Optional[StrategyDefinition]:
        """
        对单个岛执行 Refine 操作。
        
        1. 取岛内 elite_score 最高的策略
        2. 调用 DirectionGenerator.generate_refine()
        3. 验证变异幅度（≤2维）
        4. 返回新策略
        """
        best_strategy = island_stats.get("best_strategy")
        if not best_strategy:
            return None

        type_win_rates = island_stats.get("type_win_rates", {})
        failures = island_stats.get("failures", [])[:3]  # 最多取3条失败案例

        refined = self.direction_generator.generate_refine(
            best_strategy=best_strategy,
            type_stats=type_win_rates,
            failures=failures,
        )
        return refined

    def _diverge_island(
        self,
        island: StrategyIsland,
    ) -> Optional[StrategyDefinition]:
        """
        对单个岛执行 Diverge 操作。
        
        1. 获取岛的 perspective 和所有现有策略
        2. 调用 DirectionGenerator.generate_diverge()
        3. 验证多样性（≥3维不同）
        4. 返回新策略
        """
        existing_strategies = island.get_all_strategies()
        if not existing_strategies:
            return None

        diverged = self.direction_generator.generate_diverge(
            island_perspective=island.config.perspective,
            existing_strategies=existing_strategies,
        )
        return diverged

    def _migrate(self, island_pool: IslandPool) -> List[MigrationRecord]:
        """
        执行环形迁移 (0→1→2→3→4→0)。
        
        对每个岛：
        1. 选择 elite_score 最高的策略
        2. 计算与目标岛所有策略的最小距离
        3. 若距离 ≥ threshold 则接受迁移
        """
        records = []
        islands = island_pool.islands
        n = len(islands)

        if n < 2:
            return records

        for i in range(n):
            source = islands[i]
            target = islands[(i + 1) % n]
            
            candidate = source.get_top_strategy(k=1)
            if not candidate:
                continue
            candidate = candidate[0]

            min_distance = target.min_distance_to(candidate)
            accepted = min_distance >= self.migration_distance_threshold

            record = MigrationRecord(
                source_island_id=source.island_id,
                target_island_id=target.island_id,
                strategy_id=candidate.strategy_id,
                elite_score=candidate.elite_score,
                distance_to_nearest=min_distance,
                accepted=accepted,
            )
            records.append(record)

            if accepted:
                target.add_strategy(candidate.copy())

        return records

    def _check_spawn(
        self,
        island_pool: IslandPool,
        question_type_stats: Dict,
    ) -> Optional[SpawnRecord]:
        """
        检查是否需要动态开岛。
        
        条件：某题型所有岛最佳胜率 < 0.4 且样本 ≥ 5
        
        Returns:
            SpawnRecord if spawned, None otherwise
        """
        for q_type, stats in question_type_stats.items():
            best_win_rate = stats.get("best_win_rate", 1.0)
            samples = stats.get("samples", 0)

            if best_win_rate < self.spawn_win_rate_threshold and samples >= self.spawn_min_samples:
                # 收集失败案例
                failures = self._collect_failures_for_type(island_pool, q_type)
                per_island_rates = {
                    island.island_id: island.get_win_rate_for_type(q_type)
                    for island in island_pool.islands
                }
                existing_perspectives = [
                    island.config.perspective for island in island_pool.islands
                ]

                island_config, seed_strategy = self.direction_generator.generate_spawn(
                    question_type=q_type,
                    per_island_rates=per_island_rates,
                    failures=failures[:5],
                    existing_perspectives=existing_perspectives,
                )

                new_island = island_pool.add_island(island_config, seed_strategy)

                return SpawnRecord(
                    trigger_question_type=q_type,
                    trigger_round=self.current_round,
                    new_island_id=new_island.island_id,
                    perspective=island_config.perspective,
                    rationale=island_config.rationale,
                    seed_strategy_id=seed_strategy.strategy_id,
                )

        return None

    def _collect_failures_for_type(
        self, island_pool: IslandPool, question_type: str
    ) -> List[Dict]:
        """收集指定题型在所有岛上的失败案例"""
        failures = []
        for island in island_pool.islands:
            failures.extend(island.get_failures_for_type(question_type))
        return failures
```

### 3.2 DirectionGenerator 类

**文件：** `src/evoagent/direction_generator.py`

```python
import json
from typing import List, Dict, Tuple, Optional
from evoagent.strategy import StrategyDefinition
from evoagent.island import IslandConfig


class DirectionGenerator:
    """
    进化方向生成器。
    
    封装所有与 LLM 交互的 prompt 构建和输出解析逻辑。
    提供三种生成模式：Refine、Diverge、Spawn。
    """

    STRATEGY_DIMENSIONS = [
        "approach", "reasoning_style", "verification_method",
        "decomposition", "abstraction_level", "tool_usage",
        "error_handling", "explanation_depth"
    ]

    def __init__(self, llm_client, max_refine_dims: int = 2, min_diverge_dims: int = 3):
        self.llm_client = llm_client
        self.max_refine_dims = max_refine_dims
        self.min_diverge_dims = min_diverge_dims

    def generate_refine(
        self,
        best_strategy: StrategyDefinition,
        type_stats: Dict[str, float],
        failures: List[Dict],
    ) -> StrategyDefinition:
        """
        生成 Refine 策略：基于最优策略微调 1-2 个维度。
        
        Args:
            best_strategy: 岛内 elite_score 最高的策略
            type_stats: 各题型胜率 {"algebra": 0.7, "geometry": 0.3, ...}
            failures: 最近失败案例列表 (最多3条)
        
        Returns:
            微调后的新 StrategyDefinition
        """
        prompt = REFINE_PROMPT.format(
            strategy_json=json.dumps(best_strategy.to_dict(), indent=2),
            type_win_rates=json.dumps(type_stats, indent=2),
            failure_cases=self._format_failures(failures),
            max_dims=self.max_refine_dims,
        )

        response = self.llm_client.generate(prompt)
        new_strategy = self._parse_strategy_response(response)

        # 验证变异幅度
        changed_dims = self._count_changed_dims(best_strategy, new_strategy)
        if changed_dims > self.max_refine_dims:
            new_strategy = self._truncate_changes(
                best_strategy, new_strategy, self.max_refine_dims
            )

        return new_strategy

    def generate_diverge(
        self,
        island_perspective: str,
        existing_strategies: List[StrategyDefinition],
    ) -> StrategyDefinition:
        """
        生成 Diverge 策略：在岛视角内生成全新变种。
        
        Args:
            island_perspective: 岛的探索视角
            existing_strategies: 岛内所有现有策略
        
        Returns:
            全新的 StrategyDefinition（≥3维不同）
        """
        existing_summary = self._summarize_strategies(existing_strategies)
        prompt = DIVERGE_PROMPT.format(
            perspective=island_perspective,
            existing_strategies=existing_summary,
            min_different_dims=self.min_diverge_dims,
        )

        response = self.llm_client.generate(prompt)
        new_strategy = self._parse_strategy_response(response)

        # 验证多样性
        if not self._verify_diversity(new_strategy, existing_strategies):
            # 重试一次
            response = self.llm_client.generate(prompt + "\n\n⚠️ 上次生成的策略多样性不足，请确保至少3个维度与现有策略不同。")
            new_strategy = self._parse_strategy_response(response)

        return new_strategy

    def generate_spawn(
        self,
        question_type: str,
        per_island_rates: Dict[int, float],
        failures: List[Dict],
        existing_perspectives: List[str],
    ) -> Tuple[IslandConfig, StrategyDefinition]:
        """
        生成新岛的 perspective 和种子策略。
        
        Args:
            question_type: 触发开岛的题型
            per_island_rates: 各岛在该题型的胜率
            failures: 该题型的失败案例 (最多5条)
            existing_perspectives: 现有所有岛的 perspective
        
        Returns:
            (IslandConfig, StrategyDefinition) 元组
        """
        prompt = SPAWN_PROMPT.format(
            question_type=question_type,
            per_island_performance=json.dumps(per_island_rates, indent=2),
            failure_cases=self._format_failures(failures),
            existing_perspectives=json.dumps(existing_perspectives, indent=2, ensure_ascii=False),
        )

        response = self.llm_client.generate(prompt)
        parsed = json.loads(self._extract_json(response))

        island_config = IslandConfig(
            perspective=parsed["perspective"],
            rationale=parsed["rationale"],
        )
        seed_strategy = StrategyDefinition.from_dict(parsed["initial_strategy"])

        return island_config, seed_strategy

    # ── 内部辅助方法 ──

    def _parse_strategy_response(self, response: str) -> StrategyDefinition:
        """从 LLM 响应中提取 JSON 并转为 StrategyDefinition"""
        json_str = self._extract_json(response)
        data = json.loads(json_str)
        return StrategyDefinition.from_dict(data)

    def _extract_json(self, text: str) -> str:
        """从可能包含 markdown 代码块的文本中提取 JSON"""
        if "```json" in text:
            start = text.index("```json") + 7
            end = text.index("```", start)
            return text[start:end].strip()
        elif "```" in text:
            start = text.index("```") + 3
            end = text.index("```", start)
            return text[start:end].strip()
        return text.strip()

    def _count_changed_dims(
        self, original: StrategyDefinition, modified: StrategyDefinition
    ) -> int:
        """计算两个策略之间有多少个维度发生了变化"""
        count = 0
        for dim in self.STRATEGY_DIMENSIONS:
            if getattr(original, dim, None) != getattr(modified, dim, None):
                count += 1
        return count

    def _truncate_changes(
        self,
        original: StrategyDefinition,
        modified: StrategyDefinition,
        max_dims: int,
    ) -> StrategyDefinition:
        """将变化维度截断至 max_dims 个（保留变化最大的维度）"""
        changes = []
        for dim in self.STRATEGY_DIMENSIONS:
            orig_val = getattr(original, dim, None)
            mod_val = getattr(modified, dim, None)
            if orig_val != mod_val:
                changes.append((dim, mod_val))

        # 只保留前 max_dims 个变化，其余恢复为原值
        result = original.copy()
        for dim, val in changes[:max_dims]:
            setattr(result, dim, val)
        return result

    def _verify_diversity(
        self,
        new_strategy: StrategyDefinition,
        existing: List[StrategyDefinition],
    ) -> bool:
        """验证新策略与所有现有策略至少有 min_diverge_dims 维不同"""
        for existing_s in existing:
            diff_count = self._count_changed_dims(existing_s, new_strategy)
            if diff_count < self.min_diverge_dims:
                return False
        return True

    def _format_failures(self, failures: List[Dict]) -> str:
        """格式化失败案例为可读文本"""
        if not failures:
            return "(无失败案例)"
        lines = []
        for i, f in enumerate(failures, 1):
            lines.append(f"案例{i}: 题目={f.get('question', 'N/A')}")
            lines.append(f"  预期={f.get('expected', 'N/A')}")
            lines.append(f"  实际={f.get('actual', 'N/A')}")
        return "\n".join(lines)

    def _summarize_strategies(self, strategies: List[StrategyDefinition]) -> str:
        """生成现有策略的摘要文本"""
        summaries = []
        for s in strategies:
            summaries.append(json.dumps(s.to_dict(), indent=2, ensure_ascii=False))
        return "\n---\n".join(summaries)
```

### 3.3 EvolutionReport Dataclass

（已在 3.1 中定义，此处补充使用示例）

```python
# 使用示例
report = EvolutionReport(round_number=3)
report.refined_strategies.append(refined_s1)
report.diverged_strategies.append(diverged_s1)
report.total_llm_calls = 10

print(f"Round {report.round_number}: "
      f"{report.total_new_strategies} new strategies, "
      f"{len(report.migrations)} migrations, "
      f"{len(report.spawned_islands)} spawned islands, "
      f"{report.total_llm_calls} LLM calls")
```

### 3.4 Prompt 模板

#### REFINE_PROMPT

```python
REFINE_PROMPT = """You are an AI strategy optimizer. Your task is to REFINE an existing problem-solving strategy by making small, targeted improvements.

## Current Best Strategy (8 dimensions)
{strategy_json}

## Performance by Question Type
{type_win_rates}

## Recent Failure Cases
{failure_cases}

## Instructions
1. Analyze the failure cases and low-performing question types
2. Identify which 1-{max_dims} dimensions to adjust to address the weaknesses
3. Make MINIMAL changes — only modify what's necessary
4. Keep the strategy's core approach intact

## Output Format
Return ONLY a JSON object with all 8 dimensions. Mark changed dimensions with a comment.

```json
{{
  "approach": "...",
  "reasoning_style": "...",
  "verification_method": "...",
  "decomposition": "...",
  "abstraction_level": "...",
  "tool_usage": "...",
  "error_handling": "...",
  "explanation_depth": "..."
}}
```

IMPORTANT: Change at most {max_dims} dimensions. The rest MUST remain identical to the original."""
```

#### DIVERGE_PROMPT

```python
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
Return ONLY a JSON object with all 8 dimensions:

```json
{{
  "approach": "...",
  "reasoning_style": "...",
  "verification_method": "...",
  "decomposition": "...",
  "abstraction_level": "...",
  "tool_usage": "...",
  "error_handling": "...",
  "explanation_depth": "..."
}}
```

IMPORTANT: At least {min_different_dims} dimensions must be SUBSTANTIALLY different from every existing strategy."""
```

#### SPAWN_PROMPT

```python
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
  "perspective": "A concise description of the new island's unique angle/philosophy",
  "initial_strategy": {{
    "approach": "...",
    "reasoning_style": "...",
    "verification_method": "...",
    "decomposition": "...",
    "abstraction_level": "...",
    "tool_usage": "...",
    "error_handling": "...",
    "explanation_depth": "..."
  }},
  "rationale": "Why this perspective and strategy should succeed where others failed"
}}
```

IMPORTANT: The perspective must be DISTINCT from all existing perspectives. Think outside the box."""
```

---

## 4. 数据流

```
┌────────────────────────────────────────────────────────────────────────┐
│                        main_multipath.py                               │
│                                                                        │
│  for batch in question_batches:                                        │
│      results = evaluate_batch(batch, island_pool)     ◄── 评测         │
│      round_stats = aggregate_stats(results)           ◄── 统计         │
│      report = island_evolver.evolve_round(            ◄── 进化         │
│          island_pool, round_stats                                      │
│      )                                                                 │
│      log_evolution(report)                            ◄── 日志         │
└────────────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌────────────────────────────────────────────────────────────────────────┐
│                     IslandEvolver.evolve_round()                       │
│                                                                        │
│  Input:                                                                │
│    island_pool: IslandPool (5+ islands, each with strategies)          │
│    round_stats: {per_island: {...}, per_question_type: {...}}          │
│                                                                        │
│  Processing:                                                           │
│    1. For each island:                                                 │
│       ├─ _refine_island() → DirectionGenerator.generate_refine()       │
│       │   └─ LLM call → parse JSON → StrategyDefinition               │
│       └─ _diverge_island() → DirectionGenerator.generate_diverge()     │
│           └─ LLM call → parse JSON → StrategyDefinition               │
│    2. _migrate() → ring topology copy                                  │
│    3. _check_spawn() → DirectionGenerator.generate_spawn()             │
│       └─ LLM call → parse JSON → (IslandConfig, StrategyDefinition)   │
│                                                                        │
│  Output:                                                               │
│    EvolutionReport {                                                   │
│      round_number, refined_strategies[], diverged_strategies[],        │
│      migrations[], spawned_islands[], total_llm_calls                  │
│    }                                                                   │
└────────────────────────────────────────────────────────────────────────┘
```

**关键数据类型流转：**

| 阶段 | 输入 | 输出 |
|------|------|------|
| Refine | `StrategyDefinition` + `type_stats` + `failures` | `StrategyDefinition` (1-2维变化) |
| Diverge | `perspective: str` + `List[StrategyDefinition]` | `StrategyDefinition` (≥3维不同) |
| Migrate | `IslandPool` | `List[MigrationRecord]` |
| Spawn | `question_type` + `per_island_rates` + `failures` + `perspectives` | `(IslandConfig, StrategyDefinition)` |

---

## 5. 文件结构

```
evoagent/
├── src/
│   └── evoagent/
│       ├── island_evolver.py          ◄── EE-503 IslandEvolver 类
│       ├── direction_generator.py     ◄── EE-502 DirectionGenerator 类
│       ├── prompts/
│       │   ├── refine_prompt.py       ◄── EE-102 REFINE_PROMPT
│       │   ├── diverge_prompt.py      ◄── EE-202 DIVERGE_PROMPT
│       │   └── spawn_prompt.py        ◄── EE-402 SPAWN_PROMPT
│       ├── strategy.py               ◄── (QP) StrategyDefinition
│       ├── island.py                  ◄── (SI) StrategyIsland/IslandPool
│       └── main_multipath.py         ◄── EE-501 集成入口
├── tests/
│   ├── test_refine.py                ◄── EE-601~604
│   ├── test_diverge.py               ◄── EE-605~609
│   ├── test_spawn.py                 ◄── EE-610~613
│   ├── test_migration.py             ◄── EE-614~615
│   ├── test_island_evolver.py        ◄── EE-616~620 集成测试
│   └── test_regression.py            ◄── EE-621~623
├── docs/
│   └── design/
│       └── EE_EVOLUTION_ENGINE_DEV.md ◄── 本文档
└── logs/
    └── evolution_log.jsonl            ◄── EE-404 进化日志
```

---

## 6. 开发路线图

### Phase 1: Refine + Diverge (1.5 天)

| 时间 | 任务 | 编号 |
|------|------|------|
| Day 1 上午 | 创建 `direction_generator.py` 骨架 + REFINE_PROMPT | EE-502, EE-102 |
| Day 1 上午 | 实现 `generate_refine()` + 输出解析 | EE-101, EE-103 |
| Day 1 下午 | 实现 `generate_diverge()` + DIVERGE_PROMPT | EE-201, EE-202, EE-203 |
| Day 1 下午 | 编写 Refine + Diverge 单元测试 | EE-601~609 |
| Day 2 上午 | 创建 `island_evolver.py` 骨架 | EE-503 |
| Day 2 上午 | 实现 `evolve_round()` / `_refine_island()` / `_diverge_island()` | EE-003 |
| Day 2 上午 | 实现轮次管理器 | EE-001, EE-002 |

### Phase 2: 迁移 + 动态开岛 (1 天)

| 时间 | 任务 | 编号 |
|------|------|------|
| Day 2 下午 | 实现 `_migrate()` 环形迁移 | EE-301, EE-302, EE-303 |
| Day 2 下午 | 编写迁移单元测试 | EE-614~615 |
| Day 3 上午 | 实现 `_check_spawn()` + SPAWN_PROMPT | EE-401, EE-402, EE-403 |
| Day 3 上午 | 实现变异幅度控制 + 多样性验证 | EE-104, EE-204 |
| Day 3 上午 | 编写 Spawn 单元测试 | EE-610~613 |

### Phase 3: 集成 + 测试 (0.5 天)

| 时间 | 任务 | 编号 |
|------|------|------|
| Day 3 下午 | 集成到 `main_multipath.py` | EE-501 |
| Day 3 下午 | 编写集成测试 | EE-616~620 |
| Day 3 下午 | 回归测试 + 性能验证 | EE-621~623 |
| Day 3 下午 | 开岛日志 + 文档收尾 | EE-404 |

---

## 7. 设计决策记录

### EE-DD-01: Refine 变异幅度限制为 2 维

**决策：** Refine 操作最多修改 2 个维度。

**原因：** 
- Refine 的目标是**微调**，不是重新设计
- 改太多维度会让 Refine 退化为 Diverge，失去区分度
- 2 维变化足以修正特定弱点而不破坏整体策略

**替代方案：** 无限制 → 已拒绝（会与 Diverge 重叠）

### EE-DD-02: Diverge 要求 ≥3 维不同

**决策：** Diverge 生成的策略必须与岛内所有现有策略至少 3 个维度不同。

**原因：**
- 确保真正的探索多样性
- 8维中至少3维不同 = 37.5% 差异率，足以产生行为差异
- 少于3维可能只是 Refine 的加强版

### EE-DD-03: 环形迁移拓扑

**决策：** 使用固定环形拓扑 `0→1→2→3→4→0`。

**原因：**
- 实现简单，确定性强
- 每个岛恰好接收一个来源的迁移，避免过度同质化
- 环形保证信息最终能传遍所有岛（N轮后）

**替代方案：** 全连接迁移 → 已拒绝（会导致快速趋同）；随机迁移 → 已拒绝（不可复现）

### EE-DD-04: 迁移距离阈值 0.3

**决策：** 迁移候选策略与目标岛最近策略的距离必须 ≥ 0.3。

**原因：**
- 防止迁入与岛内已有策略过于相似的策略
- 0.3 是经验值，对应 8 维中约 2-3 维有显著差异
- 太低则迁移无意义，太高则几乎无法迁移

### EE-DD-05: 开岛触发条件 win_rate < 0.4 且 samples ≥ 5

**决策：** 双条件触发。

**原因：**
- `win_rate < 0.4`：表示所有岛都在该题型上表现不佳
- `samples ≥ 5`：避免因样本不足导致误判
- 两者结合确保开岛有统计意义

### EE-DD-06: 每轮每岛固定产出 2 个新策略

**决策：** 每个岛每轮固定产出 1 个 Refine + 1 个 Diverge。

**原因：**
- 简单可预测：5 岛 = 10 个新策略/轮
- LLM 调用成本可控
- 足以在合理轮数内覆盖策略空间

**替代方案：** 根据岛表现动态调整 → Phase 2 考虑

### EE-DD-07: Prompt 模板硬编码为 Python 字符串

**决策：** Prompt 模板直接写在 Python 文件中，不使用外部模板引擎。

**原因：**
- 项目规模小，无需 Jinja2 等额外依赖
- Python f-string / `.format()` 足够灵活
- 版本控制友好，prompt 变更可通过 git diff 追踪

### EE-DD-08: EvolutionReport 作为返回值而非事件

**决策：** `evolve_round()` 返回 `EvolutionReport` dataclass。

**原因：**
- 同步调用模型，简单直观
- 调用方可以自由决定如何处理报告（日志、展示、存储）
- 无需引入事件系统或消息队列

---

## 8. 风险与缓解

| 编号 | 风险 | 概率 | 影响 | 缓解措施 |
|------|------|------|------|----------|
| R-01 | LLM 返回格式不合法（非 JSON） | 中 | 高 | 重试机制（最多2次）+ JSON 提取逻辑 + fallback 策略 |
| R-02 | Refine 退化为无变化（原样返回） | 低 | 中 | 检测变化维度数，=0 时强制重试 |
| R-03 | Diverge 无法满足 ≥3 维不同 | 中 | 中 | 重试1次；仍失败则降级为 ≥2 维并记录警告 |
| R-04 | 动态开岛过多导致资源膨胀 | 低 | 高 | 设置最大岛数上限（默认10），达上限后不再开岛 |
| R-05 | 迁移导致岛间策略趋同 | 中 | 中 | 距离阈值 ≥0.3 过滤 + 每轮最多迁移 1 个策略/岛 |
| R-06 | LLM 调用成本超预期 | 低 | 中 | 每轮调用上限 = 2×岛数+1，可通过配置降低 |
| R-07 | 进化不收敛（策略越来越差） | 中 | 高 | 保留历史最优策略不被淘汰（精英保留）；监控 elite_score 趋势 |
| R-08 | Spawn prompt 生成重复 perspective | 低 | 低 | 在 prompt 中明确列出现有 perspectives 并要求不重复 |

---

## 9. 术语表

| 术语 | 定义 |
|------|------|
| **Strategy / 策略** | 一组 8 维参数，定义 AI 解题的方法论（`StrategyDefinition`） |
| **Island / 岛** | 策略的隔离进化单元，每个岛有独立的 `perspective` 和策略集合 |
| **IslandPool / 岛池** | 所有岛的集合，提供全局管理接口 |
| **Perspective / 视角** | 岛的探索方向描述，约束该岛内策略的设计空间 |
| **Refine / 微调** | 对最优策略做 1-2 维的精细调整，保持核心不变 |
| **Diverge / 发散** | 在岛视角内生成全新策略，要求 ≥3 维不同 |
| **Migration / 迁移** | 将一个岛的精英策略复制到相邻岛 |
| **Spawn / 开岛** | 为失败题型创建全新岛，含新视角和种子策略 |
| **Elite Score / 精英分** | 策略的综合评分，用于排名和迁移选择 |
| **Round / 轮次** | 一批评测题的完整执行周期（默认 10 题/轮） |
| **Ring Topology / 环形拓扑** | 迁移路径：0→1→2→...→N-1→0 |
| **Distance / 距离** | 两个策略在 8 维空间中的差异度量 |
| **Win Rate / 胜率** | 策略在特定题型上的正确率 |
| **Batch / 批次** | 同一轮次中的一组评测题 |

---

*文档结束。模块代号 EE，基线项目 EvoAgent。*
