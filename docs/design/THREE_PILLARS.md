# EvoAgent 三大支柱：MiroThinker × SkyDiscover × OpenViking

> **文档日期**: 2026-03-17  
> **核心命题**: EvoAgent 不是从零开始的项目，而是将三个已有系统的核心能力提取、融合后的产物。

---

## 总览

```
┌─────────────────────────────────────────────────────────────────┐
│                         EvoAgent                                │
│                "会进化的预测 Agent"                               │
├──────────────────┬──────────────────┬──────────────────────────┤
│   MiroThinker    │   SkyDiscover    │      OpenViking          │
│   🧠 执行引擎     │   🧬 进化方法论   │      💾 记忆基础设施       │
│                  │                  │                          │
│  "怎么执行任务"   │  "怎么越做越好"   │    "怎么记住经验"          │
└──────────────────┴──────────────────┴──────────────────────────┘
```

---

## 1. MiroThinker — 执行引擎 🧠

### 是什么

MiroThinker 是 EvoAgent fork 出来的**底层 Agent 框架**。它提供了一个完整的、可运行的 Research Agent：能接收任务、调用搜索工具、读取网页、执行代码、输出答案。

### 核心能力

| 能力 | 说明 |
|------|------|
| **ReAct 循环** | LLM 思考 → 调用工具 → 观察结果 → 继续思考，直到得出答案 |
| **搜索工具链** | Google/DuckDuckGo/SerpAPI 搜索 + 网页抓取 + 结果过滤 |
| **Python 沙箱** | 本地 subprocess 执行代码（数据处理、计算验证） |
| **网页阅读** | 抓取并解析网页内容，提取关键信息 |
| **Orchestrator** | 编排器管理 Agent 的完整生命周期（初始化→执行→输出） |
| **Benchmark Runner** | 标准化评测流程（加载题目→执行→评分→汇总） |
| **Hydra 配置** | 灵活的 YAML 配置体系（LLM 选择、工具配置、运行参数） |

### 在 EvoAgent 中的角色

MiroThinker 是**每条探索路径内部的执行单元**。无论 EvoAgent 开了几条并行路径，每条路径内部跑的都是一个完整的 MiroThinker Agent。

```
EvoAgent 多路径调度器
    │
    ├── Path-α → [MiroThinker Agent + 策略A]
    ├── Path-β → [MiroThinker Agent + 策略B]
    └── Path-γ → [MiroThinker Agent + 策略C]
```

### 改造点

EvoAgent 对 MiroThinker 的改造主要集中在**外围**，核心 ReAct 循环基本未动：

| 改造 | 内容 |
|------|------|
| 策略注入 | 在 system prompt 末尾追加策略指令（`prompt_suffix`） |
| 独立实例化 | 每条路径拥有独立的 ToolManager，避免状态冲突 |
| 预算控制 | 不同路径分配不同的 `max_turns` |
| 搜索工具替换 | Serper → DuckDuckGo → SerpAPI（Baidu），按需切换 |
| before_date 注入 | ToolManager 自动在搜索 API 中注入时间截止参数，防止数据泄漏 |

---

## 2. SkyDiscover — 进化方法论 🧬

### 是什么

SkyDiscover 是一个**代码进化框架**，通过多路径探索和进化算法来自动发现更好的解决方案。它的核心理念是：与其让人类设计固定的解题策略，不如让系统自己探索、竞争、进化出最优策略。

### 核心理念

| 理念 | 说明 |
|------|------|
| **多路径并行** | 对同一问题启动多个不同策略的求解路径，而非只走一条 |
| **竞争选优** | 多个路径的结果互相竞争，选出最优解 |
| **策略进化** | 根据历史表现，淘汰差策略、强化好策略、生成新策略 |
| **代码即策略** | SkyDiscover 原版进化的是 solution code 本身 |

### EvoAgent 借鉴了什么

EvoAgent 没有照搬 SkyDiscover 的代码进化（太重），而是**借鉴了它的方法论**，并做了关键调整：

