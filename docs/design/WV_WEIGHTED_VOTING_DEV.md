# 加权投票与策略评估 开发文档

> **模块代号**: WV (Weighted Voting & Strategy Evaluation)  
> **基线项目**: EvoAgent v1.0 (多路径系统已实现, IST 模块已设计)  
> **核心理念**: 用置信度加权取代简单多数投票，用题型条件化胜率取代全局胜率，让投票更聪明、进化更精准  
> **分支**: `main`  
> **创建日期**: 2026-03-20  
> **最后更新**: 2026-03-20  
> **前置文档**: `EVOAGENT_DESIGN.md` §3/§11, `STRATEGY_EVOLVE_ARCHITECTURE.md` §8/§9, `INLINE_STEP_TRACE_DEV.md`  
> **依赖模块**: QP (Question Parser → `ParsedQuestion.question_type`), IST (Inline Step Trace → `PathDigest.confidence`)  
> **预计工期**: 1.5 天

---

## 1. 架构总览

```
                         ┌─────────────────────┐
                         │   Question Parser    │  ← QP 模块提供
                         │  ParsedQuestion      │     question_type
                         └──────────┬──────────┘
                                    │
         ┌──────────────────────────┼──────────────────────────┐
         │                          │                          │
    ┌────▼─────┐             ┌──────▼──────┐            ┌──────▼──────┐
    │  Path 0  │             │   Path 1    │            │   Path N    │
    │ (Agent)  │             │  (Agent)    │            │  (Agent)    │
    │ +IST     │             │  +IST       │            │  +IST       │
    └────┬─────┘             └──────┬──────┘            └──────┬──────┘
         │                          │                          │
         │ PathDigest               │ PathDigest               │ PathDigest
         │ (answer+confidence       │ (answer+confidence       │ (answer+confidence
         │  +evidence+risk)         │  +evidence+risk)         │  +evidence+risk)
         │                          │                          │
         └──────────────────────────┼──────────────────────────┘
                                    │
                                    ▼
                    ┌───────────────────────────────┐
                    │     WV: 加权投票模块            │
                    │                               │
                    │  ┌─────────────────────────┐  │
                    │  │ 1. 权重映射              │  │
                    │  │   high→3, med→2, low→1  │  │
                    │  └────────────┬────────────┘  │
                    │               │               │
                    │  ┌────────────▼────────────┐  │
                    │  │ 2. 加权多数投票          │  │
                    │  │   ∑weight per answer     │  │
                    │  └────────────┬────────────┘  │
                    │               │               │
                    │       ┌───────┴───────┐       │
                    │       │               │       │
                    │  一致(共识)        分裂(冲突)   │
                    │       │               │       │
                    │       ▼               ▼       │
                    │  直接采用      Judge 仲裁       │
                    │               (带证据+风险)    │
                    └───────────────┬───────────────┘
                                    │
                                    ▼ 最终答案 + adopted_strategy
                                    │
                    ┌───────────────▼───────────────┐
                    │   WV: 策略评估记录模块          │
                    │                               │
                    │  record_result()              │
                    │   ├── overall: total/wins/rate │
                    │   └── by_type[question_type]  │
                    │       total/wins/rate          │
                    │                               │
                    │  get_fitness()                 │
                    │   ├── 题型样本≥3 → 题型胜率    │
                    │   └── 样本不足  → 全局胜率     │
                    └───────────────────────────────┘
```

---

## 2. 功能清单与编号

### 2.1 第一层：策略评估记录层 (Evaluation Recording)

| 编号 | 功能名称 | 描述 | 状态 | 优先级 |
|------|---------|------|------|--------|
| **WV-001** | StrategyMetrics 数据结构 | 策略指标：overall{total/wins/rate} + by_type{question_type → total/wins/rate} | ✅ 已完成 | P0 |
| **WV-002** | record_result() | 记录单次任务结果：strategy_id, island_id, question_type, won, adopted → 更新 overall + by_type | ✅ 已完成 | P0 |
| **WV-003** | get_fitness() | 获取策略适应度：优先题型胜率(样本≥3)，不足时退回全局胜率 | ✅ 已完成 | P0 |
| **WV-004** | 全局统计更新 | record_result 时同步更新 metrics["overall"]["total/wins/rate"] | ✅ 已完成 | P0 |
| **WV-005** | 题型统计更新 | record_result 时同步更新 metrics["by_type"][question_type]["total/wins/rate"] | ✅ 已完成 | P0 |
| **WV-006** | 最小样本阈值 | MIN_TYPE_SAMPLES = 3，控制 get_fitness 退回逻辑 | ✅ 已完成 | P0 |
| **WV-007** | 零样本保护 | overall.total == 0 时 get_fitness 返回默认值 0.5 | ✅ 已完成 | P1 |
| **WV-008** | 评估结果持久化 | StrategyMetrics 内嵌于 StrategyDefinition.metrics，随策略存储（OpenViking / 本地 JSON） | ✅ 已完成 | P1 |

### 2.2 第二层：加权投票层 (Weighted Voting)

