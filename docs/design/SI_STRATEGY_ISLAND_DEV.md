# Strategy Island 开发文档

| 字段 | 值 |
|------|------|
| **模块代号** | SI (Strategy Island) |
| **基线项目** | EvoAgent |
| **创建日期** | 2026-03-20 |
| **依赖** | QP 模块 — `StrategyDefinition`, `strategy_distance()` |
| **预计工期** | 3 天 |
| **作者** | happyclaw01 |

---

## 1. 架构总览

```
┌─────────────────────────────────────────────────────────────────┐
│                        Strategy Island 架构                      │
├─────────────────────────────────────────────────────────────────┤
│                                                                   │
│  ┌──────────────┐                                                │
│  │ IslandConfig  │  name / perspective / max_size / elite_ratio  │
│  │  (dataclass)  │  fitness_weight / novelty_weight              │
│  └──────┬───────┘                                                │
│         │ 1:1                                                     │
│         ▼                                                         │
│  ┌──────────────────┐                                            │
│  │  StrategyIsland   │  策略池 + 适应度 + 新颖度 + 淘汰          │
│  │    (单岛管理)     │  elite_score / sample / evict              │
│  └──────┬───────────┘                                            │
│         │ N:1                                                     │
│         ▼                                                         │
│  ┌──────────────────┐     ┌────────────────┐                     │
│  │   IslandPool      │────▶│  Ring Migration │                    │
│  │   (多岛管理)      │     │  0→1→2→3→4→0   │                    │
│  └──────┬───────────┘     └────────────────┘                     │
│         │                                                         │
│         ├──────────────────┬──────────────────┐                  │
│         ▼                  ▼                  ▼                   │
│  ┌────────────┐    ┌────────────────┐  ┌──────────────┐         │
│  │ DigestStore │    │ IslandStore    │  │  OpenViking   │         │
│  │  (JSON本地) │    │ (本地JSON后端) │  │  (远程后端)   │         │
│  └────────────┘    └────────────────┘  └──────────────┘         │
│                                                                   │
├─────────────────────────────────────────────────────────────────┤
│  集成层:  multi_path.py ◄── IslandPool.sample_all()             │
│           openviking_context.py ◄── 岛/策略结构 fallback         │
└─────────────────────────────────────────────────────────────────┘
```

### 数据流向

```
Question(question_type)
    │
    ▼
IslandPool.sample_all(question_type)
    │
    ├─→ Island_0 (信息追踪)  ──→ sample() ──→ Strategy_A
    ├─→ Island_1 (机制分析)  ──→ sample() ──→ Strategy_B
    ├─→ Island_2 (历史类比)  ──→ sample() ──→ Strategy_C
    ├─→ Island_3 (市场信号)  ──→ sample() ──→ Strategy_D
    └─→ Island_4 (对抗验证)  ──→ sample() ──→ Strategy_E
    │
    ▼
[Strategy_A, Strategy_B, Strategy_C, Strategy_D, Strategy_E]
    │
    ▼
multi_path.py → 5 条探索路径（路径数 = 岛数）
```

---

## 2. 功能清单与编号

### 2.1 第一层：数据结构

| 编号 | 功能 | 描述 | 优先级 | 状态 |
|------|------|------|--------|------|
| **SI-001** | IslandConfig dataclass | `name`/`perspective`/`max_size=10`/`elite_ratio=0.2`/`fitness_weight=0.6`/`novelty_weight=0.4` | P0 | ✅ |
| **SI-002** | 初始 5 岛定义 | 信息追踪 / 机制分析 / 历史类比 / 市场信号 / 对抗验证 | P0 | ✅ |
| **SI-003** | 岛元数据存储格式 | `_meta.json` — 岛配置 + 统计信息 | P1 | ✅ |

### 2.2 第二层：单岛管理

| 编号 | 功能 | 描述 | 优先级 | 状态 |
|------|------|------|--------|------|
| **SI-101** | StrategyIsland 类 | 持有策略池 + IslandConfig，单岛生命周期管理 | P0 | ✅ |
| **SI-102** | elite_score 计算 | `fitness_weight × fitness_percentile + novelty_weight × novelty_percentile` | P0 | ✅ |
| **SI-103** | fitness 计算 | 题型条件化胜率：样本 ≥ 3 用题型胜率，否则用全局胜率 | P0 | ✅ |
| **SI-104** | novelty 计算 | 与岛内其他策略的平均 `strategy_distance`（k-NN, k=全岛） | P0 | ✅ |
| **SI-105** | 淘汰机制（确定性拥挤） | 岛满 → 找最相似非精英 → 新策略 elite_score 更高则替换 | P0 | ✅ |
| **SI-106** | 策略采样 `sample()` | 选该题型上胜率最高的策略 | P0 | ✅ |
| **SI-107** | 冷启动处理 | 没有题型数据时退回全局胜率 | P1 | ✅ |
| **SI-108** | 精英保护 | top N% 策略不参与淘汰 | P1 | ✅ |

### 2.3 第三层：多岛管理

| 编号 | 功能 | 描述 | 优先级 | 状态 |
|------|------|------|--------|------|
| **SI-201** | IslandPool 类 | 持有所有岛，统一调度接口 | P0 | ✅ |
| **SI-202** | `sample_all(question_type)` | 所有岛各出 1 策略，返回列表 | P0 | ✅ |
| **SI-203** | 岛间环形迁移 | 0→1→2→3→4→0 环形拓扑 | P1 | ✅ |
| **SI-204** | 迁移筛选 | 过 elite_score 阈值 + 距离 ≥ 0.3 | P1 | ✅ |
| **SI-205** | 动态开岛接口 | 供 EE 模块调用创建新岛 | P1 | ✅ |
| **SI-206** | 岛数动态感知 | 路径数 = 岛数，动态调整 | P1 | ✅ |