| SkyDiscover 原版 | EvoAgent 借鉴 | 差异 |
|------------------|--------------|------|
| 进化 solution code | 进化 prompt text（策略指令） | 更轻量，不需要代码编译/测试 |
| 代码变异/交叉 | LLM 生成新策略 + prompt 微调 | 用 LLM 替代遗传算子 |
| 多路径并行探索 | ✅ 直接采用 | 3 条并行路径（breadth/depth/lateral） |
| 适应度评估 | 投票 + Judge 评选 | 从代码通过率改为答案正确性 |
| 种群管理 | 策略池管理（活跃/观察/淘汰） | 概念一致，实现更简单 |
| 停滞检测 | ✅ 计划采用 | 策略胜率持续下降时触发进化 |

### 关键贡献

SkyDiscover 给 EvoAgent 的最大贡献是**架构思想**：

1. **多路径 > 单路径** — 即使同一个 LLM，用不同策略并行探索，正确率显著提升
2. **竞争出真知** — 路径之间的竞争比单路径的自我验证更可靠
3. **进化的闭环** — 执行 → 评估 → 进化 → 执行，形成持续改进循环
4. **动态策略调整** — 不是固定三条路径，而是根据任务类型和历史数据动态选择策略组合
5. **异构路径参数** — 不同策略用不同的搜索深度、工具偏好、验证轮次

### EvoAgent 中体现 SkyDiscover 思想的模块

| 模块 | SkyDiscover 思想 |
|------|-----------------|
| EA-001 多路径调度器 | 多路径并行探索 |
| EA-002 策略变体 | 异构策略（类似种群多样性） |
| EA-003 LLM 投票 | 竞争选优 |
| EA-009 早停机制 | 共识即停（类似提前收敛） |
| EA-104 自适应选择 | Exploit/Explore 平衡（类似 bandit） |
| EA-106 淘汰机制 | 适应度淘汰 |
| EA-201 策略生成 | 元进化（用 LLM 替代遗传算子） |

---

## 3. OpenViking — 记忆基础设施 💾

### 是什么

OpenViking 是字节跳动（火山引擎）开源的 **AI Agent 上下文数据库**，采用"文件系统范式"（`viking://` URI）统一管理 Agent 的记忆、资源和技能。

### 核心能力

| 能力 | 说明 |
|------|------|
| **文件系统范式** | 用 `viking://agent/memories/` 这样的路径统一管理所有 Agent 数据 |
| **分层加载 (L0/L1/L2)** | L0 摘要 (~100 token)、L1 概览 (~2k token)、L2 完整数据（按需），精确控制 token 成本 |
| **目录递归检索** | 自动检索子目录，支持模糊匹配和语义搜索 |
| **记忆自迭代** | 会话结束后自动提取长期记忆，无需额外调度 |
| **跨会话持久化** | 记忆在 Agent 重启后仍然存在 |

### 为什么需要 OpenViking

EvoAgent 的进化系统需要一个**跨任务的持久记忆层**。没有它，每次执行都是从零开始：

| 没有 OpenViking | 有 OpenViking |
|----------------|---------------|
| 每次任务随机选策略 | 根据历史画像选最优策略 |
| 犯过的错重复犯 | 经验库避免重复错误 |
| 策略无法积累胜率 | 战绩持久化，支持统计分析 |
| 路径间不能共享发现 | `viking://resources/discoveries/` 跨路径共享 |
| token 消耗无法优化 | L0/L1/L2 分层加载精准控制成本 |

### 在 EvoAgent 中的角色

OpenViking 是整个进化系统的**唯一存储后端**（设计决策 DD-006）：

```
viking://
├── agent/
│   ├── memories/
│   │   ├── strategy_results/     ← 每次任务的策略战绩
│   │   ├── strategy_profiles/    ← 聚合后的策略画像（胜率/擅长/弱点）
│   │   └── learnings/            ← 从失败中提取的经验
│   ├── skills/
│   │   └── strategies/           ← 策略种群（内置 + 进化生成）
│   └── instructions/
│       └── selection_rules/      ← 任务→策略的映射规则
└── resources/
    ├── discoveries/              ← 跨路径共享的中间发现
    └── task_taxonomy/            ← 任务分类体系
```