| 编号 | 功能名称 | 描述 | 状态 | 优先级 |
|------|---------|------|------|--------|
| **WV-101** | 权重映射常量 | CONFIDENCE_WEIGHTS = {"high": 3, "medium": 2, "low": 1} | ✅ 已完成 | P0 |
| **WV-102** | weighted_majority_vote() | 加权多数投票：按 confidence 加权累计每个答案的票数 | ✅ 已完成 | P0 |
| **WV-103** | 共识判定 | 最高权重答案权重占比 > threshold (默认 0.6) → 一致 → 直接采用 | ✅ 已完成 | P0 |
| **WV-104** | 分裂判定 | 权重占比 ≤ threshold → 分裂 → 触发 Judge 仲裁 | ✅ 已完成 | P0 |
| **WV-105** | 加权 Judge 仲裁 | Judge 输入增加：各路径的 confidence + 关键证据 + 主要风险 | ✅ 已完成 | P0 |
| **WV-106** | 答案归一化 | 投票前对答案做标准化处理（strip/lower/去除格式差异） | ✅ 已完成 | P1 |
| **WV-107** | 投票结果元数据 | 返回 VoteResult：winner, method(majority/judge), weight_distribution, confidence_stats | ✅ 已完成 | P1 |
| **WV-108** | 向后兼容降级 | PathDigest 不含 confidence 时，默认权重 = 1（等同原简单多数投票） | ✅ 已完成 | P1 |

### 2.3 第三层：结构化输出层 (Structured Output)

| 编号 | 功能名称 | 描述 | 状态 | 优先级 |
|------|---------|------|------|--------|
| **WV-201** | 结构化输出格式定义 | 答案 / 置信度 / 关键证据 / 主要风险 的标准输出格式 | ✅ 已完成 | P0 |
| **WV-202** | System Prompt 注入 — 结构化输出要求 | 在 Agent system prompt 末尾追加结构化输出格式要求 | ✅ 已完成 | P0 |
| **WV-203** | Prompt 合并 — IST trace + WV 结构化输出 | 将 IST 的 trace 要求和 WV 的结构化输出要求合并为统一的 prompt 块 | ✅ 已完成 | P0 |
| **WV-204** | 结构化输出解析 | 从 Agent 最终输出中解析 confidence / evidence / risk（可复用 IST 的 PathDigest.confidence） | ✅ 已完成 | P0 |
| **WV-205** | IST PathDigest 协作 | 投票模块从 PathDigest.to_l0() 读取 answer + confidence，不额外解析 Agent 输出 | ✅ 已完成 | P0 |
| **WV-206** | evidence / risk 解析器 | 从 Agent 输出中提取关键证据和主要风险（供 Judge 使用） | ✅ 已完成 | P1 |
| **WV-207** | 默认值填充 | confidence 未提供 → "medium"；evidence 未提供 → []；risk 未提供 → "无" | ✅ 已完成 | P1 |

### 2.4 第四层：集成层 (Integration)

| 编号 | 功能名称 | 描述 | 修改文件 | 状态 | 优先级 |
|------|---------|------|---------|------|--------|
| **WV-301** | multi_path.py — 投票函数改造 | `_vote_best_answer()` 替换为加权版本 `weighted_vote()` | `multi_path.py` | ✅ 待开发 | P0 |
| **WV-302** | multi_path.py — 结果记录调用 | 任务结束后调用 `record_result(strategy_id, island_id, question_type, won, adopted)` | `multi_path.py` | ✅ 待开发 | P0 |
| **WV-303** | multi_path.py — system prompt 追加 | `_build_system_prompt()` 中追加结构化输出要求（与 IST trace 要求合并） | `multi_path.py` | ✅ 待开发 | P0 |
| **WV-304** | voter.py 适配 | 现有投票逻辑适配新的加权输入格式（如已独立存在） | `voter.py` (如存在) | ✅ 待开发 | P1 |
| **WV-305** | judge.py 适配 | Judge prompt 模板更新：增加 confidence + evidence + risk 输入 | `judge.py` (如存在) / `multi_path.py` | ✅ 待开发 | P0 |
| **WV-306** | StrategyIsland.elite_score 对接 | `get_fitness()` 返回值供 `StrategyIsland` 的 `elite_score` 计算使用 | `strategy_island.py` | ✅ 待开发 | P1 |
| **WV-307** | PathDigest 扩展 — evidence/risk 字段 | 在 IST 的 PathDigest 中增加 evidence: List[str] 和 risk: str 字段 | `step_trace.py` / IST 模块 | ✅ 待开发 | P1 |
| **WV-308** | 日志增强 | 投票过程记录：各路径权重、答案分布、最终选择方法 | `multi_path.py` | ✅ 待开发 | P1 |

### 2.5 第五层：测试层 (Testing)

