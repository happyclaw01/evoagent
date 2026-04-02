# EvoAgent 设计文档 V2（合并版）

> **项目代号**: EvoAgent  
> **基线项目**: MiroThinker v1.0  
> **核心理念**: 将进化搜索方法论应用于 Research Agent，通过多路径探索和策略进化超越单链路 ReAct 循环  
> **核心参考**: SkyDiscover（AdaEvolve + EvoX 双层进化框架），谢一凡硕士论文 (SJTU, 2025)，Self-Improving Agent (ClawHub)  
> **创建日期**: 2026-03-29  
> **合并来源**: `EVOAGENT_DESIGN.md` (V1 总设计) + `STRATEGY_EVOLVE_MASTER.md` (策略进化总纲)

---

## 一句话总结

**5 个专家视角岛，每次任务由 Question Parser 解析题型，所有岛各出 1 条路径并行执行（带 IST 留痕），加权投票选最优答案，每轮结束后全岛进化（refine + diverge），题型全岛不擅长时动态开新岛。**

---

## 1. 架构总览

```
┌──────────────────────────────────────────────────────────────────────────────┐
│                          EvoAgent Controller (EA-CTL)                        │
│                                                                              │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐      │
│  │ QP       │  │ SI       │  │ WV       │  │ IST      │  │ EE       │      │
│  │ 题目解析  │  │ 策略岛池  │  │ 加权投票  │  │ 步骤留痕  │  │ 进化引擎  │      │
│  └──────────┘  └──────────┘  └──────────┘  └──────────┘  └──────────┘      │
└───────────────────────────────┬───────────────────────────────────────────────┘
                                │
          ┌─────────────────────┼─────────────────────┐
          │                     │                     │
    ┌─────▼─────┐        ┌─────▼─────┐        ┌─────▼─────┐
    │  Island 0  │        │  Island 1  │        │  Island N  │
    │  信息追踪   │        │  机制分析   │        │  (动态)    │
    │  + IST 留痕 │        │  + IST 留痕 │        │  + IST 留痕 │
    └─────┬─────┘        └─────┬─────┘        └─────┬─────┘
          │                     │                     │
          └─────────────────────┼─────────────────────┘
                                │
                     ┌──────────▼──────────┐
                     │  WV 加权投票 → 答案   │
                     └──────────┬──────────┘
                                │
                     ┌──────────▼──────────┐
                     │  EE 进化引擎         │
                     │  refine + diverge    │
                     │  迁移 + 动态开岛      │
                     └─────────────────────┘
```

---

## 2. 三层架构 + 基础设施

| 层 | 名称 | 核心问题 | V1 编号 | V2 改动 |
|----|------|---------|---------|---------|
| **第一层** | 运行时多路径探索 | 对同一任务怎么跑多条路径 | EA-001~012 | ＋QP 解析, ＋SI 采样, ＋WV 投票, ＋IST 留痕 |
| **第二层** | 跨任务策略进化 | 历史数据怎么改善策略选择 | EA-101~108 | 改为岛池结构 (SI), 题型条件化评估 (WV) |
| **第三层** | 元进化 | 怎么产生全新策略和视角 | EA-201~203 | 改为 EE 统一引擎 (refine/diverge/迁移/开岛) |
| **基础设施** | 工具与存储 | 底层支撑 | EA-301~307 | ＋IST DigestStore |

---

## 3. 第一层：运行时多路径探索（Runtime）

> 一次任务从输入到输出的完整流程。V1 的 EA-001~012 保留，新增 QP/SI/WV/IST 改造运行时行为。

### 3.1 数据流

```
Task 到达
    │
    ▼  ① QP: 解析题目 → ParsedQuestion
    │
    ▼  ② SI: 所有岛各选 1 策略 → [StrategyDefinition × N]
    │
    ▼  ③ QP: 编译策略 → [CompiledStrategy × N] (8维 → prompt_suffix)
    │
    ▼  ④ N 路径并行执行 (MiroThinker + prompt_suffix + IST 留痕)
    │      ├── Path 0 (Island 0 策略)
    │      ├── Path 1 (Island 1 策略)
    │      └── Path N (Island N 策略)
    │
    ▼  ⑤ IST: 每路径 finalize → L0/L1/L2 digest
    │
    ▼  ⑥ WV: 加权投票 (读 L0: 答案+confidence; 分裂时 Judge 读 L1)
    │
    ▼  ⑦ 输出最终答案
    │
    ▼  ⑧ WV: 记录战绩 → strategy_results/{task_id}.json
    │
    ▼  ⑨ IST: digest 持久化 → DigestStore
```

### 3.2 功能清单

#### 3.2.1 多路径调度（保留自 V1）

| 编号 | 功能名称 | 描述 | 状态 |
|------|---------|------|------|
| **EA-001** | 多路径调度器 | 对同一任务启动 N 条并行 Agent 路径 | ✅ 已实现 |
| **EA-005** | 独立工具管理器 | 每条路径拥有独立 ToolManager 实例 | ✅ 已实现 |
| **EA-006** | 路径级日志隔离 | 每条路径生成独立 TaskLog | ✅ 已实现 |
| **EA-007** | 主控日志聚合 | 汇总所有路径结果、投票过程到 master log | ✅ 已实现 |
| **EA-008** | 路径数动态配置 | 通过环境变量 `NUM_PATHS` 控制并行路径数 | ✅ 已实现 |
| **EA-009** | 早停机制 | 前 K 条路径达成共识时取消剩余路径 | ✅ 已实现 |
| **EA-010** | 路径预算分配 | 不同策略分配不同 max_turns | ✅ 已实现 |
| **EA-011** | 异步流式输出 | 各路径中间过程实时流式输出 | ✅ 已实现 |
| **EA-012** | 路径失败重试 | API 错误时自动用备选策略重启 | ✅ 已实现 |

#### 3.2.2 QP — Question Parser + 策略编译器（V2 新增，替代 V1 静态策略分配）

