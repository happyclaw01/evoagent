# EvoAgent 项目概述

> **一句话定义：** EvoAgent 是一个基于多路径探索 + 策略自进化的 AI 预测研究 Agent。

---

## 1. 它能做什么

EvoAgent 接收一个预测类问题（如"阿森纳 vs 切尔西谁赢？"、"比特币下周涨还是跌？"），通过多条并行搜索路径进行信息检索和推理，最终给出预测答案。

核心能力：
- **多路径并行预测**：同一个问题由 5 个不同"专家视角"同时探索，各自搜索、推理、得出答案
- **加权投票**：对 5 条路径的结果做 confidence 加权投票，分裂时用 LLM Judge 仲裁
- **策略自进化**：每轮预测后，系统自动分析哪些策略好用、哪些不好用，通过 LLM 生成改进后的策略
- **经验积累**：从历史预测中提取可复用的教训，注入到未来的预测 prompt 中

---

## 2. 核心工作流

```
用户提交预测问题
        │
        ▼
┌─ QP (Question Parser) ──────────────────────────┐
│  LLM 解析题目 → 题型/难度/关键实体/时间窗口       │
└────────────────────┬────────────────────────────┘
                     │
                     ▼
┌─ SI (Strategy Island Pool) ─────────────────────┐
│  5 个策略岛各出 1 条最优策略                       │
│  岛 0: 信息追踪专家                               │
│  岛 1: 机制分析专家                               │
│  岛 2: 历史类比专家                               │
│  岛 3: 市场信号专家                               │
│  岛 4: 对抗验证专家                               │
└────────────────────┬────────────────────────────┘
                     │
                     ▼
┌─ 5 条路径并行执行 ──────────────────────────────┐
│  每条路径:                                        │
│  ├── 接收策略编译后的 prompt_suffix               │
│  ├── 注入历史 experience 到 system prompt         │
│  ├── IST 包装工具调用 → 自动留痕                  │
│  ├── Agent 搜索/推理 (多轮 tool call)             │
│  └── 输出答案 + confidence                        │
└────────────────────┬────────────────────────────┘
                     │
                     ▼
┌─ WV (Weighted Voting) ──────────────────────────┐
│  confidence 加权多数投票                           │
│  共识 ≥ 60%: 直接采纳                             │
│  分裂时: LLM Judge 仲裁                           │
│  → 最终预测答案                                   │
└────────────────────┬────────────────────────────┘
                     │
                     ▼
                输出答案
```

### 反思 + 进化流程（独立触发）

```
预测结果 + 正确答案
        │
        ▼
┌─ Reflector ─────────────────────────────────────┐
│  读 IST L1 digest (300 tokens，非原始 log)        │
│  LLM 分析: 为什么对/为什么错                       │
│  输出 Experience: lesson + failure_pattern         │
│  → ExperienceStore (本地 + OpenViking)            │
└────────────────────┬────────────────────────────┘
                     │
                     ▼
┌─ EE (Evolution Engine) ─────────────────────────┐
│  对每个岛:                                        │
│  ├── Refine: 基于胜率 + experience → 微调策略      │
│  ├── Diverge: 生成多样化新策略                     │
│  └── 淘汰: 确定性拥挤替换最弱策略                  │
│                                                    │
│  跨岛迁移: 环形拓扑 0→1→2→3→4→0                   │
│  动态开岛: 所有岛对某题型都弱 → LLM 创建新岛       │
└─────────────────────────────────────────────────┘
```

---

## 3. 模块架构

| 模块 | 代号 | 文件 | 功能 |
|------|------|------|------|
| Question Parser | QP | `question_parser.py` + `strategy_compiler.py` + `seed_strategies.py` | 解析题目 → 8 维策略定义 → prompt 编译 |
| Strategy Island | SI | `strategy_island.py` | 策略岛管理、采样、淘汰、持久化 |
| Evolution Engine | EE | `evolution_engine.py` | Refine/Diverge/Spawn/Migration |
| Weighted Voting | WV | `weighted_voting.py` | 加权投票 + LLM Judge |
| Inline Step Trace | IST | `inline_step_trace.py` | 运行时追踪 → 97% token 压缩 |
| Reflector | — | `evolving/reflector.py` | 反思 → 结构化经验 |
| ExperienceStore | — | `evolving/experience_store.py` | 经验存储 + 语义检索 |
| OpenViking | — | `openviking_context.py` + `viking_storage.py` | 远程存储 (write-through + 语义搜索) |
| Multi-Path Pipeline | — | `multi_path.py` | 主 pipeline，串联所有模块 |