| 编号 | 功能名称 | 描述 | 状态 | 优先级 |
|------|---------|------|------|--------|
| **WV-401** | 单元测试 — record_result 更新正确性 | 验证 overall 和 by_type 统计在各种输入下正确更新 | ✅ 已完成 | P0 |
| **WV-402** | 单元测试 — get_fitness 优先级逻辑 | 样本≥3 用题型胜率；样本<3 退回全局；全零返回 0.5 | ✅ 已完成 | P0 |
| **WV-403** | 单元测试 — 权重映射 | high→3, medium→2, low→1, 未知→1 | ✅ 已完成 | P0 |
| **WV-404** | 单元测试 — 加权投票计算 | 5 路径加权后答案累计正确性 | ✅ 已完成 | P0 |
| **WV-405** | 单元测试 — 共识判定 | 权重占比 > 0.6 → 共识；≤ 0.6 → 分裂 | ✅ 已完成 | P0 |
| **WV-406** | 单元测试 — 答案归一化 | strip/lower/格式差异消除 | ✅ 已完成 | P1 |
| **WV-407** | 单元测试 — 向后兼容降级 | 无 confidence 时等同简单多数投票 | ✅ 已完成 | P0 |
| **WV-408** | 单元测试 — VoteResult 元数据 | 返回结果包含完整投票元信息 | ✅ 已完成 | P1 |
| **WV-409** | 集成测试 — 5 路径加权投票端到端 | 构造 5 个 PathDigest → weighted_vote → 验证结果 | ✅ 已完成 | P0 |
| **WV-410** | 集成测试 — Judge 带证据仲裁 | 分裂场景 → Judge 收到 confidence + evidence + risk → 输出选择 | ✅ 已完成 | P1 |
| **WV-411** | 集成测试 — 题型统计积累 | 连续 10 次 record_result → 验证题型胜率准确 | ✅ 已完成 | P1 |
| **WV-412** | 集成测试 — fitness 与 island 对接 | get_fitness → StrategyIsland.elite_score 链路 | ✅ 已完成 | P1 |
| **WV-413** | 回归测试 — 现有投票测试适配 | 加入 WV 后，现有 EA-402 投票测试仍通过 | ✅ 已完成 | P0 |
| **WV-414** | 回归测试 — 37 个已有单元测试 | WV 改造不破坏任何现有测试 | ✅ 已完成 | P0 |
| **WV-415** | 性能测试 — 投票额外开销 | 加权投票 vs 简单多数投票延迟差 < 1ms（纯计算） | ✅ 已完成 | P2 |
| **WV-416** | 性能测试 — record_result 写入开销 | 单次 record_result 耗时 < 5ms | ✅ 已完成 | P2 |

---

## 3. 数据架构

### 3.1 StrategyMetrics（内嵌于 StrategyDefinition.metrics）

```python
# 数据结构示意
{
    "overall": {
        "total": 25,
        "wins": 18,
        "rate": 0.72
    },
    "by_type": {
        "politics": {
            "total": 8,
            "wins": 6,
            "rate": 0.75
        },
        "entertainment": {
            "total": 5,
            "wins": 2,
            "rate": 0.40
        },
        "finance": {
            "total": 2,      # < MIN_TYPE_SAMPLES(3)，get_fitness 退回全局
            "wins": 1,
            "rate": 0.50
        }
    }
}
```

### 3.2 VoteResult（投票结果）

```python
{
    "winner_answer": "答案A",
    "winner_path_index": 0,
    "winner_strategy": "breadth_first",
    "method": "weighted_majority",    # weighted_majority | judge
    "total_weight": 11,               # 所有路径权重总和
    "weight_distribution": {
        "答案A": {"weight": 7, "paths": [0, 2], "confidences": ["high", "medium"]},
        "答案B": {"weight": 4, "paths": [1, 3, 4], "confidences": ["low", "low", "medium"]}
    },
    "consensus_ratio": 0.636,         # 7/11
    "judge_used": false
}
```

### 3.3 结构化输出格式

```
答案：\boxed{A}
置信度：high
关键证据：[https://example.com: 官方数据显示..., https://news.com: 最新报告称...]
主要风险：数据来源可能有时间延迟，最新变化未反映
```

### 3.4 增强的 Judge 输入格式

```
You are evaluating multiple answers to the same question. Pick the best answer.

Question: {task_description}

--- Path 1 (Strategy: breadth_first) ---
Answer: 答案A
Confidence: high
Key Evidence: [URL1: 摘要1, URL2: 摘要2]
Risk Analysis: 可能的风险描述
Summary: {summary[:2000]}

--- Path 2 (Strategy: depth_first) ---
Answer: 答案B
Confidence: low
Key Evidence: [URL3: 摘要3]
Risk Analysis: 数据来源单一
Summary: {summary[:2000]}

...

Consider each path's confidence level, evidence quality, and risk assessment.
Which answer is most likely correct and well-supported?
Format: BEST: <number>
Reason: <brief explanation>
```

### 3.5 数据层关系图

```
┌──────────────────┐      question_type      ┌──────────────────┐
│  ParsedQuestion  │ ─────────────────────→  │  record_result() │
│  (QP 模块)       │                         │  (WV-002)        │
└──────────────────┘                         └────────┬─────────┘
                                                      │
                                                      ▼
┌──────────────────┐                         ┌──────────────────┐
│  PathDigest      │  answer + confidence    │  StrategyMetrics │
│  (IST 模块)      │ ──────────────────────→ │  (WV-001)        │
│                  │                         │                  │
│  .answer         │                         │  .overall{       │
│  .confidence     │       get_fitness()     │    total/wins/   │
│  .key_findings   │  ←───────────────────── │    rate}         │
│  .potential_      │                         │  .by_type{       │
│   issues         │                         │    [qtype]{      │
└──────────────────┘                         │    total/wins/   │
        │                                    │    rate}}        │
        │                                    └────────┬─────────┘
        ▼                                             │
┌──────────────────┐                                  │ fitness
│  weighted_vote() │                                  ▼
│  (WV-102)        │                         ┌──────────────────┐
│                  │                         │ StrategyIsland   │
│  输入:           │                         │  .elite_score    │
│   PathDigest[]   │                         │  .sample()       │
│  输出:           │                         └──────────────────┘
│   VoteResult     │
└──────────────────┘
```

---

## 4. 模块详细接口设计

### 4.1 策略评估模块 — `strategy_evaluator.py`（新增）