| 编号 | 功能名称 | 描述 | 状态 | 优先级 |
|------|---------|------|------|--------|
| **SE-001** | 题目解析器 | LLM 单次调用解析题型/实体/时间窗/criteria | ✅ 完成 | P0 |
| **SE-002** | ParsedQuestion 数据结构 | question_type, key_entities, time_window, resolution_criteria, difficulty_hint | ✅ 完成 | P0 |
| **SE-003** | 8 维策略定义 | StrategyDefinition: Hi/Qi/Ei/Ri/Ui/Ai/Ti + max_turns | ✅ 完成 | P0 |
| **SE-004** | 策略编译器 | 8 维 → prompt_suffix，TEMPLATES 映射 | ✅ 完成 | P0 |
| **SE-005** | 策略距离度量 | 维度差异数 / 7，归一化 0-1 | ✅ 完成 | P1 |
| **SE-006** | 5 个种子策略 | 信息追踪/机制分析/历史类比/市场信号/对抗验证 | ✅ 完成 | P0 |

#### 3.2.3 WV — Weighted Voting（V2 新增，替代 V1 的 EA-003/004 简单投票）

| 编号 | 功能名称 | 描述 | 状态 | 优先级 |
|------|---------|------|------|--------|
| **SE-030** | 结构化输出规范 | 答案 + confidence(high/medium/low) + 关键证据 + 风险 | ✅ 完成 | P0 |
| **SE-031** | 加权投票机制 | high=3票, medium=2票, low=1票；一致直接采用，分裂 Judge | ✅ 完成 | P0 |
| **SE-032** | 题型条件化战绩记录 | 按 question_type 拆分 wins/total/rate | ✅ 完成 | P0 |
| **SE-033** | Fitness 条件化计算 | 有题型数据(≥3样本)用题型胜率，否则退回全局 | ✅ 完成 | P1 |

#### 3.2.4 IST — Inline Step Trace（V2 新增）

| 编号 | 功能名称 | 描述 | 状态 | 优先级 |
|------|---------|------|------|--------|
| **SE-040** | TracingToolWrapper | 工具调用自动提取 key_info (~80 chars) | ✅ 已完成 | P0 |
| **SE-041** | StepTraceCollector | 收集每步 trace，路径结束后 finalize | ✅ 已完成 | P0 |
| **SE-042** | ConclusionExtractor | 解析 `<conclusion>` 标签提取结论 | ✅ 已完成 | P0 |
| **SE-043** | L0/L1/L2 分层摘要 | L0 ~30tok, L1 ~300tok, L2 ~5k-15k tok | ✅ 已完成 | P0 |
| **SE-044** | DigestStore | 本地 JSON / OpenViking 持久化 | ✅ 已完成 | P0 |

### 3.3 V1 → V2 替代关系

| V1 编号 | V1 功能 | V2 替代 | 说明 |
|---------|---------|---------|------|
| EA-002 | 策略变体定义 (3 个硬编码) | SE-003 + SE-006 | 改为 8 维结构化定义 + 5 个种子策略 |
| EA-003 | LLM 投票评选 | SE-031 | 改为加权投票，分裂时才用 Judge |
| EA-004 | 多数投票快速路径 | SE-031 | 统一到加权投票机制中 |

---

## 4. 第二层：跨任务策略进化（Cross-task）

> 每次任务结束积累数据，跨任务改善策略选择。V1 的 EA-101~108 被重新设计为 **岛池结构 (SI)** + **题型条件化评估 (WV)**。

### 4.1 核心改动

| V1 设计 | V2 设计 | 改动原因 |
|---------|---------|---------|
| 扁平策略池 + 全局胜率 | 按专家视角分岛 + 题型条件化胜率 | 不同视角适合不同题型，全局胜率掩盖真实表现 |
| 策略画像引擎 (EA-102) | elite_score = fitness × w1 + novelty × w2 (SI) | 岛内多样性由数学保证，不靠手动画像 |
| 自适应策略选择 (EA-104) | 所有岛各选 1 策略 (SI 采样) | 5 视角全参与，最大化多样性 |
| 独立的战绩记录器 (EA-101) | 战绩记录由 WV 负责 | 投票结果天然产出战绩，减少跨模块调用 |
| 经验提取器 (EA-108) | IST L1 digest + EE 进化分析 | 留痕自动化，进化时读 digest 而非原始 log |

### 4.2 功能清单

#### 4.2.1 SI — Strategy Island（替代 V1 的 EA-104/107 策略池管理）

| 编号 | 功能名称 | 描述 | 状态 | 优先级 |
|------|---------|------|------|--------|
| **SE-010** | 单岛结构 | IslandConfig: perspective, max_size, elite_ratio, fitness/novelty_weight | ✅ 完成 | P0 |
| **SE-011** | 岛内策略池 | 策略存储、CRUD、持久化（JSON / OpenViking） | ✅ 完成 | P0 |
| **SE-012** | Elite Score 计算 | fitness_weight × fitness_percentile + novelty_weight × novelty_percentile | ✅ 完成 | P0 |
| **SE-013** | 确定性拥挤淘汰 | 岛满时：找最近似非精英，新策略 elite_score 更高则替换 | ✅ 完成 | P1 |
| **SE-014** | 岛内策略采样 | 根据 question_type 选该题型上胜率最优的策略 | ✅ 完成 | P0 |
| **SE-015** | 多岛管理器 IslandPool | 管理所有岛的生命周期，提供全局 API | ✅ 完成 | P0 |
| **SE-016** | OpenViking 存储集成 | L0/L1/L2 分层存储，无 Server 降级为本地 JSON | ✅ 完成 | P1 |
| **SE-017** | 初始 5 岛配置 | 信息追踪/机制分析/历史类比/市场信号/对抗验证 | ✅ 完成 | P0 |

#### 4.2.2 战绩记录与评估（由 WV 驱动，替代 V1 的 EA-101/102）

> 战绩记录集成在 SE-032 (WV 题型条件化战绩记录) 中，不再独立。
> 策略画像由 SE-012 (elite_score) 自动计算，不再需要独立的画像引擎。

#### 4.2.3 V1 → V2 替代关系