---

## 4. 数据流总览

```
                    ┌─────────────────┐
                    │   ExperienceStore │◄── Reflector 写入
                    │ (本地+OpenViking) │──► 注入 agent prompt
                    └────────┬────────┘    ──► EE refine 参考
                             │
     ┌───────────────────────┼───────────────────────┐
     │                       │                       │
     ▼                       ▼                       ▼
┌─────────┐           ┌──────────┐           ┌──────────┐
│ IslandPool│           │DigestStore│           │ResultStore│
│ 策略岛池  │           │ IST 摘要  │           │ 任务战绩  │
│ (本地+OV) │           │ (本地+OV) │           │ (本地+OV) │
└─────────┘           └──────────┘           └──────────┘
     │                       │                       │
     │    ┌──────────────────┼───────────────────┐   │
     ▼    ▼                  ▼                   ▼   ▼
┌──────────────────────────────────────────────────────┐
│              multi_path.py (主 pipeline)               │
│  QP 解析 → 岛采样 → 5路径并行 → IST留痕 → 加权投票    │
└──────────────────────────────────────────────────────┘
```

---

## 5. Strategy Evolve Master 改动记录

### 背景

`docs/design/STRATEGY_EVOLVE_MASTER.md` 是策略进化系统的总纲文档，定义了 5 个子模块的架构、依赖关系和实施路径。以下是从规划到实现的完整改动。

### 5.1 已完成（全部子模块代码实现）

| Phase | 模块 | 改动内容 | 状态 |
|-------|------|---------|------|
| Phase 1 | **QP** | 数据结构层 + 解析层 + 编译层 + 集成层 + 测试 (45 项 ✅) | 完成 |
| Phase 2 | **SI** | IslandConfig + StrategyIsland + IslandPool + 存储 + 集成 + 测试 (50 项 ✅) | 完成 |
| Phase 3 | **EE** | EvolutionConfig + DirectionGenerator + IslandEvolver + 测试 (44 项 ✅) | 完成 |
| Phase 4 | **WV** | StrategyMetrics + weighted_vote + LLM Judge + 测试 (47 项 ✅) | 完成 |
| Phase 5 | **IST** | TracingToolWrapper + StepTraceCollector + DigestStore + 测试 (47 项 ✅) | 完成 |
| Phase 6 | **集成层** | 所有模块串联进 multi_path.py + reflector.py 改造 | 完成 |

### 5.2 架构层面的关键改动

1. **做题与进化分离** — `execute_multi_path_pipeline()` 只负责做题和投票。反思 + 进化抽到独立的 `reflect_and_evolve()` 函数，可单独触发。

2. **Reflector → EE 打通** — EE 的 Refine 操作从 ExperienceStore 查询相关失败经验，注入到进化 prompt 里。数据流：IST digest → Reflector → ExperienceStore → EE Refine。

3. **OpenViking 全量接入** — 所有 Store（Experience、Island、Digest、Result）支持 write-through 到 OpenViking + 语义搜索读取。使用后台守护线程处理异步写入。

4. **Feature Flag 控制** — 所有新模块通过 `question_parser.enabled` 开关控制。关闭时 pipeline 行为与改动前完全一致。

### 5.3 与原始规划的差异

| 原始规划 | 实际实现 | 原因 |
|---------|---------|------|
| OpenViking 后端 (P2) | 已实现（write-through + 语义搜索） | 提前做了 |
| IST 在 Phase 2 集成 | 独立 Phase 5 实现 + Phase 6 集成 | 解耦更清晰 |
| EE 在做题后自动触发 | 分离为独立函数，可手动触发 | 灵活性更好 |
| Reflector 和 EE 独立 | 已打通（experience → refine prompt） | 进化质量更高 |

### 5.4 测试覆盖

| 基线 | 当前 | 新增 |
|------|------|------|
| 484 | 820 | +336 |

全部 820 测试通过，零回归。

### 5.5 跳过的项目 (⏭️)

- QP-411/412: 需要真实 LLM 的集成测试
- SI-302, SI-525: OpenViking P2 后端（已在后续 PR 中实现）
- IST-203: OpenViking 后端（已实现）
- IST-415~419: 需要真实执行环境的性能测试

---

## 6. 当前状态

- **分支**: `feature/strategy-evolve`
- **测试**: 820 通过
- **冷启动基线**: cat10 10 道题，单路径 50%，多路径 20%（无历史数据/进化）
- **历史最佳**: 同 10 道题 90%（经过多轮进化后）
- **下一步**: 分析冷启动性能下降原因，优化种子策略和投票机制
