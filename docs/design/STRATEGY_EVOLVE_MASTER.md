# Strategy Evolution 总纲文档

> **项目代号**: EvoAgent — Strategy Evolution  
> **文档类型**: 总调度文档（Master Plan）  
> **前置文档**: `EVOAGENT_DESIGN.md`, `STRATEGY_EVOLVE_ARCHITECTURE.md`, `THREE_PILLARS.md`  
> **核心参考**: SkyDiscover（AdaEvolve + EvoX 双层进化框架），谢一凡硕士论文 (SJTU, 2025)  
> **创建日期**: 2026-03-20  
> **最后更新**: 2026-03-20  
> **编号前缀**: SE = Strategy Evolution

---

## 一、一句话总结

**5 个专家视角岛，每次任务由 Question Parser 解析题型，所有岛各出 1 条路径并行执行（带 IST 留痕），加权投票选最优答案，每轮结束后全岛进化（refine + diverge），题型全岛不擅长时动态开新岛。**

---

## 二、全局架构总览

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    STRATEGY EVOLUTION — 全局架构                             │
│                                                                             │
│  ┌─────────────────────────────────────────────────────────────────────┐    │
│  │                    QP — Question Parser                             │    │
│  │   Task ──→ [LLM 1次调用] ──→ ParsedQuestion                        │    │
│  │              (题型/实体/时间窗/criteria)                              │    │
│  └──────────────────────┬──────────────────────────────────────────────┘    │
│                         │                                                   │
│                         ▼                                                   │
│  ┌─────────────────────────────────────────────────────────────────────┐    │
│  │                    SI — Strategy Island Pool                        │    │
│  │                                                                     │    │
│  │  ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────────┐     │    │
│  │  │ Island 0 │ │ Island 1 │ │ Island 2 │ │ Island 3 │ │ Island N │     │    │
│  │  │ 信息追踪  │ │ 机制分析  │ │ 历史类比  │ │ 市场信号  │ │ (动态)   │     │    │
│  │  │ [策略池]  │ │ [策略池]  │ │ [策略池]  │ │ [策略池]  │ │ [策略池]  │     │    │
│  │  └────┬────┘ └────┬────┘ └────┬────┘ └────┬────┘ └────┬────┘     │    │
│  │       │           │           │           │           │           │    │
│  │   所有岛各选 1 策略（根据 question_type 选岛内最优）                  │    │
│  └───┬───────┬───────┬───────┬───────┬──────────────────────────────┘    │
│      │       │       │       │       │                                    │
│      ▼       ▼       ▼       ▼       ▼                                    │
│  ┌─────────────────────────────────────────────────────────────────────┐    │
│  │  QP — Strategy Compiler:  8维定义 → prompt_suffix                   │    │
│  └──────────────────────┬──────────────────────────────────────────────┘    │
│                         │                                                   │
│      ┌──────────────────┼──────────────────┐                               │
│      ▼                  ▼                  ▼                               │
│   Path 0             Path 1             Path N                             │
│   (MiroThinker)      (MiroThinker)      (MiroThinker)                     │
│   + IST 留痕          + IST 留痕          + IST 留痕                       │
│      │                  │                  │                               │
│      └──────────────────┼──────────────────┘                               │
│                         ▼                                                   │
│  ┌─────────────────────────────────────────────────────────────────────┐    │
│  │                    WV — Weighted Voting                             │    │
│  │   confidence 加权投票 → 分裂时 LLM Judge 仲裁 → 最终答案              │    │
│  └──────────────────────┬──────────────────────────────────────────────┘    │
│                         │                                                   │
│                    ┌────┴────┐                                              │
│                    ▼         ▼                                              │
│              IST 保存      WV 记录                                          │
│              digest        战绩                                             │
│                    │         │                                              │
│                    └────┬────┘                                              │
│                         ▼  [一轮结束]                                       │
│  ┌─────────────────────────────────────────────────────────────────────┐    │
│  │                    EE — Evolution Engine                            │    │
│  │   所有岛各自进化 (refine + diverge) → 岛间迁移 → 检查动态开岛          │    │
│  └─────────────────────────────────────────────────────────────────────┘    │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 三、模块清单与依赖

### 3.1 子模块列表