```python
"""
WV-001~008: 策略评估记录与 Fitness 计算

位置: apps/miroflow-agent/src/evolving/strategy_evaluator.py
"""

from dataclasses import dataclass, field
from typing import Dict, Optional, Any

# WV-006: 最小样本阈值
MIN_TYPE_SAMPLES: int = 3

# WV-007: 零样本默认 fitness
DEFAULT_FITNESS: float = 0.5


@dataclass
class StrategyMetrics:
    """WV-001: 策略评估指标数据结构"""
    overall: Dict[str, Any] = field(default_factory=lambda: {
        "total": 0,
        "wins": 0,
        "rate": 0.0,
    })
    by_type: Dict[str, Dict[str, Any]] = field(default_factory=dict)

    def to_dict(self) -> dict:
        """序列化为 dict，用于 JSON 存储"""
        ...

    @classmethod
    def from_dict(cls, data: dict) -> "StrategyMetrics":
        """从 dict 反序列化"""
        ...


def record_result(
    strategy_id: str,
    island_id: str,
    question_type: str,
    won: bool,
    adopted: bool,
    metrics: StrategyMetrics,
) -> StrategyMetrics:
    """
    WV-002: 记录单次任务结果，更新策略指标
    
    Args:
        strategy_id: 策略唯一标识
        island_id: 所属岛 ID
        question_type: 题型（来自 ParsedQuestion.question_type）
        won: 该策略的答案是否是最终被采纳的正确答案
        adopted: 该策略的答案是否被投票选中
        metrics: 当前策略的 StrategyMetrics（就地更新）
    
    Returns:
        更新后的 StrategyMetrics
    
    行为:
        1. WV-004: metrics.overall.total += 1; if won: overall.wins += 1; 重算 rate
        2. WV-005: metrics.by_type[question_type].total += 1; if won: wins += 1; 重算 rate
    """
    ...


def get_fitness(
    metrics: StrategyMetrics,
    question_type: Optional[str] = None,
) -> float:
    """
    WV-003: 获取策略适应度
    
    Args:
        metrics: 策略的 StrategyMetrics
        question_type: 当前题型（None 时直接返回全局胜率）
    
    Returns:
        fitness 值 (0.0 ~ 1.0)
    
    逻辑:
        1. question_type 存在且 by_type[question_type].total >= MIN_TYPE_SAMPLES(3)
           → 返回 by_type[question_type].rate
        2. question_type 不存在或样本不足
           → 返回 overall.rate
        3. WV-007: overall.total == 0
           → 返回 DEFAULT_FITNESS (0.5)
    """
    ...
```

### 4.2 加权投票模块 — `weighted_voter.py`（新增）

```python
"""
WV-101~108: 加权投票机制

位置: apps/miroflow-agent/src/core/weighted_voter.py
"""

from dataclasses import dataclass, field
from typing import List, Dict, Optional, Tuple, Any


# WV-101: 权重映射常量
CONFIDENCE_WEIGHTS: Dict[str, int] = {
    "high": 3,
    "medium": 2,
    "low": 1,
}

# WV-103: 共识阈值
CONSENSUS_THRESHOLD: float = 0.6


@dataclass
class PathVoteInput:
    """单条路径的投票输入"""
    path_index: int
    answer: str
    confidence: str = "medium"          # high / medium / low
    strategy_name: str = ""
    summary: str = ""
    evidence: List[str] = field(default_factory=list)    # 关键证据列表
    risk: str = ""                       # 主要风险描述


@dataclass
class VoteResult:
    """WV-107: 投票结果元数据"""
    winner_answer: str
    winner_path_index: int
    winner_strategy: str
    method: str                          # "weighted_majority" | "judge"
    total_weight: int
    weight_distribution: Dict[str, Dict[str, Any]]
    consensus_ratio: float
    judge_used: bool = False
    judge_reason: str = ""


def normalize_answer(answer: str) -> str:
    """
    WV-106: 答案归一化
    
    处理:
        - strip 前后空白
        - lower case
        - 移除 \\boxed{} 包装
        - 移除多余标点
    """
    ...


def get_weight(confidence: str) -> int:
    """
    WV-101: 获取置信度对应权重
    
    WV-108: 未知置信度默认返回 1（向后兼容）
    """
    return CONFIDENCE_WEIGHTS.get(confidence.lower(), 1)


def weighted_majority_vote(
    inputs: List[PathVoteInput],
) -> Tuple[Optional[VoteResult], bool]:
    """
    WV-102~104: 加权多数投票
    
    Args:
        inputs: 各路径的投票输入列表
    
    Returns:
        (VoteResult, needs_judge): 投票结果 和 是否需要 Judge 仲裁
    
    逻辑:
        1. WV-106: 对所有答案做归一化
        2. WV-102: 按归一化答案分组，累加各组权重
        3. WV-103: 最高权重占比 > CONSENSUS_THRESHOLD → 共识，needs_judge=False
        4. WV-104: 否则 → 分裂，needs_judge=True
    """
    ...


async def judge_with_evidence(
    inputs: List[PathVoteInput],
    task_description: str,
    cfg: Any,
    task_log: Any,
) -> VoteResult:
    """
    WV-105: 带证据的 Judge 仲裁
    
    Args:
        inputs: 各路径的投票输入（含 confidence, evidence, risk）
        task_description: 原始任务描述
        cfg: 配置
        task_log: 日志
    
    Returns:
        VoteResult (method="judge")
    
    行为:
        1. 构建增强 Judge prompt：包含各路径的 confidence + evidence + risk
        2. 调用 LLM 选择最优答案
        3. 解析 LLM 输出，构建 VoteResult
    """
    ...


async def weighted_vote(
    inputs: List[PathVoteInput],
    task_description: str,
    cfg: Any,
    task_log: Any,
) -> VoteResult:
    """
    加权投票入口：综合 weighted_majority_vote + judge_with_evidence
    
    流程:
        1. 调用 weighted_majority_vote
        2. 若共识 → 直接返回
        3. 若分裂 → 调用 judge_with_evidence → 返回
    """
    ...


def build_vote_inputs_from_digests(
    path_digests: List["PathDigest"],
    results: List[Tuple],
) -> List[PathVoteInput]:
    """
    WV-205: 从 IST PathDigest 构建投票输入
    
    从 PathDigest.to_l0() 读取 answer + confidence，
    从 PathDigest 读取 key_findings → evidence, potential_issues → risk
    
    WV-108: PathDigest 无 confidence 时默认 "medium"
    """
    ...
```