### 2.4 第四层：存储层

| 编号 | 功能 | 描述 | 优先级 | 状态 |
|------|------|------|--------|------|
| **SI-301** | 本地 JSON 后端 | `data/islands/island_X/_meta.json` + `strategies.json` | P0 | ✅ |
| **SI-302** | OpenViking 后端 | `viking://agent/skills/islands/` 远程存储 | P2 | ⏭️ |
| **SI-303** | 策略战绩记录 | `data/results/task_results.jsonl` 追加写入 | P0 | ✅ |
| **SI-304** | L0/L1/L2 分层加载 | L0=配置, L1=策略摘要, L2=完整策略体 | P1 | ✅ |

### 2.5 第五层：集成

| 编号 | 功能 | 描述 | 优先级 | 状态 |
|------|------|------|--------|------|
| **SI-401** | multi_path.py 改造 | `_select_strategies()` 改为 `IslandPool.sample_all()` | P0 | ✅ |
| **SI-402** | 路径数动态化 | `路径数 = 岛数`（不再硬编码） | P0 | ✅ |
| **SI-403** | openviking_context.py 改造 | fallback 改为岛/策略结构 | P1 | ✅ |

### 2.6 测试

| 编号 | 功能 | 描述 | 优先级 | 状态 |
|------|------|------|--------|------|
| **SI-501** | IslandConfig 创建测试 | 默认值、自定义值、边界值 | P0 | ✅ |
| **SI-502** | IslandConfig 验证测试 | 非法参数拒绝 | P0 | ✅ |
| **SI-503** | elite_score 计算测试 | 权重正确性、百分位排序 | P0 | ✅ |
| **SI-504** | fitness 条件化测试 | 题型样本 ≥ 3 走题型、< 3 走全局 | P0 | ✅ |
| **SI-505** | novelty 距离测试 | k-NN 平均距离计算 | P0 | ✅ |
| **SI-506** | 淘汰机制：岛未满不淘汰 | 直接添加 | P0 | ✅ |
| **SI-507** | 淘汰机制：找最相似非精英 | 相似度排序正确 | P0 | ✅ |
| **SI-508** | 淘汰机制：score 比较 | 新高替换、新低不替换 | P0 | ✅ |
| **SI-509** | 采样逻辑：题型最高胜率 | 正确选出最佳策略 | P0 | ✅ |
| **SI-510** | 采样逻辑：空岛返回 None | 边界条件 | P0 | ✅ |
| **SI-511** | 冷启动处理测试 | 无题型数据退回全局 | P1 | ✅ |
| **SI-512** | 精英保护测试 | top N% 不被淘汰 | P1 | ✅ |
| **SI-513** | IslandPool 创建测试 | 5 岛初始化 | P0 | ✅ |
| **SI-514** | sample_all 测试 | 每岛出 1 策略 | P0 | ✅ |
| **SI-515** | 环形迁移路径测试 | 0→1→2→3→4→0 | P1 | ✅ |
| **SI-516** | 迁移筛选测试 | elite_score + 距离过滤 | P1 | ✅ |
| **SI-517** | 距离过滤阈值测试 | 距离 < 0.3 被拒 | P1 | ✅ |
| **SI-518** | 动态开岛测试 | 新岛注册后 sample_all 包含 | P1 | ✅ |
| **SI-519** | 存储读写测试 | JSON 序列化/反序列化 | P0 | ✅ |
| **SI-520** | 战绩记录追加测试 | JSONL 格式正确 | P0 | ✅ |
| **SI-521** | 集成：5 岛全出路径 | multi_path 获得 5 条路径 | P1 | ✅ |
| **SI-522** | 集成：策略多样性 | 5 策略互不相同 | P1 | ✅ |
| **SI-523** | 集成：存储读写端到端 | 保存→重启→加载一致 | P1 | ✅ |
| **SI-524** | 集成：QP 模块对接 | StrategyDefinition 兼容 | P1 | ✅ |
| **SI-525** | 集成：openviking fallback | 远程不可用走本地 | P1 | ⏭️ |
| **SI-526** | 回归：现有 37 测试不变 | 全绿 | P0 | ✅ |
| **SI-527** | 回归：multi_path 行为兼容 | 输出格式不变 | P0 | ✅ |
| **SI-528** | 回归：性能基线 | 采样延迟 < 50ms | P0 | ✅ |

---

## 3. IslandConfig 详细接口

```python
# evoagent/strategy_island.py

from dataclasses import dataclass, field
from typing import Optional


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
        """验证参数合法性。"""
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
            raise ValueError(f"fitness_weight + novelty_weight must equal 1.0, got {total}")

    @property
    def elite_count(self) -> int:
        """精英策略数量（向上取整，至少 1）。"""
        import math
        return max(1, math.ceil(self.max_size * self.elite_ratio))

    def to_dict(self) -> dict:
        """序列化为字典。"""
        ...

    @classmethod
    def from_dict(cls, data: dict) -> "IslandConfig":
        """从字典反序列化。"""
        ...
```

---

## 4. 初始 5 岛定义

```python
# evoagent/strategy_island.py (续)

DEFAULT_ISLANDS: list[IslandConfig] = [
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
```

---

## 5. StrategyIsland 详细接口