| V1 编号 | V1 功能 | V2 替代 | 说明 |
|---------|---------|---------|------|
| EA-101 | 策略战绩记录器 | SE-032 (WV) | 战绩随投票结果自动产出 |
| EA-102 | 策略画像引擎 | SE-012 (SI) | elite_score 自动聚合，无需独立画像 |
| EA-103 | 任务分类器 | SE-001 (QP) | 前置到 Question Parser 中 |
| EA-104 | 自适应策略选择 | SE-014 + SE-015 (SI) | 所有岛各选最优策略 |
| EA-105 | 策略参数微调 | SE-020 (EE refine) | 由进化引擎的 refine 操作完成 |
| EA-106 | 策略淘汰机制 | SE-013 (SI) | 由确定性拥挤淘汰替代 |
| EA-107 | 策略种群管理 | SE-011 + SE-015 (SI) | 岛池 = 种群管理 |
| EA-108 | 经验提取器 | SE-043 (IST L1) + SE-020/021 (EE) | IST 自动留痕 + 进化时分析 |

### 4.3 跨任务进化数据流

```
任务 1 结束 → WV 记录战绩 (SE-032)
任务 2 结束 → WV 记录战绩
...
任务 N 结束 → WV 记录战绩
    │
    ▼  积累到一轮结束（如 10 题）
    │
    ├── SI: 各岛策略的题型条件化胜率自动更新
    │       (SE-033: 有题型数据用题型胜率，否则退回全局)
    │
    ├── SI: elite_score 重算 (SE-012)
    │       = fitness_weight × fitness_percentile
    │       + novelty_weight × novelty_percentile
    │
    └── SI: 岛内淘汰检查 (SE-013)
            岛满时，新策略与最近似非精英比 elite_score
```

---

## 5. 第三层：元进化（Meta-evolution）

> 产生全新策略和全新视角。V1 的 EA-201~203 被重新设计为 **EE 统一进化引擎**。

### 5.1 核心改动

| V1 设计 | V2 设计 | 改动原因 |
|---------|---------|---------|
| EA-201 LLM 策略生成器（被动触发） | EE refine + diverge（每轮主动进化） | 数据量小，等停滞再进化太慢 |
| EA-202 策略代码进化 | 移除 | 8 维结构化定义已足够，代码进化复杂度过高 |
| EA-203 跨维度自适应 | EE 动态开岛 (SE-024/025) | 用新视角岛替代抽象的维度调整 |
| 触发条件分散 | 统一由轮次结束触发 | 每轮全岛进化，简化调度逻辑 |

### 5.2 功能清单

#### 5.2.1 EE — Evolution Engine（替代 V1 的 EA-201~203）

| 编号 | 功能名称 | 描述 | 状态 | 优先级 |
|------|---------|------|------|--------|
| **SE-020** | Refine 操作 | 拿岛内 top 策略，LLM 微调 1-2 维 | ✅ 完成 | P0 |
| **SE-021** | Diverge 操作 | 在岛视角内，LLM 设计全新变种（≥3 维不同） | ✅ 完成 | P0 |
| **SE-022** | 每轮全岛进化调度 | 一轮结束后，所有岛各 1 refine + 1 diverge = 2 新策略/岛 | ✅ 完成 | P0 |
| **SE-023** | 岛间环形迁移 | top 策略复制到下一岛，距离 < 0.3 不迁移 | ✅ 完成 | P1 |
| **SE-024** | 动态开岛检测 | 某题型全岛 best_rate < 0.4 且 samples ≥ 5 → 触发 | ✅ 完成 | P1 |
| **SE-025** | 动态开岛执行 | LLM 生成新视角 + 初始策略 → spawn 新岛 | ✅ 完成 | P1 |

#### 5.2.2 V1 → V2 替代关系

| V1 编号 | V1 功能 | V2 替代 | 说明 |
|---------|---------|---------|------|
| EA-201 | LLM 策略生成器 | SE-020 (refine) + SE-021 (diverge) | 拆分为微调和创新两种操作 |
| EA-202 | 策略代码进化 | **移除** | 8 维结构化已够用，代码进化过早优化 |
| EA-203 | 跨维度自适应 | SE-024 + SE-025 (动态开岛) | 新视角岛 = 新维度 |

### 5.3 进化调度流程

```
一轮（如 10 题）结束
    │
    ▼  ⑨ EE: 所有岛各自进化 (SE-022)
    │       │
    │       ├── 每岛: 1 × refine (SE-020)
    │       │     拿岛内 top 策略
    │       │     读 L1 digest 分析失败案例
    │       │     LLM 微调 1-2 维 → 新策略
    │       │
    │       └── 每岛: 1 × diverge (SE-021)
    │             在岛视角内
    │             LLM 设计全新变种（≥3 维不同）
    │             strategy_distance(新, 旧) ≥ 0.43
    │
    ▼  ⑩ EE: 岛间环形迁移 (SE-023)
    │       Island_0.top → Island_1
    │       Island_1.top → Island_2
    │       ...
    │       Island_N.top → Island_0
    │       距离 < 0.3 时不迁移（避免趋同）
    │
    ▼  ⑪ EE: 动态开岛检测 (SE-024)
    │       某题型全岛 best_rate < 0.4 且 samples ≥ 5
    │       → 触发
    │
    ▼  ⑫ EE: 动态开岛执行 (SE-025)
            LLM 生成新专家视角 + 初始策略
            → spawn 新岛，下轮自动参与
```

---

## 6. 基础设施

### 6.1 工具改造（保留自 V1）

| 编号 | 功能名称 | 描述 | 状态 |
|------|---------|------|------|
| **EA-301** | 本地 Python 沙箱 | 替代 E2B 云沙箱，本地 subprocess 执行 | ✅ 已实现 |
| **EA-302** | DuckDuckGo 搜索替代 | 替代 Serper API，免费搜索 | ✅ 已实现 |
| **EA-303** | OpenRouter LLM 配置 | 支持 OpenRouter 多模型路由 | ✅ 已实现 |
| **EA-304** | 成本追踪器 | 记录每条路径 token 消耗和 API 成本 | ✅ 已实现 |
| **EA-307** | OpenViking 集成 | 上下文存储层：分层加载 / 目录检索 / 跨路径共享 | ✅ 已实现 |

### 6.2 V1 变更说明

| V1 编号 | V1 功能 | V2 状态 | 说明 |
|---------|---------|---------|------|
| EA-305 | 路径间通信总线 | 通过 EA-307 实现 | 无变更 |
| EA-306 | 结果缓存层 | 通过 EA-307 实现 | 无变更 |