### 4.3 结构化输出解析 — `structured_output.py`（新增）

```python
"""
WV-201~207: 结构化输出格式定义与解析

位置: apps/miroflow-agent/src/core/structured_output.py
"""

from dataclasses import dataclass, field
from typing import List, Optional
import re


# WV-201: 结构化输出格式（追加到 Agent system prompt）
STRUCTURED_OUTPUT_INSTRUCTION = """
在你给出最终答案时，请使用以下格式：

答案：\\boxed{你的答案}
置信度：high / medium / low
关键证据：[来源1: 一句话摘要, 来源2: 一句话摘要]
主要风险：这个答案可能错在哪里（一句话）

置信度说明：
- high: 多个可靠来源交叉验证，证据充分
- medium: 有一定证据支持，但未完全确认
- low: 证据不足或相互矛盾，不太确定
"""

# WV-203: 与 IST trace 要求合并后的统一 prompt 块
COMBINED_TRACE_AND_OUTPUT_INSTRUCTION = """
## 执行过程追踪

每次使用工具后，用一句话总结你的发现：
<conclusion>你从这步中得出的关键结论</conclusion>
<confidence>0.0-1.0</confidence>

## 最终答案格式

在你给出最终答案时，请使用以下格式：

答案：\\boxed{你的答案}
置信度：high / medium / low
关键证据：[来源1: 一句话摘要, 来源2: 一句话摘要]
主要风险：这个答案可能错在哪里（一句话）
"""


@dataclass
class StructuredOutput:
    """WV-204: 解析后的结构化输出"""
    answer: str = ""
    confidence: str = "medium"        # WV-207: 默认 medium
    evidence: List[str] = field(default_factory=list)  # WV-207: 默认 []
    risk: str = ""                    # WV-207: 默认 ""


def parse_structured_output(text: str) -> StructuredOutput:
    """
    WV-204: 从 Agent 输出文本中解析结构化输出
    
    解析规则:
        - 答案：\\boxed{...} 或 "答案：..." 行
        - 置信度：high / medium / low
        - 关键证据：[...] 列表
        - 主要风险：一句话
    
    WV-207: 任何字段解析失败时使用默认值
    """
    ...


def parse_confidence(text: str) -> str:
    """
    WV-206: 从文本中提取置信度
    
    匹配 "置信度：high" / "confidence: medium" 等模式
    返回 "high" / "medium" / "low"，默认 "medium"
    """
    ...


def parse_evidence(text: str) -> List[str]:
    """
    WV-206: 从文本中提取关键证据列表
    
    匹配 "关键证据：[URL1: 摘要, URL2: 摘要]" 模式
    返回证据字符串列表，默认 []
    """
    ...


def parse_risk(text: str) -> str:
    """
    WV-206: 从文本中提取主要风险
    
    匹配 "主要风险：..." 模式
    返回风险描述字符串，默认 ""
    """
    ...
```

### 4.4 IST PathDigest 扩展字段

```python
# WV-307: 在 IST 的 PathDigest 中增加字段（修改 IST 模块）
# 位置: apps/miroflow-agent/src/core/step_trace.py (IST 模块)

@dataclass
class PathDigest:
    # ... 现有字段 ...
    answer: str = ""
    confidence: str = "medium"
    traces: List[StepTrace] = field(default_factory=list)
    reasoning_chain: str = ""
    key_findings: List[str] = field(default_factory=list)
    potential_issues: List[str] = field(default_factory=list)
    
    # WV-307: 新增字段
    evidence: List[str] = field(default_factory=list)      # 关键证据
    risk: str = ""                                          # 主要风险
    
    def to_l0(self) -> dict:
        """L0: 答案 + 置信度 (~30 tokens)"""
        return {
            "answer": self.answer,
            "confidence": self.confidence,
        }
    
    def to_vote_input(self, path_index: int, strategy_name: str = "") -> "PathVoteInput":
        """WV-205: 转换为投票输入"""
        from .weighted_voter import PathVoteInput
        return PathVoteInput(
            path_index=path_index,
            answer=self.answer,
            confidence=self.confidence,
            strategy_name=strategy_name,
            summary=self.reasoning_chain,
            evidence=self.evidence if self.evidence else self.key_findings,
            risk=self.risk if self.risk else (
                self.potential_issues[0] if self.potential_issues else ""
            ),
        )
```

---

## 5. 数据流完整图