```python
# evoagent/strategy_island.py (续)

from typing import Optional
from evoagent.question_pool import StrategyDefinition, strategy_distance


@dataclass
class StrategyRecord:
    """岛内策略的运行时记录。

    Attributes:
        strategy: QP 模块的 StrategyDefinition
        wins: 各题型胜利次数 {question_type: int}
        attempts: 各题型尝试次数 {question_type: int}
        total_wins: 全局胜利次数
        total_attempts: 全局尝试次数
    """
    strategy: StrategyDefinition
    wins: dict[str, int] = field(default_factory=dict)
    attempts: dict[str, int] = field(default_factory=dict)
    total_wins: int = 0
    total_attempts: int = 0

    def win_rate(self, question_type: Optional[str] = None) -> float:
        """计算胜率。

        Args:
            question_type: 题型名称。None 表示全局胜率。

        Returns:
            胜率 [0.0, 1.0]。无数据时返回 0.0。
        """
        ...

    def record_result(self, question_type: str, won: bool) -> None:
        """记录一次对局结果。

        Args:
            question_type: 题型名称
            won: 是否胜出
        """
        ...


class StrategyIsland:
    """单个策略岛，管理一组同视角策略的生命周期。

    Attributes:
        config: 岛配置
        _records: 岛内策略记录列表
    """

    def __init__(self, config: IslandConfig) -> None:
        """初始化策略岛。

        Args:
            config: 岛配置
        """
        self.config: IslandConfig = config
        self._records: list[StrategyRecord] = []

    # ── 核心属性 ─────────────────────────────────

    @property
    def size(self) -> int:
        """当前岛内策略数量。"""
        ...

    @property
    def is_full(self) -> bool:
        """岛是否已满。"""
        ...

    @property
    def strategies(self) -> list[StrategyDefinition]:
        """返回岛内所有策略（只读副本）。"""
        ...

    # ── SI-102: elite_score ──────────────────────

    def elite_score(self, record: StrategyRecord,
                    question_type: Optional[str] = None) -> float:
        """计算策略的精英分数。

        公式: fitness_weight × fitness_percentile + novelty_weight × novelty_percentile

        Args:
            record: 目标策略记录
            question_type: 题型（用于 fitness 条件化）

        Returns:
            精英分数 [0.0, 1.0]
        """
        ...

    # ── SI-103: fitness ──────────────────────────

    def fitness(self, record: StrategyRecord,
                question_type: Optional[str] = None) -> float:
        """计算策略适应度（条件化胜率）。

        规则:
            - 该题型样本 >= 3: 使用题型胜率
            - 该题型样本 < 3: 退回全局胜率（SI-107 冷启动）

        Args:
            record: 目标策略记录
            question_type: 题型名称

        Returns:
            适应度值 [0.0, 1.0]
        """
        ...

    def _fitness_percentile(self, record: StrategyRecord,
                            question_type: Optional[str] = None) -> float:
        """计算策略在岛内的适应度百分位排名。

        Args:
            record: 目标策略记录
            question_type: 题型名称

        Returns:
            百分位值 [0.0, 1.0]
        """
        ...

    # ── SI-104: novelty ──────────────────────────

    def novelty(self, record: StrategyRecord) -> float:
        """计算策略的新颖度（与岛内其他策略的平均距离）。

        使用 QP 模块的 strategy_distance() 函数，
        计算与岛内所有其他策略的距离均值（k-NN, k=全岛）。

        Args:
            record: 目标策略记录

        Returns:
            新颖度值 [0.0, 1.0]。岛内仅 1 个策略时返回 1.0。
        """
        ...

    def _novelty_percentile(self, record: StrategyRecord) -> float:
        """计算策略在岛内的新颖度百分位排名。

        Args:
            record: 目标策略记录

        Returns:
            百分位值 [0.0, 1.0]
        """
        ...

    # ── SI-105: 淘汰机制 ─────────────────────────

    def add_strategy(self, strategy: StrategyDefinition,
                     question_type: Optional[str] = None) -> bool:
        """向岛中添加策略，必要时触发淘汰。

        流程:
            1. 岛未满: 直接添加，返回 True
            2. 岛已满:
               a. 计算新策略的 elite_score
               b. 找到岛内与新策略最相似的非精英策略
               c. 若新策略 elite_score > 该策略: 替换，返回 True
               d. 否则: 拒绝添加，返回 False

        Args:
            strategy: 待添加的策略
            question_type: 当前题型（用于 elite_score 计算）

        Returns:
            是否成功添加
        """
        ...

    def _find_most_similar_non_elite(
        self, strategy: StrategyDefinition,
        question_type: Optional[str] = None
    ) -> Optional[StrategyRecord]:
        """找到岛内与目标策略最相似的非精英策略。

        Args:
            strategy: 目标策略
            question_type: 当前题型

        Returns:
            最相似的非精英策略记录，若全是精英则返回 None
        """
        ...

    def _get_elite_records(self,
                           question_type: Optional[str] = None
                           ) -> list[StrategyRecord]:
        """获取当前精英策略列表（SI-108）。

        按 elite_score 降序排列，取 top elite_count 个。

        Args:
            question_type: 当前题型

        Returns:
            精英策略记录列表
        """
        ...

    # ── SI-106: 采样 ─────────────────────────────

    def sample(self, question_type: Optional[str] = None) -> Optional[StrategyDefinition]:
        """采样一个策略（该题型上胜率最高者）。

        Args:
            question_type: 题型名称。None 使用全局胜率。

        Returns:
            最佳策略。岛为空时返回 None。
        """
        ...

    # ── 记录管理 ──────────────────────────────────

    def record_result(self, strategy: StrategyDefinition,
                      question_type: str, won: bool) -> None:
        """记录策略的一次对局结果。

        Args:
            strategy: 参与对局的策略
            question_type: 题型名称
            won: 是否胜出
        """
        ...

    def get_record(self, strategy: StrategyDefinition) -> Optional[StrategyRecord]:
        """获取策略的运行时记录。

        Args:
            strategy: 目标策略

        Returns:
            策略记录，不存在则返回 None
        """
        ...

    # ── 序列化 ────────────────────────────────────

    def to_dict(self) -> dict:
        """序列化为字典（含 config + 所有 records）。"""
        ...

    @classmethod
    def from_dict(cls, data: dict) -> "StrategyIsland":
        """从字典反序列化。"""
        ...
```