### 关键设计：记忆自迭代作为进化心跳

OpenViking 最巧妙的借鉴是用它的 **memory self-iteration** 机制驱动进化循环（DD-008）：

```
每次任务结束 → 写入战绩 (strategy_results/)
                  │
                  ▼ (积累 N 次后)
        trigger_memory_iteration()    ← OpenViking 自迭代
                  │
                  ├── 聚合战绩 → 更新策略画像
                  ├── 分析失败 → 提取经验
                  ├── 更新选择规则
                  └── 检测进化信号 → 触发新策略生成
```

不需要额外写一个调度器来驱动进化——OpenViking 本身的自迭代机制就是心跳。

### Fallback 模式

考虑到 OpenViking Server 部署有复杂度，EvoAgent 实现了 fallback 模式：
- **有 Server**: 完整功能（向量检索、自动迭代、跨路径共享）
- **无 Server**: 降级为本地 JSON 文件存储（丢失语义搜索，保留基本读写）

---

## 4. 三者如何融合

### 融合架构

```
                    ┌────────────────────────────────────┐
                    │         EvoAgent Controller        │
                    │                                    │
                    │  ┌──────────┐    ┌──────────────┐  │
                    │  │ 任务分类  │    │ 策略选择      │  │
                    │  │ (EA-103) │───▶│ (EA-104)     │  │
                    │  └──────────┘    └──────┬───────┘  │
                    │                         │          │
                    └─────────────────────────┼──────────┘
                                              │
                    ┌─────────────────────────┼──────────────────────┐
                    │                         │                      │
              ┌─────▼──────┐          ┌───────▼──────┐       ┌──────▼───────┐
              │  Path-α    │          │   Path-β     │       │  Path-γ      │
              │            │          │              │       │              │
              │ MiroThinker│          │ MiroThinker  │       │ MiroThinker  │
              │ + 策略A     │          │ + 策略B      │       │ + 策略C      │
              │ (ReAct)    │          │ (ReAct)      │       │ (ReAct)      │
              └─────┬──────┘          └──────┬───────┘       └──────┬───────┘
                    │                        │                      │
                    └────────────────────────┼──────────────────────┘
                                             │
                    ┌────────────────────────▼─────────────────────┐
                    │              投票 / Judge 评选                │
                    │         (SkyDiscover 竞争选优思想)             │
                    └────────────────────────┬─────────────────────┘
                                             │
                    ┌────────────────────────▼─────────────────────┐
                    │           OpenViking 存储层                   │
                    │                                              │
                    │  写入战绩 → 聚合画像 → 提取经验 → 更新规则     │
                    │                                              │
                    │  (记忆自迭代驱动进化闭环)                      │
                    └──────────────────────────────────────────────┘
```

### 每个系统解决什么问题

| 问题 | 解决者 | 怎么解决 |
|------|--------|---------|
| Agent 怎么搜索、阅读、计算？ | **MiroThinker** | ReAct 循环 + 工具链 |
| 一条路径不够怎么办？ | **SkyDiscover** | 多路径并行 + 竞争选优 |
| 怎么从多个答案里选最好的？ | **SkyDiscover** | 多数投票 + LLM Judge |
| 做过的事怎么记住？ | **OpenViking** | 文件系统范式 + 持久化存储 |
| 怎么根据历史选策略？ | **OpenViking** + **SkyDiscover** | L0 快速加载画像 + Exploit/Explore 选择 |
| 怎么从失败中学习？ | **OpenViking** | 经验库 + 三层晋升机制 |
| 怎么自动生成新策略？ | **SkyDiscover** | 进化信号检测 + LLM 策略生成 |
| token 成本怎么控制？ | **OpenViking** | L0/L1/L2 分层加载 |
| 怎么防止进化过拟合？ | **SkyDiscover** | Explore 机制强制尝试新策略 |