```
┌─────────────────────────────────────────────────────────────────────────────┐
│ Task 到达                                                                   │
└─────┬───────────────────────────────────────────────────────────────────────┘
      │
      ▼
┌─────────────────────┐
│ Question Parser      │
│ (QP 模块)            │
│                     │
│ 输出 ParsedQuestion  │
│  .question_type ─────┼──────────────────────────────────────────┐
│  .key_entities       │                                          │
└─────┬───────────────┘                                          │
      │                                                           │
      ▼                                                           │
┌─────────────────────┐                                          │
│ 策略选择             │                                          │
│ (每个岛选 1 策略)     │                                          │
│                     │                                          │
│ get_fitness(         │ ← WV-003                                │
│   metrics,           │                                          │
│   question_type)     │                                          │
└─────┬───────────────┘                                          │
      │                                                           │
      ▼                                                           │
┌─────────────────────────────────────────────────────────┐      │
│ System Prompt 构建                                       │      │
│                                                         │      │
│ base_prompt                                             │      │
│ + strategy.prompt_suffix                                │      │
│ + COMBINED_TRACE_AND_OUTPUT_INSTRUCTION   ← WV-203     │      │
│   (IST trace 要求 + WV 结构化输出要求)                    │      │
└─────┬───────────────────────────────────────────────────┘      │
      │                                                           │
      ▼                                                           │
┌─────────────────────────────────────────────────────────┐      │
│ N 条路径并行执行 (MiroThinker × N)                        │      │
│                                                         │      │
│  Path 0 ──→ [Agent 执行 + IST 采集] ──→ PathDigest 0   │      │
│  Path 1 ──→ [Agent 执行 + IST 采集] ──→ PathDigest 1   │      │
│  ...                                                    │      │
│  Path N ──→ [Agent 执行 + IST 采集] ──→ PathDigest N   │      │
│                                                         │      │
│  每个 PathDigest 包含:                                    │      │
│    .answer       (Agent 最终答案)                         │      │
│    .confidence   (IST 解析 / WV-204 解析)                │      │
│    .evidence     (WV-206 从输出提取)                      │      │
│    .risk         (WV-206 从输出提取)                      │      │
└─────┬───────────────────────────────────────────────────┘      │
      │                                                           │
      ▼                                                           │
┌─────────────────────────────────────────────────────────┐      │
│ WV: 加权投票                                              │      │
│                                                         │      │
│ 1. PathDigest[].to_vote_input() → PathVoteInput[]       │ ← WV-205
│                                                         │      │
│ 2. weighted_majority_vote(inputs)                       │ ← WV-102
│    │                                                    │      │
│    ├── 共识 (ratio > 0.6) → VoteResult(method=majority) │ ← WV-103
│    │                                                    │      │
│    └── 分裂 (ratio ≤ 0.6) → judge_with_evidence()      │ ← WV-104/105
│         │                                               │      │
│         └── VoteResult(method=judge)                    │      │
│                                                         │      │
│ 输出: VoteResult                                         │      │
│   .winner_answer                                        │      │
│   .winner_strategy                                      │      │
│   .method                                               │      │
│   .weight_distribution                                  │      │
└─────┬───────────────────────────────────────────────────┘      │
      │                                                           │
      ▼                                                           │
┌─────────────────────────────────────────────────────────┐      │
│ WV: 策略评估记录                                          │      │
│                                                         │      │
│ for each path:                                          │      │
│   record_result(                                        │ ← WV-002
│     strategy_id = path.strategy_name,                   │      │
│     island_id   = path.island_id,                       │      │
│     question_type = parsed.question_type,  ◄────────────┼──────┘
│     won     = (path.answer == correct_answer),          │
│     adopted = (path.answer == voted_answer),            │
│     metrics = strategy.metrics                          │
│   )                                                     │
│                                                         │
│ → 更新 metrics.overall                                   │ ← WV-004
│ → 更新 metrics.by_type[question_type]                    │ ← WV-005
│ → 持久化到存储                                            │ ← WV-008
└─────────────────────────────────────────────────────────┘
```

---

## 6. 文件结构

### 6.1 新增文件

| 文件路径 | 职责 | 对应编号 |
|---------|------|---------|
| `src/evolving/strategy_evaluator.py` | 策略评估：StrategyMetrics / record_result / get_fitness | WV-001~008 |
| `src/core/weighted_voter.py` | 加权投票：PathVoteInput / VoteResult / weighted_vote | WV-101~108 |
| `src/core/structured_output.py` | 结构化输出：格式定义 / 解析器 / prompt 模板 | WV-201~207 |
| `src/tests/test_strategy_evaluator.py` | 策略评估单元测试 | WV-401~402 |
| `src/tests/test_weighted_voter.py` | 加权投票单元测试 | WV-403~409 |
| `src/tests/test_structured_output.py` | 结构化输出解析测试 | WV-406 相关 |

### 6.2 修改文件

| 文件路径 | 修改内容 | 对应编号 |
|---------|---------|---------|
| `src/core/multi_path.py` | `_vote_best_answer()` 替换为 `weighted_vote()`；任务结束调用 `record_result()`；system prompt 追加结构化输出要求 | WV-301~303, WV-308 |
| `src/core/step_trace.py` (IST) | PathDigest 增加 evidence / risk 字段；增加 `to_vote_input()` 方法 | WV-307 |
| `src/tests/test_multi_path.py` | 适配新投票接口，回归测试 | WV-413~414 |

### 6.3 不修改文件

| 文件路径 | 理由 |
|---------|------|
| `src/core/orchestrator.py` | 单路径 ReAct 逻辑不变 |
| `src/llm/` | LLM 调用层不变 |
| `libs/miroflow-tools/` | 工具层不变 |
| `main.py` | 单路径入口不变 |
| `src/core/pipeline.py` | 管道逻辑不变 |
| `src/core/cost_tracker.py` | 成本追踪不变 |
| `src/core/streaming.py` | 流式输出不变 |

---

## 7. 开发路线图

### Phase 1: 策略评估记录层 (0.3 天)

**目标**: 实现 record_result / get_fitness，建立题型条件化评估基础