---

## 6. IslandPool 详细接口

```python
# evoagent/island_pool.py

from typing import Optional
from evoagent.strategy_island import (
    IslandConfig, StrategyIsland, StrategyRecord,
    DEFAULT_ISLANDS, StrategyDefinition, strategy_distance,
)


class IslandPool:
    """多岛管理器，统一调度所有策略岛。

    Attributes:
        _islands: 岛列表（有序，索引即岛 ID）
    """

    def __init__(self, configs: Optional[list[IslandConfig]] = None) -> None:
        """初始化岛池。

        Args:
            configs: 岛配置列表。None 使用 DEFAULT_ISLANDS。
        """
        self._islands: list[StrategyIsland] = [
            StrategyIsland(cfg) for cfg in (configs or DEFAULT_ISLANDS)
        ]

    # ── 核心属性 ─────────────────────────────────

    @property
    def island_count(self) -> int:
        """当前岛数（= 路径数）。"""
        return len(self._islands)

    @property
    def islands(self) -> list[StrategyIsland]:
        """所有岛（只读副本）。"""
        return list(self._islands)

    def get_island(self, name: str) -> Optional[StrategyIsland]:
        """按名称查找岛。

        Args:
            name: 岛名称

        Returns:
            匹配的岛，不存在则返回 None
        """
        ...

    # ── SI-202: sample_all ───────────────────────

    def sample_all(self, question_type: Optional[str] = None
                   ) -> list[Optional[StrategyDefinition]]:
        """所有岛各采样 1 个策略。

        Args:
            question_type: 题型名称

        Returns:
            策略列表，长度 = island_count。空岛位置为 None。
        """
        return [island.sample(question_type) for island in self._islands]

    # ── SI-203/204: 环形迁移 ─────────────────────

    def migrate_ring(self, question_type: Optional[str] = None) -> list[dict]:
        """执行一轮环形迁移 (0→1→2→3→4→0)。

        迁移筛选条件 (SI-204):
            1. 源岛精英策略才有资格迁移
            2. 策略与目标岛所有策略的最小距离 >= 0.3

        Args:
            question_type: 当前题型（用于 elite_score 计算）

        Returns:
            迁移日志列表 [{"from": int, "to": int, "strategy": str, "accepted": bool}, ...]
        """
        ...

    def _can_migrate(self, strategy: StrategyDefinition,
                     target_island: StrategyIsland,
                     min_distance: float = 0.3) -> bool:
        """判断策略是否满足迁移到目标岛的距离条件。

        Args:
            strategy: 候选迁移策略
            target_island: 目标岛
            min_distance: 最小距离阈值

        Returns:
            是否满足迁移条件
        """
        ...

    # ── SI-205: 动态开岛 ─────────────────────────

    def add_island(self, config: IslandConfig) -> StrategyIsland:
        """动态创建并注册新岛（供 EE 模块调用）。

        Args:
            config: 新岛配置

        Returns:
            新创建的岛实例

        Raises:
            ValueError: 同名岛已存在
        """
        ...

    def remove_island(self, name: str) -> bool:
        """移除指定岛（需岛为空或仅含可淘汰策略）。

        Args:
            name: 岛名称

        Returns:
            是否成功移除
        """
        ...

    # ── 批量操作 ──────────────────────────────────

    def add_strategy(self, island_name: str,
                     strategy: StrategyDefinition,
                     question_type: Optional[str] = None) -> bool:
        """向指定岛添加策略。

        Args:
            island_name: 岛名称
            strategy: 待添加策略
            question_type: 当前题型

        Returns:
            是否成功添加
        """
        ...

    def record_result(self, island_name: str,
                      strategy: StrategyDefinition,
                      question_type: str, won: bool) -> None:
        """记录指定岛中策略的对局结果。

        Args:
            island_name: 岛名称
            strategy: 参与对局的策略
            question_type: 题型名称
            won: 是否胜出
        """
        ...

    def broadcast_strategy(self, strategy: StrategyDefinition,
                           question_type: Optional[str] = None
                           ) -> dict[str, bool]:
        """尝试向所有岛投放策略（广播模式）。

        Args:
            strategy: 待投放策略
            question_type: 当前题型

        Returns:
            {island_name: accepted} 结果映射
        """
        ...

    # ── 统计 ──────────────────────────────────────

    def stats(self) -> dict:
        """返回全池统计信息。

        Returns:
            {
                "island_count": int,
                "total_strategies": int,
                "islands": [{"name": str, "size": int, "avg_fitness": float}, ...]
            }
        """
        ...

    # ── 序列化 ────────────────────────────────────

    def to_dict(self) -> dict:
        """序列化为字典。"""
        ...

    @classmethod
    def from_dict(cls, data: dict) -> "IslandPool":
        """从字典反序列化。"""
        ...
```

---

## 7. IslandStore 详细接口