| 代号 | 模块名称 | 详细开发文档 | 覆盖内容 | 状态 | 优先级 |
|------|---------|-------------|---------|------|--------|
| **QP** | Question Parser + 策略定义 + 编译器 | `QP_QUESTION_PARSER_DEV.md` | 题目解析、8维 StrategyDefinition、策略编译器、策略距离 | ❌ 待开发 | P0 |
| **SI** | Strategy Island | `SI_STRATEGY_ISLAND_DEV.md` | 策略岛、岛池、elite_score、淘汰、采样、OpenViking 存储 | ❌ 待开发 | P0 |
| **EE** | Evolution Engine | `EE_EVOLUTION_ENGINE_DEV.md` | refine/diverge 进化、岛间迁移、动态开岛 | ❌ 待开发 | P1 |
| **WV** | Weighted Voting | `WV_WEIGHTED_VOTING_DEV.md` | 置信度结构化输出、加权投票、题型条件化评估、战绩记录 | ❌ 待开发 | P1 |
| **IST** | Inline Step Trace | `INLINE_STEP_TRACE_DEV.md` | 运行时每步留痕、自动生成 L0/L1/L2 摘要、DigestStore | ✅ 已完成 | P0 |

### 3.2 依赖关系图

```
QP (Question Parser + 策略定义)  ← 最先开发，其他模块依赖策略定义
    │
    ├── SI (策略岛) ← 依赖 QP 的 StrategyDefinition + compile_strategy()
    │       │
    │       └── EE (进化引擎) ← 依赖 SI 的 Island + StrategyPool
    │
    ├── WV (加权投票) ← 依赖 QP 的 ParsedQuestion（题型条件化记录）
    │
    └── IST (已完成) ← 独立模块，Phase 2 时集成到路径执行流程
```

**关键依赖说明**：

| 依赖方向 | 依赖内容 | 说明 |
|---------|---------|------|
| SI → QP | `StrategyDefinition`, `strategy_distance()` | 岛内策略的数据结构和距离度量 |
| SI → QP | `compile_strategy()` | 采样后需要编译成 prompt_suffix |
| EE → SI | `StrategyIsland`, `IslandPool` | 进化操作作用于岛和策略池 |
| EE → QP | `StrategyDefinition` | refine/diverge 生成新的策略定义 |
| WV → QP | `ParsedQuestion.question_type` | 按题型记录战绩 |
| IST → 无 | 独立 | 只需嵌入路径执行流程 |

---

## 四、全局功能编号

SE-xxx 是总纲级编号，每个对应子模块文档里的详细编号。

### 4.1 QP — Question Parser + 策略定义 + 编译器

| SE 编号 | 功能名称 | 子模块详细编号 | 描述 | 状态 | 优先级 |
|---------|---------|--------------|------|------|--------|
| **SE-001** | 题目解析器 | QP-001 | LLM 单次调用解析题型/实体/时间窗/criteria | ❌ 待开发 | P0 |
| **SE-002** | ParsedQuestion 数据结构 | QP-002 | question_type, key_entities, time_window, resolution_criteria, difficulty_hint | ❌ 待开发 | P0 |
| **SE-003** | 8 维策略定义 | QP-003 | StrategyDefinition: Hi/Qi/Ei/Ri/Ui/Ai/Ti + max_turns | ❌ 待开发 | P0 |
| **SE-004** | 策略编译器 | QP-004 | 8 维 → prompt_suffix，TEMPLATES 映射 | ❌ 待开发 | P0 |
| **SE-005** | 策略距离度量 | QP-005 | 维度差异数 / 7，归一化 0-1 | ❌ 待开发 | P1 |
| **SE-006** | 5 个种子策略 | QP-006 | 信息追踪/机制分析/历史类比/市场信号/对抗验证 初始定义 | ❌ 待开发 | P0 |

### 4.2 SI — Strategy Island