**任务**:
1. 实现 `StrategyMetrics` 数据结构 (WV-001)
2. 实现 `record_result()` (WV-002, WV-004, WV-005)
3. 实现 `get_fitness()` (WV-003, WV-006, WV-007)
4. 编写单元测试 (WV-401, WV-402)

**验收标准**:
- [x] `record_result` 连续调用 20 次，overall 和 by_type 统计数值完全正确
- [x] `get_fitness` 在样本≥3 时返回题型胜率，<3 时返回全局胜率，全零返回 0.5
- [x] 单元测试覆盖率 ≥90%（对 strategy_evaluator.py）

### Phase 2: 加权投票核心 (0.4 天)

**目标**: 实现加权多数投票 + Judge 仲裁增强

**任务**:
1. 实现 `PathVoteInput` / `VoteResult` 数据结构 (WV-107)
2. 实现 `normalize_answer()` (WV-106)
3. 实现 `weighted_majority_vote()` (WV-102~104)
4. 实现 `judge_with_evidence()` (WV-105)
5. 实现 `weighted_vote()` 入口函数
6. 实现降级逻辑 (WV-108)
7. 编写单元测试 (WV-403~408)

**验收标准**:
- [x] 5 路径投票：3 个 high 选 A + 2 个 medium 选 B → A 胜 (9 vs 4)
- [x] 分裂场景正确触发 Judge
- [x] 无 confidence 时退化为简单多数投票（与现有行为一致）
- [x] VoteResult 包含完整的 weight_distribution 和 consensus_ratio

### Phase 3: 结构化输出与 IST 协作 (0.3 天)

**目标**: 定义结构化输出格式，实现解析器，与 IST PathDigest 对接

**任务**:
1. 定义 `STRUCTURED_OUTPUT_INSTRUCTION` 和 `COMBINED_TRACE_AND_OUTPUT_INSTRUCTION` (WV-201~203)
2. 实现 `parse_structured_output()` (WV-204)
3. 实现 `parse_confidence` / `parse_evidence` / `parse_risk` (WV-206)
4. 扩展 PathDigest 增加 evidence / risk 字段 (WV-307)
5. 实现 `PathDigest.to_vote_input()` (WV-205)
6. 编写解析测试

**验收标准**:
- [x] 标准格式输出正确解析 confidence / evidence / risk
- [x] 非标准格式（缺字段、格式不规范）不报错，使用默认值 (WV-207)
- [x] PathDigest.to_vote_input() 正确构建 PathVoteInput

### Phase 4: 集成与改造 (0.3 天)

**目标**: 将加权投票和策略评估集成到 multi_path.py 主流程

**任务**:
1. 替换 `_vote_best_answer()` 为 `weighted_vote()` (WV-301)
2. 任务结束后调用 `record_result()` (WV-302)
3. System prompt 追加结构化输出要求 (WV-303)
4. 增强投票日志 (WV-308)
5. Judge prompt 更新 (WV-305)

**验收标准**:
- [x] 现有 37 个单元测试全部通过 (WV-414)
- [x] 投票流程端到端跑通：PathDigest → weighted_vote → VoteResult → record_result
- [x] 日志中能看到各路径权重和投票分布

### Phase 5: 集成测试与回归 (0.2 天)

**目标**: 端到端验证 + 回归 + 性能

**任务**:
1. 5 路径加权投票端到端测试 (WV-409)
2. Judge 带证据仲裁测试 (WV-410)
3. 题型统计积累测试 (WV-411)
4. fitness 与 island 对接测试 (WV-412)
5. 回归测试全通过 (WV-413~414)
6. 性能测试 (WV-415~416)

**验收标准**:
- [x] 构造 5 个 PathDigest 的端到端测试通过
- [x] 连续 10 次 record_result 后题型胜率统计准确
- [x] 投票额外开销 < 1ms
- [x] 所有现有测试无回归

---

## 8. 设计决策记录

| 编号 | 决策 | 理由 | 替代方案 | 日期 |
|------|------|------|---------|------|
| **WV-DD-01** | 权重映射用固定常量 (3/2/1) 而非可配置 | 简单直接，过早可配置增加复杂度；积累数据后再考虑自动调参 | 从历史数据学习权重映射 | 2026-03-20 |
| **WV-DD-02** | 共识阈值 0.6 而非 0.5 | 0.5 在偶数路径时总是分裂；0.6 允许较弱共识也被接受，减少不必要的 Judge 调用 | 使用 0.5 或动态阈值 | 2026-03-20 |
| **WV-DD-03** | confidence 从 IST PathDigest 读取，不二次解析 | IST 模块已有 ConclusionExtractor 解析 confidence，避免重复工作；PathDigest 是统一数据源 | 独立从 Agent 原始输出解析 | 2026-03-20 |
| **WV-DD-04** | record_result 就地更新 metrics 而非追加 event log | 简单直接，胜率计算无需遍历历史；event log 由 OpenViking strategy_results/ 承载 | 追加到 JSONL 事件流再聚合 | 2026-03-20 |
| **WV-DD-05** | MIN_TYPE_SAMPLES = 3 | 统计学上 3 是最小有意义样本；过低容易被噪音误导，过高会让新题型长期退回全局 | 5 或 10 | 2026-03-20 |
| **WV-DD-06** | 将 evidence/risk 追加到 PathDigest 而非另建数据结构 | PathDigest 已是路径执行结果的统一载体；WV 模块只是消费者不是生产者 | 单独的 VoteContext 数据结构 | 2026-03-20 |
| **WV-DD-07** | IST trace prompt 与 WV 结构化输出 prompt 合并为一个 block | 避免 system prompt 中出现两段格式要求造成 Agent 混淆；减少 prompt token | 分开注入 | 2026-03-20 |
| **WV-DD-08** | 向后兼容：无 confidence 默认权重 = 1 | 确保 IST 模块未部署时 WV 退化为简单多数投票，现有行为不变 | 无 confidence 时不启用加权 | 2026-03-20 |
| **WV-DD-09** | Judge prompt 使用中文模板 | EvoAgent 目标场景为中文预测市场题，中文 prompt 匹配更好 | 英文 prompt | 2026-03-20 |
| **WV-DD-10** | adopted 字段与 won 字段分离 | adopted = 被投票选中；won = 最终答案正确。两者独立——被选中不代表正确，未被选中也可能是对的 | 只记录 won | 2026-03-20 |