```python
# evoagent/island_store.py

from pathlib import Path
from typing import Optional, Protocol
from evoagent.island_pool import IslandPool
from evoagent.strategy_island import StrategyIsland


class IslandBackend(Protocol):
    """存储后端协议（策略模式）。"""

    def save_island(self, island_id: int, island: StrategyIsland) -> None:
        """保存单个岛。"""
        ...

    def load_island(self, island_id: int) -> Optional[dict]:
        """加载单个岛数据。"""
        ...

    def save_pool(self, pool: IslandPool) -> None:
        """保存整个岛池。"""
        ...

    def load_pool(self) -> Optional[dict]:
        """加载整个岛池数据。"""
        ...

    def save_result(self, result: dict) -> None:
        """追加一条对局结果。"""
        ...

    def load_results(self, limit: Optional[int] = None) -> list[dict]:
        """加载对局结果列表。"""
        ...


class LocalJsonBackend:
    """本地 JSON 存储后端 (SI-301)。

    目录结构:
        data/islands/
            island_0/
                _meta.json      # IslandConfig 序列化
                strategies.json # StrategyRecord 列表
            island_1/
                ...
        data/results/
            task_results.jsonl  # 逐行 JSON
    """

    def __init__(self, base_dir: Path) -> None:
        """初始化本地存储后端。

        Args:
            base_dir: 数据根目录 (通常为 project_root/data)
        """
        self.base_dir: Path = base_dir
        self.islands_dir: Path = base_dir / "islands"
        self.results_dir: Path = base_dir / "results"

    def save_island(self, island_id: int, island: StrategyIsland) -> None:
        """保存单个岛到 data/islands/island_{id}/。

        创建目录（如不存在），写入:
            - _meta.json: 岛配置
            - strategies.json: 策略记录列表

        Args:
            island_id: 岛索引
            island: 岛实例
        """
        ...

    def load_island(self, island_id: int) -> Optional[dict]:
        """从本地加载单个岛数据。

        Args:
            island_id: 岛索引

        Returns:
            岛数据字典，目录不存在则返回 None
        """
        ...

    def save_pool(self, pool: IslandPool) -> None:
        """保存整个岛池。遍历所有岛调用 save_island。

        Args:
            pool: 岛池实例
        """
        ...

    def load_pool(self) -> Optional[dict]:
        """加载整个岛池数据。

        Returns:
            岛池数据字典，无数据则返回 None
        """
        ...

    def save_result(self, result: dict) -> None:
        """追加一条对局结果到 task_results.jsonl。

        Args:
            result: 对局结果字典，格式:
                {
                    "timestamp": str (ISO 8601),
                    "question_type": str,
                    "island_name": str,
                    "strategy_id": str,
                    "won": bool,
                    "score": float
                }
        """
        ...

    def load_results(self, limit: Optional[int] = None) -> list[dict]:
        """加载对局结果。

        Args:
            limit: 最多加载条数（从末尾开始）。None 加载全部。

        Returns:
            对局结果列表（按时间正序）
        """
        ...


class OpenVikingBackend:
    """OpenViking 远程存储后端 (SI-302, P2)。

    URI: viking://agent/skills/islands/
    """

    def __init__(self, base_uri: str = "viking://agent/skills/islands/") -> None:
        """初始化 OpenViking 后端。

        Args:
            base_uri: Viking 存储根 URI
        """
        self.base_uri: str = base_uri

    def save_island(self, island_id: int, island: StrategyIsland) -> None:
        """保存岛到 OpenViking。"""
        ...

    def load_island(self, island_id: int) -> Optional[dict]:
        """从 OpenViking 加载岛。"""
        ...

    def save_pool(self, pool: IslandPool) -> None:
        """保存岛池到 OpenViking。"""
        ...

    def load_pool(self) -> Optional[dict]:
        """从 OpenViking 加载岛池。"""
        ...

    def save_result(self, result: dict) -> None:
        """追加结果到 OpenViking。"""
        ...

    def load_results(self, limit: Optional[int] = None) -> list[dict]:
        """从 OpenViking 加载结果。"""
        ...


class IslandStore:
    """岛存储管理器，支持多后端 + L0/L1/L2 分层加载 (SI-304)。

    加载层级:
        L0 — 仅配置 (IslandConfig): 极快，用于 UI 展示
        L1 — 配置 + 策略摘要 (id/name/win_rate): 中等，用于采样决策
        L2 — 完整数据 (含所有 StrategyRecord): 完整，用于淘汰/迁移计算
    """

    def __init__(self, primary: IslandBackend,
                 fallback: Optional[IslandBackend] = None) -> None:
        """初始化存储管理器。

        Args:
            primary: 主存储后端（通常为 LocalJsonBackend）
            fallback: 备用后端（通常为 OpenVikingBackend）
        """
        self.primary: IslandBackend = primary
        self.fallback: Optional[IslandBackend] = fallback

    def save(self, pool: IslandPool) -> None:
        """保存岛池到主后端（可选同步到备用）。

        Args:
            pool: 岛池实例
        """
        ...

    def load(self, level: int = 2) -> Optional[IslandPool]:
        """加载岛池。

        Args:
            level: 加载层级 (0/1/2)

        Returns:
            岛池实例。无数据返回 None。主后端失败自动 fallback。
        """
        ...

    def save_result(self, result: dict) -> None:
        """保存对局结果。

        Args:
            result: 对局结果字典
        """
        ...

    def load_results(self, limit: Optional[int] = None) -> list[dict]:
        """加载对局结果。

        Args:
            limit: 最多加载条数
        """
        ...
```

---

## 8. 集成层接口变更

### 8.1 multi_path.py 变更 (SI-401, SI-402)