---

## 7. 测试与评估

| 编号 | 功能名称 | 描述 | 状态 |
|------|---------|------|------|
| **EA-401** | 单元测试 - 多路径调度 | 测试 N 条路径正确并发 | ✅ 已实现 |
| **EA-402** | 单元测试 - 投票机制 | 测试加权投票和 LLM Judge | ✅ 已实现 |
| **EA-403** | 单元测试 - 策略注入 | 测试策略正确注入 system prompt | ✅ 已实现 |
| **EA-404** | 集成测试 - 端到端 | 使用真实 API 运行完整流程 | ❌ 待开发 |
| **EA-405** | 基准对比测试 | GAIA/HLE 子集上对比正确率 | ❌ 待开发 |
| **EA-406** | 成本效益分析 | 不同路径数的正确率与成本比 | ❌ 待开发 |
| **EA-407** | 策略消融实验 | 每个策略变体的独立贡献 | ❌ 待开发 |
| **EA-408** | 持续预测引擎 | 多路径初始预测 + 滚动更新 | ✅ 已实现 |
| **EA-409** | 预测更新调度器 | 按时间间隔或突发事件触发更新 | ✅ 已实现 |
| **EA-410** | 预测验证与轨迹分析 | 对比预测 vs 实际，分析收敛/发散 | ✅ 已实现 |

---

## 8. 核心数据结构

### 8.1 ParsedQuestion（QP 输出 → SI, WV 消费）

```python
@dataclass
class ParsedQuestion:                          # DS-001
    question_type: str        # politics / entertainment / sports / finance / tech / science / other
    key_entities: List[str]
    time_window: str
    resolution_criteria: str
    difficulty_hint: str      # easy / medium / hard
```

### 8.2 StrategyDefinition（QP 定义 → SI 存储 → EE 进化）

```python
@dataclass
class StrategyDefinition:                      # DS-002
    id: str
    name: str
    island_id: str
    # 8 维
    hypothesis_framing: str    # Hi — 假设构建
    query_policy: str          # Qi — 查询策略
    evidence_source: str       # Ei — 证据来源
    retrieval_depth: str       # Ri — shallow / medium / deep
    update_policy: str         # Ui — fast / moderate / conservative
    audit_policy: str          # Ai — 审计策略
    termination_policy: str    # Ti — 终止策略
    max_turns: int
    # 元数据
    parent_id: Optional[str] = None
    iteration_found: int = 0
    # 题型条件化胜率
    metrics: Dict[str, Any] = field(default_factory=lambda: {
        "overall": {"wins": 0, "total": 0, "rate": 0.0},
        "by_type": {},  # {"politics": {"wins": 5, "total": 8, "rate": 0.625}}
    })
```

### 8.3 CompiledStrategy（QP 编译器输出 → 路径执行消费）

```python
@dataclass
class CompiledStrategy:                        # DS-003
    name: str
    max_turns: int
    prompt_suffix: str
    _strategy_def: StrategyDefinition
```

### 8.4 PathDigest（IST 输出 → WV, EE 消费）

```python
@dataclass
class PathSummary:                             # DS-004a (L0)
    answer: str
    confidence: str            # high / medium / low
    token_cost: int

@dataclass
class PathDigest:                              # DS-004b (L1)
    summary: PathSummary
    reasoning_chain: str
    key_findings: List[str]
    potential_issues: List[str]
    step_traces: List[StepTrace]
```

### 8.5 StrategyResult（WV 输出 → SI, EE 消费）

```python
@dataclass
class StrategyResult:                          # DS-005
    task_id: str
    island_id: str
    strategy_id: str
    question_type: str
    won: bool
    adopted: bool
    confidence: str
    timestamp: str
```

---

## 9. 策略定义规范

### 9.1 V2 策略定义（8 维结构化）

替代 V1 的 4 维 `{name, description, prompt_suffix, max_turns}` 格式。

| 维度 | 缩写 | 含义 | 可选值示例 |
|------|------|------|-----------|
| 假设构建 | Hi | 如何形成初始假设 | 信息追踪 / 机制分析 / 历史类比 |
| 查询策略 | Qi | 如何构造搜索查询 | 多源广搜 / 精确关键词 / 侧面迂回 |
| 证据来源 | Ei | 优先检索哪些来源 | 新闻 / 学术 / 社交 / 官方 |
| 检索深度 | Ri | 深度 vs 广度 | shallow / medium / deep |
| 更新策略 | Ui | 新信息如何修正假设 | fast / moderate / conservative |
| 审计策略 | Ai | 如何验证结论 | 交叉验证 / 对抗检验 / 专家背书 |
| 终止策略 | Ti | 何时停止搜索 | 首个可靠源 / 三源交叉 / 穷尽时限 |
| 最大轮次 | max_turns | 搜索轮数上限 | 50~300 |

### 9.2 5 个种子策略（V2 初始岛配置）

| 岛 ID | 视角名称 | 核心思路 | 对应 V1 |
|--------|---------|---------|---------|
| Island 0 | 信息追踪 | 追踪官方声明和权威新闻源 | ≈ STR-01 breadth_first |
| Island 1 | 机制分析 | 分析底层因果机制和政策逻辑 | ≈ STR-02 depth_first |
| Island 2 | 历史类比 | 用历史先例推断未来走向 | ≈ STR-03 lateral_thinking |
| Island 3 | 市场信号 | 从市场数据和博彩赔率反推 | 新增 |
| Island 4 | 对抗验证 | 故意从反面论证，寻找漏洞 | ≈ STR-04 verification_heavy |

### 9.3 策略生命周期（V2 改动）

V1 的 `active → probation → retired` 三态改为 **确定性拥挤淘汰**：

```
新策略加入岛
    │
    ├── 岛未满 → 直接加入
    │
    └── 岛已满 → 确定性拥挤淘汰 (SE-013)
            找到最近似的非精英策略（strategy_distance 最小）
            比较 elite_score
            ├── 新策略 elite_score 更高 → 替换
            └── 新策略 elite_score 更低 → 丢弃
```

---

## 10. 跨模块接口汇总