| SE 编号 | 功能名称 | 子模块详细编号 | 描述 | 状态 | 优先级 |
|---------|---------|--------------|------|------|--------|
| **SE-010** | 单岛结构 | SI-001 | IslandConfig: perspective, max_size, elite_ratio, fitness/novelty_weight | ❌ 待开发 | P0 |
| **SE-011** | 岛内策略池 | SI-002 | 策略存储、CRUD、持久化（JSON / OpenViking） | ❌ 待开发 | P0 |
| **SE-012** | Elite Score 计算 | SI-003 | fitness_weight × fitness_percentile + novelty_weight × novelty_percentile | ❌ 待开发 | P0 |
| **SE-013** | 确定性拥挤淘汰 | SI-004 | 岛满时：找最近似非精英，新策略 elite_score 更高则替换 | ❌ 待开发 | P1 |
| **SE-014** | 岛内策略采样 | SI-005 | 根据 question_type 选该题型上胜率最优的策略 | ❌ 待开发 | P0 |
| **SE-015** | 多岛管理器 IslandPool | SI-006 | 管理所有岛的生命周期，提供全局 API | ❌ 待开发 | P0 |
| **SE-016** | OpenViking 存储集成 | SI-007 | L0/L1/L2 分层存储，无 Server 降级为本地 JSON | ❌ 待开发 | P1 |
| **SE-017** | 初始 5 岛配置 | SI-008 | 信息追踪/机制分析/历史类比/市场信号/对抗验证 | ❌ 待开发 | P0 |

### 4.3 EE — Evolution Engine

| SE 编号 | 功能名称 | 子模块详细编号 | 描述 | 状态 | 优先级 |
|---------|---------|--------------|------|------|--------|
| **SE-020** | Refine 操作 | EE-001 | 拿岛内 top 策略，LLM 微调 1-2 维 | ❌ 待开发 | P0 |
| **SE-021** | Diverge 操作 | EE-002 | 在岛视角内，LLM 设计全新变种（≥3 维不同） | ❌ 待开发 | P0 |
| **SE-022** | 每轮全岛进化调度 | EE-003 | 一轮题结束后，所有岛各 1 refine + 1 diverge = 2 新策略/岛 | ❌ 待开发 | P0 |
| **SE-023** | 岛间环形迁移 | EE-004 | top 策略复制到下一岛，距离 < 0.3 不迁移 | ❌ 待开发 | P1 |
| **SE-024** | 动态开岛检测 | EE-005 | 某题型全岛 best_rate < 0.4 且 samples ≥ 5 → 触发 | ❌ 待开发 | P1 |
| **SE-025** | 动态开岛执行 | EE-006 | LLM 生成新视角 + 初始策略 → spawn 新岛 | ❌ 待开发 | P1 |

### 4.4 WV — Weighted Voting

| SE 编号 | 功能名称 | 子模块详细编号 | 描述 | 状态 | 优先级 |
|---------|---------|--------------|------|------|--------|
| **SE-030** | 结构化输出规范 | WV-001 | 答案 + confidence(high/medium/low) + 关键证据 + 风险 | ❌ 待开发 | P0 |
| **SE-031** | 加权投票机制 | WV-002 | high=3票, medium=2票, low=1票；一致直接采用，分裂 Judge | ❌ 待开发 | P0 |
| **SE-032** | 题型条件化战绩记录 | WV-003 | 按 question_type 拆分 wins/total/rate | ❌ 待开发 | P0 |
| **SE-033** | Fitness 条件化计算 | WV-004 | 有题型数据(≥3样本)用题型胜率，否则退回全局 | ❌ 待开发 | P1 |

### 4.5 IST — Inline Step Trace（✅ 已完成）

| SE 编号 | 功能名称 | 子模块详细编号 | 描述 | 状态 | 优先级 |
|---------|---------|--------------|------|------|--------|
| **SE-040** | TracingToolWrapper | IST-001 | 工具调用自动提取 key_info (~80 chars) | ✅ 已完成 | P0 |
| **SE-041** | StepTraceCollector | IST-002 | 收集每步 trace，路径结束后 finalize | ✅ 已完成 | P0 |
| **SE-042** | ConclusionExtractor | IST-003 | 解析 `<conclusion>` 标签提取结论 | ✅ 已完成 | P0 |
| **SE-043** | L0/L1/L2 分层摘要 | IST-004 | L0 ~30tok, L1 ~300tok, L2 ~5k-15k tok (原始引用) | ✅ 已完成 | P0 |
| **SE-044** | DigestStore | IST-005 | 本地 JSON / OpenViking 持久化 | ✅ 已完成 | P0 |

---

## 五、IST 集成说明

IST（Inline Step Trace）已独立完成，需在 Phase 2 集成到主流程。集成点如下：

### 5.1 集成架构