```python
# evoagent/multi_path.py — 变更部分

from evoagent.island_pool import IslandPool


class MultiPathExplorer:
    """多路径探索器。"""

    def __init__(self, island_pool: Optional[IslandPool] = None, **kwargs) -> None:
        """初始化。

        Args:
            island_pool: 策略岛池。None 将创建默认 5 岛。
        """
        self._pool: IslandPool = island_pool or IslandPool()
        # ... 其他初始化 ...

    @property
    def path_count(self) -> int:
        """路径数 = 岛数（动态，SI-402）。"""
        return self._pool.island_count

    def _select_strategies(self, question_type: Optional[str] = None
                           ) -> list[Optional["StrategyDefinition"]]:
        """选择策略（SI-401: 委托给 IslandPool）。

        旧实现: 硬编码 5 策略
        新实现: IslandPool.sample_all(question_type)

        Args:
            question_type: 题型名称

        Returns:
            策略列表，长度 = path_count
        """
        return self._pool.sample_all(question_type)

    def explore(self, question: str, question_type: Optional[str] = None,
                **kwargs) -> list[dict]:
        """执行多路径探索。

        路径数现在动态等于岛数，不再硬编码。

        Args:
            question: 问题文本
            question_type: 题型名称
            **kwargs: 传递给各路径的额外参数

        Returns:
            探索结果列表，每个元素对应一条路径
        """
        strategies = self._select_strategies(question_type)
        # ... 为每个策略创建并执行探索路径 ...
        ...

    def report_results(self, results: list[dict],
                       question_type: str) -> None:
        """回报探索结果，更新岛内策略战绩。

        Args:
            results: explore() 的返回值
            question_type: 题型名称
        """
        ...
```

### 8.2 openviking_context.py 变更 (SI-403)

```python
# evoagent/openviking_context.py — 变更部分

from evoagent.island_pool import IslandPool
from evoagent.island_store import IslandStore, LocalJsonBackend, OpenVikingBackend


class OpenVikingContext:
    """OpenViking 上下文管理器。"""

    def __init__(self, island_store: Optional[IslandStore] = None,
                 **kwargs) -> None:
        """初始化。

        SI-403: fallback 改为岛/策略结构。

        Args:
            island_store: 岛存储管理器。None 使用默认本地后端。
        """
        if island_store is None:
            primary = LocalJsonBackend(Path("data"))
            fallback = OpenVikingBackend()
            island_store = IslandStore(primary=primary, fallback=fallback)
        self._store: IslandStore = island_store

    def load_context(self) -> IslandPool:
        """加载上下文（优先 OpenViking，fallback 本地岛/策略结构）。

        Returns:
            岛池实例
        """
        pool = self._store.load(level=2)
        if pool is None:
            pool = IslandPool()  # 默认 5 岛空池
        return pool

    def save_context(self, pool: IslandPool) -> None:
        """保存上下文。

        Args:
            pool: 岛池实例
        """
        self._store.save(pool)
```

---

## 9. 岛元数据格式 (SI-003)

### `_meta.json` 格式

```json
{
  "version": "1.0",
  "island_id": 0,
  "config": {
    "name": "信息追踪",
    "perspective": "从信息源头出发，追踪关键数据流向和信号传播路径",
    "max_size": 10,
    "elite_ratio": 0.2,
    "fitness_weight": 0.6,
    "novelty_weight": 0.4
  },
  "stats": {
    "current_size": 7,
    "total_evaluations": 142,
    "avg_fitness": 0.63,
    "avg_novelty": 0.41,
    "created_at": "2026-03-20T10:00:00Z",
    "last_updated": "2026-03-20T15:30:00Z"
  }
}
```

### `strategies.json` 格式

```json
[
  {
    "strategy": {
      "id": "strat_abc123",
      "name": "深度信息链追踪",
      "description": "...",
      "perspective": "信息追踪"
    },
    "wins": {"geopolitical": 5, "economic": 3},
    "attempts": {"geopolitical": 8, "economic": 4},
    "total_wins": 8,
    "total_attempts": 12
  }
]
```

### `task_results.jsonl` 格式（每行一条）

```json
{"timestamp": "2026-03-20T15:30:00Z", "question_type": "geopolitical", "island_name": "信息追踪", "strategy_id": "strat_abc123", "won": true, "score": 0.85}
```

---

## 10. 数据流完整图