| 接口 | 生产者 | 消费者 | 数据 | 传递方式 |
|------|--------|--------|------|---------|
| 题目解析 | QP | SI, WV | `ParsedQuestion` (DS-001) | 函数返回值 |
| 策略采样 | SI | QP (编译) | `StrategyDefinition` (DS-002) | 函数返回值 |
| 策略编译 | QP | 路径执行 | `CompiledStrategy` (DS-003) | 函数返回值 |
| 步骤留痕 | IST | WV, EE | `PathSummary` / `PathDigest` (DS-004) | DigestStore |
| 战绩记录 | WV | SI, EE | `StrategyResult` (DS-005) | 文件存储 (JSONL) |
| 进化请求 | EE | SI | 新 `StrategyDefinition` | 函数调用 |
| 开岛请求 | EE | SI | 新 `IslandConfig` + 种子策略 | 函数调用 |

---

## 11. 全局编号索引

### 11.1 文件编号

#### 源代码文件

| 文件编号 | 文件路径 | 所属模块 | 覆盖功能 | 状态 |
|---------|---------|---------|---------|------|
| **F-001** | `src/core/multi_path.py` | 第一层 | EA-001, EA-005~012 | ✅ 已实现（V2 需改造接入 QP/SI/IST） |
| **F-002** | `src/core/pipeline.py` | 第一层 | 管道（含多路径入口） | ✅ 已实现 |
| **F-003** | `src/core/orchestrator.py` | 第一层 | 原版编排器 | ✅ 已实现 |
| **F-004** | `src/core/cost_tracker.py` | 基础设施 | EA-304 | ✅ 已实现 |
| **F-005** | `src/core/streaming.py` | 第一层 | EA-011 | ✅ 已实现 |
| **F-006** | `src/core/openviking_context.py` | 基础设施 | EA-307 | ✅ 已实现（V2 需按岛/策略结构改造） |
| **F-010** | `src/core/question_parser.py` | QP | SE-001, SE-002 | ✅ 完成 |
| **F-011** | `src/core/strategy_definition.py` | QP | SE-003, SE-005 | ✅ 完成 |
| **F-012** | `src/core/strategy_compiler.py` | QP | SE-004, SE-006 | ✅ 完成 |
| **F-020** | `src/core/strategy_island.py` | SI | SE-010~014 | ✅ 完成 |
| **F-021** | `src/core/island_pool.py` | SI | SE-015~017 | ✅ 完成 |
| **F-030** | `src/evolving/weighted_voter.py` | WV | SE-030~033 | ✅ 完成 |
| **F-040** | `src/core/step_trace.py` | IST | SE-040~042 | ✅ 已完成 |
| **F-041** | `src/core/digest_store.py` | IST | SE-044 | ✅ 已完成 |
| **F-050** | `src/evolving/direction_generator.py` | EE | SE-020~021 | ✅ 完成 |
| **F-051** | `src/evolving/evolution_scheduler.py` | EE | SE-022~023 | ✅ 完成 |
| **F-052** | `src/evolving/island_spawner.py` | EE | SE-024~025 | ✅ 完成 |
| **F-053** | `src/evolving/reflector.py` | EE | 改造: 读 L1 digest | 🔄 需改造 |
| **F-060** | `main.py` | 入口 | 原版单路径入口 | ✅ 已实现 |
| **F-061** | `main_multipath.py` | 入口 | 多路径入口 | ✅ 已实现 |

#### 配置文件

| 文件编号 | 文件路径 | 用途 |
|---------|---------|------|
| **F-C01** | `conf/llm/openrouter-local.yaml` | OpenRouter 配置 (EA-303) |
| **F-C02** | `conf/evoagent/default.yaml` | 默认多路径配置 |
| **F-C03** | `conf/evoagent/strategies.yaml` | 内置策略定义 |
| **F-C04** | `conf/evoagent/evolution.yaml` | 进化参数配置 |

#### 数据目录

| 文件编号 | 路径 | 用途 |
|---------|------|------|
| **F-D01** | `data/islands/island_N_xxx/_meta.json` | 岛元信息 |
| **F-D02** | `data/islands/island_N_xxx/strategies.json` | 岛内策略持久化 |
| **F-D03** | `data/results/task_results.jsonl` | 战绩记录 |
| **F-D04** | `data/digests/task_digests.jsonl` | IST 摘要 |
| **F-D05** | `data/evolution/rounds.jsonl` | 进化日志 |

#### 测试文件

| 文件编号 | 文件路径 | 测试对象 | 状态 |
|---------|---------|---------|------|
| **F-T01** | `src/tests/test_multi_path.py` | EA-001~008 | ✅ |
| **F-T02** | `src/tests/test_early_stopping.py` | EA-009 | ✅ |
| **F-T03** | `src/tests/test_path_budget.py` | EA-010 | ✅ |
| **F-T04** | `src/tests/test_streaming.py` | EA-011 | ✅ |
| **F-T05** | `src/tests/test_retry.py` | EA-012 | ✅ |
| **F-T06** | `src/tests/test_cost_tracker.py` | EA-304 | ✅ |
| **F-T07** | `src/tests/test_openviking.py` | EA-307 | ✅ |
| **F-T10** | `src/tests/test_question_parser.py` | SE-001~002 | 待写 |
| **F-T11** | `src/tests/test_strategy_definition.py` | SE-003~005 | 待写 |
| **F-T12** | `src/tests/test_strategy_compiler.py` | SE-004~006 | 待写 |
| **F-T20** | `src/tests/test_strategy_island.py` | SE-010~014 | 待写 |
| **F-T21** | `src/tests/test_island_pool.py` | SE-015~017 | 待写 |
| **F-T30** | `src/tests/test_weighted_voter.py` | SE-030~033 | 待写 |
| **F-T40** | `src/tests/test_step_trace.py` | SE-040~042 | ✅ |
| **F-T41** | `src/tests/test_digest_store.py` | SE-044 | ✅ |
| **F-T50** | `src/tests/test_direction_generator.py` | SE-020~021 | 待写 |
| **F-T51** | `src/tests/test_evolution_scheduler.py` | SE-022~023 | 待写 |
| **F-T52** | `src/tests/test_island_spawner.py` | SE-024~025 | 待写 |

#### 设计文档