```
N 条路径并行执行
    │
    ▼ 每步执行
    │
    ├── 工具调用 → TracingToolWrapper → StepTraceCollector.record_tool_call()
    │                                    (自动提取 key_info，零额外 API 调用)
    │
    ├── 模型输出 → ConclusionExtractor → StepTraceCollector.record_conclusion()
    │
    ... (重复 N 步)
    │
    ▼ Path 执行完毕
    │
    ├── StepTraceCollector.finalize() → 生成 L0/L1/L2
    │       │
    │       ├── L0 (PathSummary)  → WV 投票使用 (~30 tokens)
    │       ├── L1 (PathDigest)   → EE 进化使用 (~300 tokens)
    │       └── L2 (原始引用)     → 按需深度分析
    │
    ▼ DigestStore 写入
        → 本地: evoagent/data/digests/
        → OpenViking: viking://agent/memories/task_digests/
```

### 5.2 IST 与各模块的交互

| 交互方 | 交互方式 | 数据层级 | 说明 |
|--------|---------|---------|------|
| **WV** (投票) | 读 L0 | ~30 tok/path | 答案 + confidence，用于加权投票 |
| **EE** (进化) | 读 L1 | ~300 tok/path | 推理链 + 失败分析，用于 refine/diverge 方向判断 |
| **Reflector** | 读 L1 | ~300 tok/path | 替代原始 log，token 节省 95% |
| **调试** | 读 L2 | 按需 | 原始 step_logs 仍保留在 logs/ |

### 5.3 集成时间

IST 在 **Phase 2（SI 开发期间）** 集成。集成工作量约 0.5 天：
- 修改 `multi_path.py`：路径执行时注入 TracingToolWrapper
- 修改 `reflector.py`：读 digest 而非原始 log
- 确认 DigestStore 写入路径与 SI 存储结构对齐

---

## 六、核心数据流

### 6.1 单次任务流程

```
Task 到达
    │
    ▼  ① QP: 解析题目
    ParsedQuestion { question_type, key_entities, time_window, criteria }
    │
    ▼  ② SI: 所有岛各选策略
    [Island_0.sample(qtype), Island_1.sample(qtype), ..., Island_N.sample(qtype)]
    │
    ▼  ③ QP: 编译策略 → prompt_suffix
    [compile_strategy(s0), compile_strategy(s1), ..., compile_strategy(sN)]
    │
    ▼  ④ N 路径并行执行 + IST 留痕
    Path_0(MiroThinker + strategy_0 + IST)
    Path_1(MiroThinker + strategy_1 + IST)
    ...
    Path_N(MiroThinker + strategy_N + IST)
    │
    ▼  ⑤ IST: 每路径 finalize → L0/L1/L2 digest
    │
    ▼  ⑥ WV: 加权投票 → 最终答案
    │       (读 L0: 答案 + confidence)
    │       (分裂时 Judge 读 L1: 推理链 + 证据)
    │
    ▼  ⑦ WV: 记录战绩
    │       strategy_results/{task_id}.json
    │       {island, strategy, question_type, won, adopted}
    │
    ▼  ⑧ IST: digest 持久化
            DigestStore → 本地 JSON / OpenViking
```

### 6.2 轮次结束流程

```
一轮（如 10 题）结束
    │
    ▼  ⑨ EE: 所有岛各自进化
    │       每岛: 1 refine + 1 diverge = 2 新策略
    │       读 L1 digest 分析失败案例
    │
    ▼  ⑩ EE: 岛间环形迁移
    │       Island_0.top → Island_1, Island_1.top → Island_2, ...
    │
    ▼  ⑪ EE: 检查动态开岛
            某题型全岛 best_rate < 0.4 → LLM 生成新视角 → spawn 新岛
```

---

## 七、跨模块接口约定

### 7.1 核心数据结构

#### ParsedQuestion（QP 输出 → SI, WV 消费）

```python
@dataclass
class ParsedQuestion:
    question_type: str        # politics / entertainment / sports / finance / tech / science / other
    key_entities: List[str]   # 关键实体
    time_window: str          # 时间窗口描述
    resolution_criteria: str  # 判定标准
    difficulty_hint: str      # easy / medium / hard
```

#### StrategyDefinition（QP 定义 → SI 存储 → EE 进化）

```python
@dataclass
class StrategyDefinition:
    id: str
    name: str
    island_id: str
    # 8 维
    hypothesis_framing: str    # Hi
    query_policy: str          # Qi
    evidence_source: str       # Ei
    retrieval_depth: str       # Ri: shallow / medium / deep
    update_policy: str         # Ui: fast / moderate / conservative
    audit_policy: str          # Ai
    termination_policy: str    # Ti
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

#### CompiledStrategy（QP 编译器输出 → 路径执行消费）

```python
@dataclass
class CompiledStrategy:
    name: str
    max_turns: int
    prompt_suffix: str         # 8 维编译后的完整指令
    _strategy_def: StrategyDefinition  # 原始定义引用