```
┌─────────────────────────────────────────────────────────────────────┐
│                         完整数据流                                    │
├─────────────────────────────────────────────────────────────────────┤
│                                                                       │
│  ① 问题输入                                                          │
│  ┌──────────────┐                                                    │
│  │  Question     │  question_text + question_type                    │
│  └──────┬───────┘                                                    │
│         │                                                             │
│  ② 策略采样                                                          │
│         ▼                                                             │
│  ┌──────────────────────────────────────────────────────┐            │
│  │  MultiPathExplorer.explore(question, question_type)   │            │
│  │    └─→ _select_strategies(question_type)              │            │
│  │          └─→ IslandPool.sample_all(question_type)     │            │
│  │                ├─→ Island_0.sample(qt) → Strategy_A   │            │
│  │                ├─→ Island_1.sample(qt) → Strategy_B   │            │
│  │                ├─→ Island_2.sample(qt) → Strategy_C   │            │
│  │                ├─→ Island_3.sample(qt) → Strategy_D   │            │
│  │                └─→ Island_4.sample(qt) → Strategy_E   │            │
│  └──────┬───────────────────────────────────────────────┘            │
│         │                                                             │
│  ③ 路径执行                                                          │
│         ▼                                                             │
│  ┌─────────────────────────────────────┐                             │
│  │  Path_0..4 并行执行                  │                             │
│  │    每条路径: Strategy + LLM → Answer │                             │
│  └──────┬──────────────────────────────┘                             │
│         │                                                             │
│  ④ 结果评估                                                          │
│         ▼                                                             │
│  ┌─────────────────────────────────────┐                             │
│  │  Evaluator 评分 + 胜者判定           │                             │
│  │    → winners: list[bool]            │                             │
│  └──────┬──────────────────────────────┘                             │
│         │                                                             │
│  ⑤ 结果回写                                                          │
│         ▼                                                             │
│  ┌─────────────────────────────────────────────────┐                 │
│  │  MultiPathExplorer.report_results()              │                 │
│  │    ├─→ IslandPool.record_result(island, strat,   │                 │
│  │    │                            qt, won)         │                 │
│  │    │     └─→ StrategyIsland.record_result()      │                 │
│  │    │           └─→ StrategyRecord.record_result() │                │
│  │    └─→ IslandStore.save_result()                  │                │
│  │          └─→ task_results.jsonl (追加)             │                │
│  └──────┬──────────────────────────────────────────┘                 │
│         │                                                             │
│  ⑥ 周期性维护（每 N 轮）                                              │
│         ▼                                                             │
│  ┌─────────────────────────────────────────┐                         │
│  │  IslandPool.migrate_ring(question_type)  │                         │
│  │    环形迁移: 精英策略跨岛传播             │                         │
│  │    筛选: elite_score + 距离 ≥ 0.3        │                         │
│  └──────┬──────────────────────────────────┘                         │
│         │                                                             │
│  ⑦ 持久化                                                            │
│         ▼                                                             │
│  ┌─────────────────────────────────────────┐                         │
│  │  IslandStore.save(pool)                  │                         │
│  │    ├─→ LocalJsonBackend (主)             │                         │
│  │    └─→ OpenVikingBackend (备, P2)        │                         │
│  └─────────────────────────────────────────┘                         │
│                                                                       │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 11. 文件结构

### 新增文件

| 文件 | 说明 |
|------|------|
| `evoagent/strategy_island.py` | IslandConfig + StrategyRecord + StrategyIsland + DEFAULT_ISLANDS |
| `evoagent/island_pool.py` | IslandPool 多岛管理器 |
| `evoagent/island_store.py` | IslandBackend 协议 + LocalJsonBackend + OpenVikingBackend + IslandStore |
| `tests/test_strategy_island.py` | SI-501~SI-512 单元测试 |
| `tests/test_island_pool.py` | SI-513~SI-520 单元测试 |
| `tests/test_island_store.py` | SI-519~SI-520 存储测试 |
| `tests/test_si_integration.py` | SI-521~SI-528 集成/回归测试 |

### 修改文件

| 文件 | 变更说明 |
|------|------|
| `evoagent/multi_path.py` | SI-401: `_select_strategies()` 委托 IslandPool; SI-402: `path_count` 动态化 |
| `evoagent/openviking_context.py` | SI-403: fallback 改为岛/策略结构 |

### 不修改文件

| 文件 | 原因 |
|------|------|
| `evoagent/question_pool.py` | QP 模块仅被依赖，不需改动 |
| `evoagent/digest_engine.py` | 消费路径结果，接口不变 |
| `evoagent/llm_client.py` | 底层 LLM 调用，不涉及 |
| `evoagent/config.py` | 如需新增 SI 配置项，在 Phase 3 追加 |

---

## 12. 开发路线图

### Phase 1: 数据结构 + 单岛（第 1 天）

| 时间 | 任务 | 编号 | 产出 |
|------|------|------|------|
| 上午 | IslandConfig dataclass | SI-001 | `strategy_island.py` 基础 |
| 上午 | DEFAULT_ISLANDS 定义 | SI-002 | 5 岛配置 |
| 上午 | StrategyRecord dataclass | — | 运行时记录 |
| 下午 | StrategyIsland 类骨架 | SI-101 | 类结构 |
| 下午 | elite_score / fitness / novelty | SI-102~104 | 核心算法 |
| 下午 | 淘汰机制 | SI-105 | 确定性拥挤 |
| 下午 | 策略采样 | SI-106 | sample() |
| 晚上 | 单元测试 SI-501~SI-512 | — | 测试覆盖 |

**Day 1 里程碑**: `strategy_island.py` 完成，所有单岛测试通过。

### Phase 2: 多岛 + 存储（第 2 天）

| 时间 | 任务 | 编号 | 产出 |
|------|------|------|------|
| 上午 | IslandPool 类 | SI-201~202 | `island_pool.py` |
| 上午 | 环形迁移 | SI-203~204 | migrate_ring() |
| 下午 | 动态开岛 | SI-205~206 | add_island() |
| 下午 | LocalJsonBackend | SI-301, SI-303 | `island_store.py` |
| 下午 | 岛元数据格式 | SI-003 | _meta.json |
| 晚上 | L0/L1/L2 分层加载 | SI-304 | IslandStore |
| 晚上 | 单元测试 SI-513~SI-520 | — | 测试覆盖 |

**Day 2 里程碑**: `island_pool.py` + `island_store.py` 完成，多岛测试通过。

### Phase 3: 集成 + 测试（第 3 天）

| 时间 | 任务 | 编号 | 产出 |
|------|------|------|------|
| 上午 | multi_path.py 改造 | SI-401~402 | 动态路径 |
| 上午 | openviking_context.py 改造 | SI-403 | fallback 结构 |
| 下午 | 冷启动处理 | SI-107 | 退回全局 |
| 下午 | 精英保护 | SI-108 | elite 不淘汰 |
| 下午 | 集成测试 | SI-521~525 | 端到端验证 |
| 晚上 | 回归测试 | SI-526~528 | 全绿 + 性能 |
| 晚上 | 文档更新 | — | README + CHANGELOG |

**Day 3 里程碑**: 全部集成完成，37 + N 测试全绿，性能基线达标。

---

## 13. 设计决策记录

### SI-DD-01: 岛配置不可变 (frozen dataclass)

- **决策**: `IslandConfig` 使用 `frozen=True`
- **原因**: 岛配置在创建后不应变更，防止运行时意外修改导致不一致
- **替代方案**: 可变 dataclass + 手动约束 → 易出错，弃用

### SI-DD-02: 精英分数 = 加权百分位（非原始值）

- **决策**: 使用岛内百分位排名而非原始 fitness/novelty 值
- **原因**: 百分位归一化消除量纲差异，使权重直观可控
- **替代方案**: 原始值加权 → fitness 和 novelty 量纲不同，权重难调

### SI-DD-03: 确定性拥挤淘汰（非随机）

- **决策**: 淘汰时选择与新策略最相似的非精英，确定性替换
- **原因**: 确定性行为更易测试、调试和复现
- **替代方案**: 锦标赛选择 → 引入随机性，测试困难

### SI-DD-04: 题型条件化胜率 + 冷启动退回

- **决策**: 样本 ≥ 3 用题型胜率，< 3 退回全局
- **原因**: 3 是信号与噪声的平衡点，避免小样本过拟合
- **替代方案**: 贝叶斯先验 → 更优但实现复杂，后续可升级

### SI-DD-05: 环形迁移拓扑

- **决策**: 0→1→2→3→4→0 固定环形
- **原因**: 简单、公平、每岛恰好有 1 个输入和 1 个输出
- **替代方案**: 全连接 → 迁移爆炸，O(N²) 复杂度；随机图 → 难以复现

### SI-DD-06: 迁移距离阈值 0.3

- **决策**: 策略与目标岛所有策略的最小距离 ≥ 0.3 才允许迁移
- **原因**: 防止相似策略跨岛复制导致多样性丧失
- **替代方案**: 无阈值 → 趋同风险；0.5 → 过严，迁移率过低

### SI-DD-07: 策略模式存储后端

- **决策**: Protocol + 多后端（Local / OpenViking）
- **原因**: 本地开发用 JSON，生产可切换 OpenViking，解耦存储
- **替代方案**: 硬编码单后端 → 不可扩展

### SI-DD-08: L0/L1/L2 分层加载

- **决策**: 三层加载策略，按需加载深度
- **原因**: 减少不必要的 IO，UI 展示只需 L0，采样只需 L1
- **替代方案**: 始终全量加载 → 岛数增大时性能下降

### SI-DD-09: 路径数 = 岛数（动态绑定）

- **决策**: `MultiPathExplorer.path_count` 直接读取 `IslandPool.island_count`
- **原因**: 消除硬编码，支持 EE 动态开岛后自动扩展路径
- **替代方案**: 配置文件指定路径数 → 与岛数脱钩，易不一致

### SI-DD-10: 采样选题型最高胜率（贪心）

- **决策**: `sample()` 返回题型上胜率最高的策略
- **原因**: 简单高效，利用题型特化信息
- **替代方案**: 
  - ε-greedy → 后续迭代可升级（SI-106 扩展点）
  - UCB → 更优但计算开销大，留给未来优化

---

## 14. 风险与缓解

| # | 风险 | 概率 | 影响 | 缓解措施 |
|---|------|------|------|----------|
| R1 | QP 模块 `strategy_distance()` 接口变更 | 低 | 高 | 定义明确的接口契约；集成测试 SI-524 覆盖 |
| R2 | 5 岛视角划分不合理，某些岛长期空置 | 中 | 中 | 监控各岛 size/fitness；SI-205 动态开岛支持调整 |
| R3 | 冷启动期间所有策略全局胜率相同，采样退化为随机 | 高 | 低 | 可接受 — 冷启动本质就是探索期；积累数据后自然改善 |
| R4 | 环形迁移导致优势策略快速扩散，丧失多样性 | 中 | 高 | SI-204 距离阈值 0.3 控制；监控岛间策略相似度 |
| R5 | JSON 存储在高并发下不安全（文件锁） | 低 | 中 | 当前单进程场景无问题；P2 OpenViking 后端解决 |
| R6 | 淘汰机制过于激进，有价值的"慢热"策略被清除 | 中 | 中 | SI-108 精英保护兜底；考虑引入"最低存活轮数" |
| R7 | 路径数=岛数导致 LLM 调用成本线性增长 | 低 | 中 | 岛数初始 5 可控；动态开岛有上限检查 |
| R8 | 3 天工期偏紧，Phase 3 集成可能延期 | 中 | 中 | Phase 1/2 严格控制范围；P1 功能可延后 |

---

## 15. 术语表

| 术语 | 英文 | 定义 |
|------|------|------|
| 策略岛 | Strategy Island | 一组共享分析视角的策略集合，独立进化 |
| 岛池 | Island Pool | 所有策略岛的集合，统一管理接口 |
| 视角 | Perspective | 岛的分析切入角度（如信息追踪、机制分析等） |
| 精英分数 | Elite Score | `fitness_weight × fitness_pct + novelty_weight × novelty_pct` |
| 适应度 | Fitness | 策略的题型条件化胜率 |
| 新颖度 | Novelty | 策略与岛内其他策略的平均距离 |
| 确定性拥挤 | Deterministic Crowding | 淘汰时选择最相似非精英替换的机制 |
| 环形迁移 | Ring Migration | 岛间按固定环形拓扑传播精英策略 |
| 冷启动 | Cold Start | 策略缺乏题型数据时退回全局胜率 |
| 精英保护 | Elite Protection | top N% 策略不参与淘汰 |
| 题型 | Question Type | 问题的分类标签，用于条件化适应度计算 |
| 迁移筛选 | Migration Filter | elite_score 通过 + 距离 ≥ 0.3 的迁移准入条件 |
| L0/L1/L2 | Load Level 0/1/2 | 分层加载深度：配置/摘要/完整数据 |
| QP 模块 | Question Pool | 依赖模块，提供 StrategyDefinition 和 strategy_distance() |
| EE 模块 | Exploration Engine | 调用方模块，可动态创建新岛 |
| 战绩 | Result Record | 策略在特定题型上的胜/败记录 |
| 百分位 | Percentile | 策略在岛内某指标上的排名占比 [0.0, 1.0] |

---

*文档结束 — SI Strategy Island 开发文档 v1.0*