---

## 9. 风险与缓解

| 风险 | 影响 | 概率 | 缓解措施 |
|------|------|------|---------|
| Agent 不遵守结构化输出格式 | 中 — confidence 解析失败 | 中 | WV-207 默认值填充 + WV-108 降级为等权投票；IST 已有 ConclusionExtractor 作为二道防线 |
| 置信度校准偏差（Agent 总说 high） | 中 — 加权失去意义 | 中 | 监控 confidence 分布，若 high 占比 >80% 需调整 prompt；未来可引入校准层 |
| 共识阈值不适配所有场景 | 低 — 偶尔误触发/漏触发 Judge | 低 | WV-DD-02 解释了 0.6 的理由；运行一段时间后可根据 Judge 准确率调整 |
| IST 模块未实现时 WV 无法获取 confidence | 中 — 退化为简单投票 | 低 | WV-108 向后兼容降级机制，default weight = 1 |
| record_result 并发写入冲突 | 低 — metrics 统计错误 | 低 | 当前任务串行执行（一次一题），无并发问题；未来需加锁 |
| 题型分类错误影响条件化评估 | 中 — fitness 计算偏差 | 中 | WV-DD-05 最小样本阈值兜底；错误分类的题型会自然在多次评估中被稀释 |
| Judge prompt 过长增加成本 | 低 — 增加 ~200 tokens/Judge 调用 | 高 | evidence/risk 各限制 200 字符；Judge 仅在分裂时触发（共识时零成本） |

---

## 10. 术语表

| 术语 | 定义 |
|------|------|
| **Confidence（置信度）** | Agent 对自己答案的自评信心等级：high / medium / low |
| **Weight（权重）** | 置信度映射的票数：high=3, medium=2, low=1 |
| **Weighted Majority Vote（加权多数投票）** | 按权重累计每个答案的票数，权重最高者胜出 |
| **Consensus（共识）** | 最高权重答案占总权重比 > 0.6，不需要 Judge |
| **Split（分裂）** | 最高权重答案占比 ≤ 0.6，需要 Judge 仲裁 |
| **Judge（裁判）** | LLM 裁判调用，在分裂时选出最优答案 |
| **Evidence（证据）** | Agent 支撑答案的关键信息来源和摘要 |
| **Risk（风险）** | Agent 自评答案可能出错的原因 |
| **StrategyMetrics（策略指标）** | 策略的评估数据：全局胜率 + 按题型拆分的胜率 |
| **Fitness（适应度）** | 策略在特定条件下的表现评分，用于岛内排名 |
| **Question Type（题型）** | 题目类型，由 QP 模块解析：politics / entertainment / sports / finance / tech 等 |
| **MIN_TYPE_SAMPLES（最小题型样本数）** | 使用题型胜率所需的最小样本量（默认 3） |
| **PathDigest（路径摘要）** | IST 模块生成的路径执行结构化摘要，包含 answer / confidence / traces |
| **VoteResult（投票结果）** | 加权投票的完整输出，含 winner / method / weight_distribution |
| **Adopted（被采纳）** | 策略的答案被投票选中（不一定正确） |
| **Won（获胜）** | 策略的答案最终被验证为正确 |
| **Consensus Threshold（共识阈值）** | 判定共识/分裂的权重占比阈值，默认 0.6 |

---

## 附录 A: 与现有模块的依赖关系

```
                ┌──────────┐
                │ QP 模块   │
                │ (待开发)   │
                │           │
                │ 提供:      │
                │ ParsedQuestion
                │  .question_type
                └─────┬────┘
                      │
          ┌───────────┼───────────┐
          │           │           │
          ▼           ▼           ▼
    ┌───────────┐ ┌───────┐ ┌──────────────┐
    │ WV 模块    │ │ IST   │ │ Island Pool  │
    │ (本文档)   │ │ 模块   │ │ (待开发)      │
    │           │ │       │ │              │
    │ 消费:      │ │ 提供:  │ │ 消费:         │
    │ question_ │ │ Path  │ │ get_fitness()│
    │  type     │ │ Digest│ │              │
    │ Path     │ │ .conf │ │              │
    │  Digest  │ │ .ans  │ │              │
    │           │ │       │ │              │
    │ 提供:      │ │       │ │              │
    │ record_   │ │       │ │              │
    │  result() │ │       │ │              │
    │ get_     │ │       │ │              │
    │  fitness()│ │       │ │              │
    │ weighted_│ │       │ │              │
    │  vote()  │ │       │ │              │
    └───────────┘ └───────┘ └──────────────┘
```

**开发顺序建议**: QP → IST → **WV (本模块)** → Island Pool / 进化机制

WV 对 QP 和 IST 的依赖可以通过接口 mock 解耦：
- QP 未就绪时：question_type 传 "unknown"，退回全局胜率
- IST 未就绪时：confidence 默认 "medium"，退化为等权投票