### 融合的关键设计决策

| 编号 | 决策 | 来源 | 理由 |
|------|------|------|------|
| DD-001 | 策略通过 prompt suffix 注入 | MiroThinker | 最小侵入性，不改核心 ReAct |
| DD-003 | 多数投票 + LLM Judge 兜底 | SkyDiscover | 零成本快速路径 + 高质量兜底 |
| DD-006 | OpenViking 作为唯一存储层 | OpenViking | 统一存储避免数据碎片化 |
| DD-007 | 竞争进化 + 经验进化双驱动 | SkyDiscover + OpenViking | "谁赢了" + "为什么赢" 互补 |
| DD-008 | 记忆自迭代作为进化心跳 | OpenViking | 不需额外调度器 |
| DD-009 | Exploit + Explore 策略选择 | SkyDiscover | Multi-Armed Bandit 避免局部最优 |

### 一次完整的任务执行流程

```
1. [接收任务]
   │
2. [OpenViking L0] 加载策略摘要 (~100 token)
   │ "breadth_first 胜率 72%, depth_first 胜率 65%, lateral 胜率 58%"
   │
3. [SkyDiscover 思想] EA-104 选择策略组合
   │ Exploit: breadth_first + depth_first
   │ Explore: 新生成的 evolved_001
   │
4. [MiroThinker ×3] 三条路径并行执行
   │ Path-α: breadth_first → 广泛搜索多源 → 答案 A
   │ Path-β: depth_first → 深入一个权威源 → 答案 B  
   │ Path-γ: evolved_001 → 新策略尝试 → 答案 C
   │
5. [SkyDiscover 思想] 投票评选
   │ A == B ≠ C → 多数投票选 A (= B)
   │
6. [OpenViking] 写入战绩
   │ breadth_first: WIN, depth_first: WIN, evolved_001: LOSE
   │
7. [OpenViking 自迭代] 周期性触发
   │ → 更新策略画像
   │ → evolved_001 胜率太低 → 标记观察期
   │ → 提取经验: "evolved_001 在搜索型任务中搜索范围过窄"
   │
8. [下一次任务] 回到步骤 1，但策略选择已经更新
```

---

## 5. 当前实现状态

| 层面 | 来源 | 状态 | 说明 |
|------|------|------|------|
| ReAct 执行引擎 | MiroThinker | ✅ 完成 | 完整的搜索/阅读/计算能力 |
| 多路径并行 | SkyDiscover | ✅ 完成 | 3 路径 + 早停 + 重试 |
| 投票评选 | SkyDiscover | ✅ 完成 | 多数投票 + LLM Judge |
| OpenViking 集成 | OpenViking | ✅ 基础完成 | fallback 模式可用，Server 未部署 |
| 经验进化 (Reflector) | SkyDiscover + OpenViking | ✅ 初版完成 | evaluate → reflect → evolve 链路已有，但完整流程未跑通 |
| 策略画像 | SkyDiscover + OpenViking | ❌ 待开发 | EA-102 |
| 自适应策略选择 | SkyDiscover | ❌ 待开发 | EA-104 |
| 元进化 (新策略生成) | SkyDiscover | ❌ 待开发 | EA-201 |
| L0/L1/L2 分层加载 | OpenViking | ❌ 待开发 | 需要 Server 部署 |

### 实验验证

| 轮次 | 配置 | 准确率 | 核心变量 |
|------|------|--------|---------|
| R1 (noevolve) | MiroThinker 多路径，无经验 | 4/10 (40%) | 基线 |
| R2 (evolved) | MiroThinker 多路径 + 经验注入 | 9/10 (90%) | +Reflector 经验 |
| R3 (evolved) | 同 R2，验证稳定性 | 进行中 | 复现性 |

R1→R2 的提升证明了**经验进化**（SkyDiscover 思想 + OpenViking 存储）的有效性。

---

## 6. 一句话总结

> **MiroThinker 负责干活，SkyDiscover 负责让它越干越好，OpenViking 负责把经验记下来。**