```

#### PathDigest（IST 输出 → WV, EE 消费）

```python
# L0
@dataclass
class PathSummary:
    answer: str
    confidence: str            # high / medium / low
    token_cost: int

# L1
@dataclass
class PathDigest:
    summary: PathSummary       # 包含 L0
    reasoning_chain: str       # 2-3 句话的推理过程
    key_findings: List[str]    # 关键发现
    potential_issues: List[str] # 可能的问题
    step_traces: List[StepTrace]  # 全部步骤痕迹
```

#### StrategyResult（WV 输出 → SI, EE 消费）

```python
@dataclass
class StrategyResult:
    task_id: str
    island_id: str
    strategy_id: str
    question_type: str
    won: bool                  # 该策略的答案是否被采纳
    adopted: bool              # 该策略的答案是否为最终答案
    confidence: str
    timestamp: str
```

### 7.2 模块间接口汇总

| 接口 | 生产者 | 消费者 | 数据 | 传递方式 |
|------|--------|--------|------|---------|
| 题目解析 | QP | SI, WV | `ParsedQuestion` | 函数返回值 |
| 策略采样 | SI | QP (编译) | `StrategyDefinition` | 函数返回值 |
| 策略编译 | QP | 路径执行 | `CompiledStrategy` | 函数返回值 |
| 步骤留痕 | IST | WV, EE | `PathSummary` / `PathDigest` | DigestStore (JSON/OV) |
| 战绩记录 | WV | SI, EE | `StrategyResult` | 文件存储 (JSONL) |
| 进化请求 | EE | SI | 新 `StrategyDefinition` | 函数调用 |
| 开岛请求 | EE | SI | 新 `IslandConfig` + 种子策略 | 函数调用 |

---

## 八、文件结构

### 8.1 设计文档

```
docs/design/
├── STRATEGY_EVOLVE_MASTER.md          ← 本文件（总纲）
├── STRATEGY_EVOLVE_ARCHITECTURE.md    ← 架构详述（已有）
├── QP_QUESTION_PARSER_DEV.md          ← QP 详细开发文档（待写）
├── SI_STRATEGY_ISLAND_DEV.md          ← SI 详细开发文档（待写）
├── EE_EVOLUTION_ENGINE_DEV.md         ← EE 详细开发文档（待写）
├── WV_WEIGHTED_VOTING_DEV.md          ← WV 详细开发文档（待写）
├── INLINE_STEP_TRACE_DEV.md           ← IST 详细开发文档（✅ 已有）
├── EVOAGENT_DESIGN.md                 ← 总设计文档（已有）
├── THREE_PILLARS.md                   ← 三支柱架构（已有）
└── OPENVIKING_INTEGRATION.md          ← OpenViking 集成（已有）
```

### 8.2 源代码（目标结构）

```
src/
├── core/
│   ├── question_parser.py             ← SE-001~002  QP: 题目解析
│   ├── strategy_definition.py         ← SE-003~005  QP: 8维定义 + 距离
│   ├── strategy_compiler.py           ← SE-004      QP: 8维 → prompt_suffix
│   ├── strategy_island.py             ← SE-010~014  SI: 单岛管理
│   ├── island_pool.py                 ← SE-015~017  SI: 多岛管理
│   ├── step_trace.py                  ← SE-040~042  IST: 留痕收集 (✅)
│   ├── digest_store.py                ← SE-044      IST: 摘要存储 (✅)
│   ├── multi_path.py                  ← 改造: 接入 QP/SI/IST
│   └── openviking_context.py          ← 改造: 按岛/策略结构存储
├── evolving/
│   ├── direction_generator.py         ← SE-020~021  EE: refine/diverge
│   ├── evolution_scheduler.py         ← SE-022~023  EE: 轮次调度 + 迁移
│   ├── island_spawner.py              ← SE-024~025  EE: 动态开岛
│   ├── reflector.py                   ← 改造: 读 L1 digest
│   └── weighted_voter.py              ← SE-030~033  WV: 加权投票
└── data/
    ├── islands/                        ← 岛和策略持久化
    │   ├── island_0_news/
    │   │   ├── _meta.json
    │   │   └── strategies.json
    │   ├── island_1_mechanism/
    │   ├── island_2_historical/
    │   ├── island_3_market/
    │   └── island_4_counterfactual/
    ├── results/
    │   └── task_results.jsonl          ← 战绩
    ├── digests/
    │   └── task_digests.jsonl          ← IST 摘要
    └── evolution/
        └── rounds.jsonl                ← 进化日志