| 文件编号 | 文件路径 | 用途 |
|---------|---------|------|
| **F-DOC-01** | `docs/design/EVOAGENT_DESIGN.md` | V1 总设计（本文档前身） |
| **F-DOC-02** | `docs/design/STRATEGY_EVOLVE_MASTER.md` | 策略进化总纲 |
| **F-DOC-03** | `docs/design/EVOAGENT_DESIGN_V2.md` | **本文档（V2 合并版）** |
| **F-DOC-10** | `docs/design/QP_QUESTION_PARSER_DEV.md` | QP 详细开发文档 |
| **F-DOC-11** | `docs/design/SI_STRATEGY_ISLAND_DEV.md` | SI 详细开发文档 |
| **F-DOC-12** | `docs/design/EE_EVOLUTION_ENGINE_DEV.md` | EE 详细开发文档 |
| **F-DOC-13** | `docs/design/WV_WEIGHTED_VOTING_DEV.md` | WV 详细开发文档 |
| **F-DOC-14** | `docs/design/INLINE_STEP_TRACE_DEV.md` | IST 详细开发文档 |
| **F-DOC-20** | `docs/design/OPENVIKING_INTEGRATION.md` | OpenViking 集成分析 |
| **F-DOC-21** | `docs/design/STRATEGY_EVOLVE_ARCHITECTURE.md` | 架构详述 |
| **F-DOC-22** | `docs/design/THREE_PILLARS.md` | 三支柱架构 |

### 11.2 函数编号

#### F-010 question_parser.py

| 函数编号 | 函数签名 | 功能编号 | 描述 |
|---------|---------|---------|------|
| **FN-010-01** | `async parse_question(task: str) → ParsedQuestion` | SE-001 | LLM 单次调用解析题型/实体/时间窗/criteria |

#### F-011 strategy_definition.py

| 函数编号 | 函数签名 | 功能编号 | 描述 |
|---------|---------|---------|------|
| **FN-011-01** | `StrategyDefinition(dataclass)` | SE-003 | 8 维策略定义数据结构 |
| **FN-011-02** | `strategy_distance(a: StrategyDefinition, b: StrategyDefinition) → float` | SE-005 | 维度差异数 / 7，归一化 0-1 |

#### F-012 strategy_compiler.py

| 函数编号 | 函数签名 | 功能编号 | 描述 |
|---------|---------|---------|------|
| **FN-012-01** | `compile_strategy(s: StrategyDefinition) → CompiledStrategy` | SE-004 | 8 维 → prompt_suffix，TEMPLATES 映射 |
| **FN-012-02** | `SEED_STRATEGIES: List[StrategyDefinition]` | SE-006 | 5 个种子策略常量 |

#### F-020 strategy_island.py

| 函数编号 | 函数签名 | 功能编号 | 描述 |
|---------|---------|---------|------|
| **FN-020-01** | `IslandConfig(dataclass)` | SE-010 | 岛配置: perspective, max_size, elite_ratio, weights |
| **FN-020-02** | `StrategyIsland.__init__(config: IslandConfig)` | SE-011 | 初始化单岛及其策略池 |
| **FN-020-03** | `StrategyIsland.compute_elite_score(s: StrategyDefinition) → float` | SE-012 | fitness_w × fitness_pct + novelty_w × novelty_pct |
| **FN-020-04** | `StrategyIsland.try_insert(s: StrategyDefinition) → bool` | SE-013 | 确定性拥挤淘汰：岛满时比 elite_score 替换最近似非精英 |
| **FN-020-05** | `StrategyIsland.sample(question_type: str) → StrategyDefinition` | SE-014 | 根据题型选胜率最优策略 |
| **FN-020-06** | `StrategyIsland.update_metrics(result: StrategyResult)` | SE-032 | 更新岛内策略的题型条件化胜率 |

#### F-021 island_pool.py

| 函数编号 | 函数签名 | 功能编号 | 描述 |
|---------|---------|---------|------|
| **FN-021-01** | `IslandPool.__init__(islands: List[StrategyIsland])` | SE-015 | 初始化多岛管理器 |
| **FN-021-02** | `IslandPool.sample_all(question_type: str) → List[StrategyDefinition]` | SE-015 | 所有岛各选 1 策略 |
| **FN-021-03** | `IslandPool.add_island(config: IslandConfig, seeds: List[StrategyDefinition])` | SE-015 | 添加新岛（动态开岛时调用） |
| **FN-021-04** | `IslandPool.save(path: str)` | SE-016 | 持久化到本地 JSON / OpenViking |
| **FN-021-05** | `IslandPool.load(path: str) → IslandPool` | SE-016 | 从存储加载 |
| **FN-021-06** | `create_default_pool() → IslandPool` | SE-017 | 创建初始 5 岛配置 |

#### F-030 weighted_voter.py

| 函数编号 | 函数签名 | 功能编号 | 描述 |
|---------|---------|---------|------|
| **FN-030-01** | `WeightedVoter.vote(digests: List[PathDigest]) → VoteResult` | SE-031 | 加权投票: high=3, medium=2, low=1 |
| **FN-030-02** | `WeightedVoter.judge(digests: List[PathDigest]) → VoteResult` | SE-031 | 分裂时 LLM Judge 仲裁（读 L1） |
| **FN-030-03** | `WeightedVoter.record_results(vote: VoteResult, parsed: ParsedQuestion)` | SE-032 | 按 question_type 拆分战绩写入 JSONL |
| **FN-030-04** | `compute_conditioned_fitness(s: StrategyDefinition, qtype: str) → float` | SE-033 | 有题型数据(≥3)用题型胜率，否则全局 |

#### F-040 step_trace.py

| 函数编号 | 函数签名 | 功能编号 | 描述 |
|---------|---------|---------|------|
| **FN-040-01** | `TracingToolWrapper.wrap(tool_call) → (result, key_info)` | SE-040 | 工具调用自动提取 key_info (~80 chars) |
| **FN-040-02** | `StepTraceCollector.record_tool_call(step, key_info)` | SE-041 | 收集单步 trace |
| **FN-040-03** | `StepTraceCollector.record_conclusion(text)` | SE-042 | 解析 `<conclusion>` 标签 |
| **FN-040-04** | `StepTraceCollector.finalize() → PathDigest` | SE-043 | 生成 L0/L1/L2 分层摘要 |

#### F-041 digest_store.py

| 函数编号 | 函数签名 | 功能编号 | 描述 |
|---------|---------|---------|------|
| **FN-041-01** | `DigestStore.save(task_id: str, digests: List[PathDigest])` | SE-044 | 写入 JSON / OpenViking |
| **FN-041-02** | `DigestStore.load(task_id: str) → List[PathDigest]` | SE-044 | 读取 digest |

#### F-050 direction_generator.py

| 函数编号 | 函数签名 | 功能编号 | 描述 |
|---------|---------|---------|------|
| **FN-050-01** | `async refine(island: StrategyIsland, digests: List[PathDigest]) → StrategyDefinition` | SE-020 | 拿 top 策略 + L1 失败分析，LLM 微调 1-2 维 |
| **FN-050-02** | `async diverge(island: StrategyIsland) → StrategyDefinition` | SE-021 | LLM 设计全新变种（≥3 维不同），distance ≥ 0.43 |

#### F-051 evolution_scheduler.py

| 函数编号 | 函数签名 | 功能编号 | 描述 |
|---------|---------|---------|------|
| **FN-051-01** | `async evolve_all(pool: IslandPool, round_digests) → EvolveReport` | SE-022 | 所有岛各 1 refine + 1 diverge |
| **FN-051-02** | `async ring_migrate(pool: IslandPool)` | SE-023 | 环形迁移: i.top → (i+1)，distance < 0.3 跳过 |

#### F-052 island_spawner.py

| 函数编号 | 函数签名 | 功能编号 | 描述 |
|---------|---------|---------|------|
| **FN-052-01** | `detect_spawn_signal(pool: IslandPool, results: List[StrategyResult]) → Optional[str]` | SE-024 | 某题型全岛 best_rate < 0.4 且 samples ≥ 5 → 返回题型 |
| **FN-052-02** | `async spawn_island(pool: IslandPool, weak_qtype: str) → StrategyIsland` | SE-025 | LLM 生成新视角 + 种子策略 → 添加到 pool |

#### F-001 multi_path.py（V2 改造后）

| 函数编号 | 函数签名 | 功能编号 | 描述 |
|---------|---------|---------|------|
| **FN-001-01** | `async run_multi_path(task: str, pool: IslandPool) → FinalResult` | EA-001 | V2 主流程：QP→SI→编译→并行执行→IST→WV→记录→进化 |
| **FN-001-02** | `async run_single_path(task, compiled: CompiledStrategy, tracer: StepTraceCollector)` | EA-001 | 单路径执行 + IST 留痕 |
| **FN-001-03** | `check_early_stop(digests: List[PathDigest]) → bool` | EA-009 | 前 K 条共识检测 |
| **FN-001-04** | `create_tool_manager() → ToolManager` | EA-005 | 创建独立 ToolManager 实例 |

---

## 12. V1 → V2 编号映射总表

| V1 编号 | V1 名称 | V2 编号 | V2 名称 | 变化类型 |
|---------|---------|---------|---------|---------|
| EA-001 | 多路径调度器 | EA-001 (FN-001-01) | 多路径调度器 | **保留**，改造接入 QP/SI |
| EA-002 | 策略变体定义 | SE-003 + SE-006 | 8 维定义 + 种子策略 | **替代** |
| EA-003 | LLM 投票评选 | SE-031 (FN-030-02) | 加权投票 + Judge | **替代** |
| EA-004 | 多数投票快速路径 | SE-031 (FN-030-01) | 加权投票 | **合并** |
| EA-005~012 | 路径管理 | EA-005~012 | 同上 | **保留** |
| EA-101 | 策略战绩记录器 | SE-032 (FN-030-03) | WV 内置记录 | **替代** |
| EA-102 | 策略画像引擎 | SE-012 (FN-020-03) | elite_score | **替代** |
| EA-103 | 任务分类器 | SE-001 (FN-010-01) | QP 解析 | **替代** |
| EA-104 | 自适应策略选择 | SE-014 (FN-020-05) + SE-015 (FN-021-02) | 岛内采样 | **替代** |
| EA-105 | 策略参数微调 | SE-020 (FN-050-01) | EE refine | **替代** |
| EA-106 | 策略淘汰机制 | SE-013 (FN-020-04) | 确定性拥挤淘汰 | **替代** |
| EA-107 | 策略种群管理 | SE-011 + SE-015 | 岛池管理 | **替代** |
| EA-108 | 经验提取器 | SE-043 (FN-040-04) + SE-020 (FN-050-01) | IST digest + EE 分析 | **替代** |
| EA-201 | LLM 策略生成器 | SE-020 + SE-021 (FN-050-01/02) | refine + diverge | **替代** |
| EA-202 | 策略代码进化 | — | — | **移除** |
| EA-203 | 跨维度自适应 | SE-024 + SE-025 (FN-052-01/02) | 动态开岛 | **替代** |
| EA-301~307 | 基础设施 | EA-301~307 | 同上 | **保留** |
| EA-401~410 | 测试 | EA-401~410 | 同上 | **保留** |

---

## 13. 存储结构

### 13.1 本地存储（默认，零外部依赖）

```
data/
├── islands/                              ← SI 持久化
│   ├── island_0_news/
│   │   ├── _meta.json                     岛元信息
│   │   └── strategies.json                岛内策略
│   ├── island_1_mechanism/
│   ├── island_2_historical/
│   ├── island_3_market/
│   └── island_4_counterfactual/
├── results/
│   └── task_results.jsonl                 ← WV 战绩
├── digests/
│   └── task_digests.jsonl                 ← IST 摘要
└── evolution/
    └── rounds.jsonl                       ← EE 进化日志
```

### 13.2 OpenViking 映射（可选升级）

| 本地路径 | OpenViking URI | 说明 |
|---------|---------------|------|
| `data/islands/` | `viking://agent/skills/islands/` | 岛和策略 |
| `data/results/` | `viking://agent/memories/strategy_results/` | 战绩 |
| `data/digests/` | `viking://agent/memories/task_digests/` | IST 摘要 |
| `data/evolution/` | `viking://agent/memories/evolution_log/` | 进化日志 |