```

---

## 九、全局开发路线图

```
          Week 1                    Week 2                 Week 2.5
    ┌──────────────┐    ┌────────────────────┐    ┌──────────────┐
    │   Phase 1    │    │     Phase 2        │    │   Phase 3    │
    │   QP (2天)   │───→│   SI (3天)         │───→│   EE (3天)   │
    │              │    │   + IST 集成(0.5天) │    │              │
    └──────────────┘    └────────────────────┘    └──────┬───────┘
                                                         │
                                                         ▼
                                                  ┌──────────────┐
                                                  │   Phase 4    │
                                                  │   WV (1.5天) │
                                                  └──────────────┘

    IST ✅ 已完成 (4天) ← 在 Phase 2 时集成到主流程
```

### Phase 1: QP — Question Parser + 策略定义 + 编译器（2 天）

| 天 | 任务 | 交付物 | 验证 |
|----|------|--------|------|
| D1 | ParsedQuestion + QuestionParser 实现 | `question_parser.py` | 解析 cat10 的 10 道题，题型分类准确 |
| D1 | StrategyDefinition 数据结构 | `strategy_definition.py` | 单元测试 |
| D2 | StrategyCompiler + TEMPLATES | `strategy_compiler.py` | 5 个种子策略编译输出合理 |
| D2 | strategy_distance() | `strategy_definition.py` | 距离计算正确，同岛 < 跨岛 |

**里程碑**: `QuestionParser` 能准确解析题型，5 个种子策略可编译为 prompt_suffix。

### Phase 2: SI — 策略岛 + 岛池 + OpenViking 存储（3 天）

| 天 | 任务 | 交付物 | 验证 |
|----|------|--------|------|
| D3 | StrategyIsland 单岛实现 | `strategy_island.py` | 采样、淘汰、elite_score 单元测试 |
| D4 | IslandPool 多岛管理 | `island_pool.py` | 5 岛初始化、全岛采样 |
| D4 | IST 集成 | 修改 `multi_path.py` | 路径执行带 IST 留痕 |
| D5 | OpenViking 存储 + multi_path 改造 | 修改 `openviking_context.py`, `multi_path.py` | 跑 cat10，5 路径输出多样 |

**里程碑**: 跑 cat10，5 条路径分别来自 5 个岛，答案多样性显著高于旧系统。

### Phase 3: EE — 进化引擎 + 动态开岛（3 天）

| 天 | 任务 | 交付物 | 验证 |
|----|------|--------|------|
| D6 | DirectionGenerator (refine + diverge) | `direction_generator.py` | LLM 生成的新策略符合 8 维定义 |
| D7 | EvolutionScheduler + 迁移 | `evolution_scheduler.py` | 2 轮 cat10 后新策略被生成和使用 |
| D8 | IslandSpawner + 动态开岛 | `island_spawner.py` | 触发条件正确，新岛可正常参与 |

**里程碑**: 跑 2 轮 cat10，第 2 轮观察到新策略；反思 token 下降 90%+（IST 效果）。

### Phase 4: WV — 加权投票 + 题型条件化评估（1.5 天）

| 天 | 任务 | 交付物 | 验证 |
|----|------|--------|------|
| D9 | 结构化输出 + 加权投票 | `weighted_voter.py` | 投票逻辑正确，加权生效 |
| D9.5 | 题型条件化战绩 + Fitness 计算 | 修改 SI, EE | 战绩按题型拆分，进化读条件化 fitness |

**里程碑**: 加权投票 Judge 准确率提升；全链路端到端可运行。

### 工期汇总

| Phase | 模块 | 天数 | 累计 |
|-------|------|------|------|
| Phase 1 | QP | 2 天 | 2 天 |
| Phase 2 | SI + IST集成 | 3 天 | 5 天 |
| Phase 3 | EE | 3 天 | 8 天 |
| Phase 4 | WV | 1.5 天 | 9.5 天 |
| IST | ✅ 已完成 | (4 天) | — |
| **总计** | | **~9.5 天** + IST 4天(已完成) = **~13.5 天** | |

---

## 十、设计决策记录

### 10.1 架构级决策（来自 STRATEGY_EVOLVE_ARCHITECTURE.md）

| 编号 | 决策 | 理由 | 影响模块 |
|------|------|------|---------|
| **DD-101** | 按专家视角分岛 | 视角差异 = 真实搜索行为差异，比 quality/diversity 分法更适合预测场景 | SI |
| **DD-102** | 开局 5 个岛 | 对应 meta-evolve-plan 的 5 类专家（信息追踪/机制分析/历史类比/市场信号/对抗验证） | SI, QP |
| **DD-103** | Question Parser 前置 | 驱动岛内策略采样、题型条件化记录、进化方向判断 | QP |
| **DD-104** | 每次所有岛全部出路径 | 5 个视角全参与，投票多样性最大化 | SI, WV |
| **DD-105** | 动态开岛后路径数随之增加 | 新视角自动加入，不需要淘汰老岛 | EE, SI |
| **DD-106** | 每轮全岛进化，不靠停滞检测 | 数据量小（每轮 10 题），等停滞再进化太慢 | EE |
| **DD-107** | 每岛每轮 1 refine + 1 diverge | 既优化已有的，又探索新的 | EE |
| **DD-108** | 题型条件化评估 | 不同题型适用不同策略，全局胜率会掩盖真实表现 | WV, SI |
| **DD-109** | 动态开岛由题型表现触发 | 某类题所有岛都不擅长 → 需要全新视角 | EE |
| **DD-110** | 策略用 8 维结构化定义 | 可独立进化、可计算距离、可组合 | QP |
| **DD-111** | elite_score = 质量 + 新颖度 | 岛内多样性由数学保证 | SI |
| **DD-112** | 进化生成的策略不受视角约束 | diverge 可探索视角边界，迁移可跨视角 | EE |
| **DD-113** | OpenViking 格式统一存储 | 岛/策略/战绩/摘要统一 URI，L0/L1/L2 分层加载，无 Server 降级为本地 JSON | SI, IST |
| **DD-114** | Task Digest 替代原始 log | 执行完立刻生成精炼摘要，反思和进化只读摘要，token 节省 95% | IST |
| **DD-115** | 原始 log 保留但不用于反思 | 原始 step_logs 仍写入 logs/ 用于调试，digest 用于进化链路 | IST |

### 10.2 跨模块决策（总纲新增）

| 编号 | 决策 | 理由 | 影响模块 |
|------|------|------|---------|
| **DD-201** | QP 最先开发，其他模块依赖其输出 | StrategyDefinition 和 ParsedQuestion 是全局基础数据结构 | 全部 |
| **DD-202** | IST 在 Phase 2 集成而非单独 Phase | IST 已完成，集成只需 0.5 天，与 SI 同期进行效率最高 | IST, SI |
| **DD-203** | 模块间通过数据结构耦合，不通过事件总线 | 系统规模小，函数调用 + 共享存储足够，避免过度工程 | 全部 |
| **DD-204** | 战绩记录由 WV 负责而非独立模块 | 投票结果天然产出战绩数据，放在 WV 减少跨模块调用 | WV |
| **DD-205** | 进化读 L1 digest 而非原始 log | token 节省 95%，IST 的 L1 已包含推理链和失败分析 | EE, IST |
| **DD-206** | 本地 JSON 为默认存储，OpenViking 为可选升级 | 开发阶段零外部依赖，数据格式与 OV URI 一一对应，切换零成本 | SI, IST |

---

## 十一、全局风险与缓解

| 编号 | 风险 | 影响 | 概率 | 缓解措施 |
|------|------|------|------|---------|
| **R-001** | 5 岛全上成本过高 | 5 路径 = 现有 3 路径的 1.7 倍 API 成本 | 高 | ① 保留早停机制（EA-009）；② 低难度题可减少路径数；③ 用小模型做 QP 和 digest |
| **R-002** | Question Parser 分类不准 | 题型错误 → 策略选择不优 → 进化方向偏差 | 中 | ① 初期用大模型验证分类准确率；② 分类结果保存，可人工校正；③ 兜底：全局胜率作为 fallback |
| **R-003** | LLM 生成的策略趋同 | refine/diverge 都生成相似策略 → 多样性丧失 | 中 | ① strategy_distance 强制 diverge ≥ 3 维不同；② novelty_weight 在 elite_score 中占 40%；③ 岛间迁移引入异质性 |
| **R-004** | 动态开岛失控 | 岛越开越多 → 路径数爆炸 → 成本不可控 | 低 | ① 设岛数上限（如 max_islands=8）；② 开岛阈值严格（rate < 0.4 且 samples ≥ 5）；③ 低活跃岛可休眠 |
| **R-005** | 进化速度太慢 | 每轮 10 题，前几轮数据太少，进化无方向 | 中 | ① 种子策略预设合理初始值；② 前 2 轮侧重 diverge 探索；③ 冷启动期用全局胜率代替题型胜率 |
| **R-006** | 8 维定义的表达力不足 | 某些策略差异无法用 8 维捕捉 | 低 | ① 8 维覆盖了搜索行为的核心方面；② 可扩展（加维度成本低）；③ prompt_suffix 仍可添加自由文本 |
| **R-007** | IST digest 丢失关键信息 | L1 摘要太简练 → 进化分析遗漏重要细节 | 低 | ① L1 包含全部 step_traces；② EE 可按需加载 L2；③ 原始 log 始终保留 |
| **R-008** | 模块间接口变更导致级联修改 | QP 数据结构变更影响 SI/EE/WV | 中 | ① 核心接口（ParsedQuestion, StrategyDefinition）Phase 1 冻结；② 用 dataclass 而非 dict，IDE 可追踪引用 |

---

## 十二、术语表

| 术语 | 缩写 | 定义 |
|------|------|------|
| Question Parser | QP | 代码层模块，LLM 单次调用解析题目类型、关键实体、时间窗口、判定标准 |
| Strategy Island | SI | 策略岛，代表一种专家视角，岛内有多个策略变种 |
| Evolution Engine | EE | 进化引擎，负责 refine/diverge/迁移/动态开岛 |
| Weighted Voting | WV | 加权投票，基于置信度加权选最优答案 |
| Inline Step Trace | IST | 运行时每步留痕，自动生成分层摘要 |
| StrategyDefinition | — | 8 维结构化策略定义（Hi/Qi/Ei/Ri/Ui/Ai/Ti + max_turns） |
| ParsedQuestion | — | 题目解析结果（题型/实体/时间窗/criteria/难度） |
| CompiledStrategy | — | 8 维编译后的 prompt_suffix + 元信息 |
| PathDigest | — | 路径执行摘要，分 L0/L1/L2 三层 |
| elite_score | — | 岛内策略的综合得分 = fitness × w1 + novelty × w2 |
| 确定性拥挤淘汰 | — | 岛满时，新策略与最近似的非精英策略比 elite_score，高者留下 |
| 环形迁移 | — | 岛间 top 策略按 Island_0→1→2→...→N→0 环形复制 |
| 动态开岛 | — | 某题型全岛表现差时，LLM 定义新专家视角，创建新岛 |
| OpenViking | OV | 上下文存储层，支持 L0/L1/L2 分层加载和 `viking://` URI |
| 一轮 | Round | 一批评测题（如 cat10 的 10 题），轮次结束触发进化 |
| MiroThinker | — | 基线 Research Agent，单路径 ReAct 执行器 |

---

## 附录 A：与现有 EA 编号的映射

| SE 编号范围 | EA 编号 | 说明 |
|------------|---------|------|
| SE-001~006 | EA-103 (任务分类), EA-002 (策略定义) | QP 统一了题目解析和策略定义 |
| SE-010~017 | EA-107 (策略种群), EA-104 (自适应选择) | SI 替代了原有的扁平策略池 |
| SE-020~025 | EA-201 (策略生成), EA-105 (参数微调), EA-106 (淘汰) | EE 统一了所有进化操作 |
| SE-030~033 | EA-003 (投票), EA-004 (多数投票), EA-101 (战绩记录), EA-102 (策略画像) | WV 统一了投票和评估 |
| SE-040~044 | EA-307 中的 digest 部分 | IST 独立为专门模块 |

---

> **文档维护**: 各子模块开发过程中如有接口变更，同步更新本文件第七章（跨模块接口约定）。
> **下一步**: 编写 `QP_QUESTION_PARSER_DEV.md`，启动 Phase 1 开发。