---

## 14. 开发路线图

### Phase 1: QP（2 天）— 题目解析 + 策略定义 + 编译器

| 天 | 任务 | 交付文件 |
|----|------|---------|
| D1 | ParsedQuestion + QuestionParser | F-010 |
| D1 | StrategyDefinition 数据结构 | F-011 |
| D2 | StrategyCompiler + TEMPLATES | F-012 |
| D2 | strategy_distance() | F-011 |

### Phase 2: SI + IST 集成（3 天）— 策略岛 + 留痕接入

| 天 | 任务 | 交付文件 |
|----|------|---------|
| D3 | StrategyIsland 单岛 | F-020 |
| D4 | IslandPool 多岛管理 | F-021 |
| D4 | IST 集成到 multi_path.py | F-001 改造 |
| D5 | OpenViking 存储 + 端到端 | F-006 改造 |

### Phase 3: EE（3 天）— 进化引擎

| 天 | 任务 | 交付文件 |
|----|------|---------|
| D6 | DirectionGenerator (refine + diverge) | F-050 |
| D7 | EvolutionScheduler + 迁移 | F-051 |
| D8 | IslandSpawner + 动态开岛 | F-052 |

### Phase 4: WV（1.5 天）— 加权投票

| 天 | 任务 | 交付文件 |
|----|------|---------|
| D9 | 结构化输出 + 加权投票 | F-030 |
| D9.5 | 题型条件化战绩 + Fitness | F-030 + F-020 改造 |

### 总计: ~9.5 天（IST 4 天已完成）

---

## 15. 设计决策记录

### V1 保留的决策

| 编号 | 决策 | 理由 |
|------|------|------|
| DD-001 | 策略通过 prompt suffix 注入 | 最小侵入性 |
| DD-002 | 每条路径独立 ToolManager | MCP 连接有状态 |
| DD-005 | 本地 subprocess 替代 E2B | 无 E2B key |
| DD-006 | OpenViking 作为存储层 | 统一存储，L0/L1/L2 控制成本 |

### V2 新增/修改的决策

| 编号 | 决策 | 理由 | 影响 |
|------|------|------|------|
| DD-101 | 按专家视角分岛 | 视角差异 = 真实搜索行为差异 | SI |
| DD-102 | 开局 5 个岛 | 对应 5 类专家 | SI, QP |
| DD-103 | Question Parser 前置 | 驱动采样、记录、进化 | QP |
| DD-104 | 每次所有岛全出路径 | 投票多样性最大化 | SI, WV |
| DD-105 | 动态开岛后路径数增加 | 新视角自动加入 | EE, SI |
| DD-106 | 每轮全岛进化 | 数据量小，等停滞太慢 | EE |
| DD-107 | 每岛每轮 1 refine + 1 diverge | 既优化又探索 | EE |
| DD-108 | 题型条件化评估 | 全局胜率掩盖真实表现 | WV, SI |
| DD-109 | 动态开岛由题型表现触发 | 全岛不擅长 → 需新视角 | EE |
| DD-110 | 8 维结构化策略定义 | 可独立进化、可算距离 | QP |
| DD-111 | elite_score = 质量 + 新颖度 | 岛内多样性由数学保证 | SI |
| DD-112 | 移除策略代码进化 (EA-202) | 8 维结构化已够用，过早优化 | — |
| DD-113 | 简单投票改为加权投票 | confidence 加权更准 | WV |
| DD-114 | Task Digest 替代原始 log 做进化 | token 节省 95% | IST, EE |
| DD-115 | 本地 JSON 默认，OV 可选 | 零外部依赖，格式一一对应 | SI, IST |
| DD-201 | QP 最先开发 | 其他模块依赖其输出 | 全部 |
| DD-203 | 模块间数据结构耦合 | 系统小，避免过度工程 | 全部 |
| DD-204 | 战绩由 WV 负责 | 投票天然产出战绩 | WV |
| DD-205 | 进化读 L1 digest | token 节省 95% | EE, IST |

---

## 16. 风险与缓解

| 风险 | 影响 | 缓解 |
|------|------|------|
| 5 岛全上成本 ≈ 原 3 路径的 1.7 倍 | 高 | 保留早停 (EA-009)；低难度减路径；小模型做 QP |
| Question Parser 分类不准 | 中 | 大模型验证；兜底全局胜率 |
| LLM 生成策略趋同 | 中 | distance 强制 diverge ≥ 3 维；novelty_weight 40% |
| 动态开岛失控 | 低 | 岛数上限 8；开岛阈值严格 |
| 进化前期数据不足 | 中 | 种子策略预设合理；冷启动用全局胜率 |

---

## 17. 术语表

| 术语 | 定义 |
|------|------|
| **Island（岛）** | 代表一种专家视角的策略容器，岛内有多个策略变种 |
| **StrategyDefinition** | 8 维结构化策略定义 (Hi/Qi/Ei/Ri/Ui/Ai/Ti + max_turns) |
| **elite_score** | 岛内策略综合得分 = fitness × w1 + novelty × w2 |
| **确定性拥挤淘汰** | 岛满时，新策略与最近似非精英比 elite_score |
| **环形迁移** | 岛间 top 策略按 0→1→2→...→N→0 复制 |
| **动态开岛** | 某题型全岛差 → LLM 定义新视角 → 创建新岛 |
| **refine** | 微调现有策略 1-2 维 |
| **diverge** | 在岛视角内设计全新变种 (≥3 维不同) |
| **ParsedQuestion** | 题目解析结果 (题型/实体/时间窗/criteria) |
| **PathDigest** | 路径执行摘要，分 L0(~30tok) / L1(~300tok) / L2(原始) |
| **加权投票** | confidence 加权: high=3 / medium=2 / low=1 |
| **Round（轮）** | 一批评测题，轮次结束触发全岛进化 |
| **MiroThinker** | 基线 Research Agent，单路径 ReAct 执行器 |
| **QP** | Question Parser — 题目解析 + 策略编译 |
| **SI** | Strategy Island — 岛池管理 |
| **EE** | Evolution Engine — 进化引擎 |
| **WV** | Weighted Voting — 加权投票 |
| **IST** | Inline Step Trace — 运行时留痕 |
