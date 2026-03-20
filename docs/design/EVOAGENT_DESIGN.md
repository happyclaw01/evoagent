# EvoAgent 设计文档

> **项目代号**: EvoAgent  
> **基线项目**: MiroThinker v1.0  
> **核心理念**: 将进化搜索方法论应用于 Research Agent，通过多路径探索和策略进化超越单链路 ReAct 循环  
> **分支**: `main`  
> **创建日期**: 2026-03-13  
> **最后更新**: 2026-03-14  
> **设计参考**: Self-Improving Agent (ClawHub: pskoett/self-improving-agent), OpenViking (volcengine), 谢一凡硕士论文 (SJTU, 2025)
> **研究日志**: `docs/research-log/` (记录设计思考过程，为论文写作积累素材)

---

## 1. 架构总览

```
┌──────────────────────────────────────────────────────────────────┐
│                      EvoAgent Controller                         │
│                    (EA-CTL: 进化调度中心)                          │
│                                                                  │
│  ┌─────────┐  ┌─────────────┐  ┌──────────┐  ┌───────────────┐  │
│  │ EA-POOL │  │ EA-STRATEGY │  │ EA-VOTE  │  │  EA-EVOLVE    │  │
│  │ 路径池   │  │ 策略管理     │  │ 投票评选  │  │ 策略进化引擎   │  │
│  └─────────┘  └─────────────┘  └──────────┘  └───────────────┘  │
└──────────────────────────┬───────────────────────────────────────┘
                           │
          ┌────────────────┼────────────────┐
          │                │                │
    ┌─────▼─────┐   ┌─────▼─────┐   ┌─────▼─────┐
    │  Path-α   │   │  Path-β   │   │  Path-γ   │
    │ (Agent)   │   │ (Agent)   │   │ (Agent)   │
    │ + 策略注入 │   │ + 策略注入 │   │ + 策略注入 │
    └─────┬─────┘   └─────┬─────┘   └─────┬─────┘
          │                │                │
          └────────────────┼────────────────┘
                           │
              ┌────────────▼────────────┐
              │   EA-307 OpenViking     │
              │   上下文存储层           │
              ├─────────────────────────┤
              │ viking://agent/         │
              │   memories/             │
              │     strategy_results/   │ ← EA-101 战绩记录
              │     strategy_profiles/  │ ← EA-102 策略画像
              │     learnings/          │ ← EA-108 经验提取
              │   skills/strategies/    │ ← EA-107 策略种群
              │   instructions/         │ ← EA-104 选择规则
              │ viking://resources/     │
              │   discoveries/          │ ← EA-307.4 跨路径共享
              │   task_taxonomy/        │ ← EA-103 任务分类
              └─────────────────────────┘
```

---

## 2. 进化双引擎架构

EvoAgent 的进化系统融合两种范式：

```
    竞争进化 (原有)                经验进化 (Self-Improving 借鉴)
    ┌─────────────┐              ┌──────────────────┐
    │ 多路径并行    │              │ 分析为什么赢/输    │
    │ 投票选出赢家  │              │ 记录失败模式       │
    │ "谁赢了？"   │              │ 提取成功模式       │
    └──────┬──────┘              │ "为什么赢了？"     │
           │                     └────────┬─────────┘
           └──────────┬──────────────────┘
                      ▼
             知识固化 (OpenViking L0/L1/L2)
             ┌──────────────────┐
             │ L0: 快速决策      │  ~100 tokens
             │ L1: 策略画像      │  ~2k tokens
             │ L2: 完整证据      │  按需加载
             │ "下次怎么选？"    │
             └──────────────────┘
```

| 进化层 | 问题 | 数据来源 | 存储层 |
|--------|------|---------|--------|
| 竞争进化 | 谁赢了 | 投票结果 | EA-307 `strategy_results/` |
| 经验进化 | 为什么赢 | 执行日志分析 | EA-307 `learnings/` |
| 知识固化 | 下次怎么选 | 聚合统计 | EA-307 `strategy_profiles/` |

---

## 3. 功能清单与编号

### 3.1 第一层：多路径并行探索（Run-time） ✅ 100%

| 编号 | 功能名称 | 描述 | 状态 | 优先级 |
|------|---------|------|------|--------|
| **EA-001** | 多路径调度器 | 对同一任务启动 N 条并行 Agent 路径，每条使用不同策略 | ✅ 已实现 | P0 |
| **EA-002** | 策略变体定义 | 定义可插拔的策略模板（breadth_first / depth_first / lateral_thinking） | ✅ 已实现 | P0 |
| **EA-003** | LLM 投票评选 | 多路径结果不一致时，用 LLM Judge 选出最优答案 | ✅ 已实现 | P0 |
| **EA-004** | 多数投票快速路径 | 多路径结果一致时，跳过 LLM Judge，直接采用多数答案 | ✅ 已实现 | P0 |
| **EA-005** | 独立工具管理器 | 每条路径拥有独立的 ToolManager 实例，避免状态冲突 | ✅ 已实现 | P0 |
| **EA-006** | 路径级日志隔离 | 每条路径生成独立的 TaskLog，支持单独审查和对比分析 | ✅ 已实现 | P1 |
| **EA-007** | 主控日志聚合 | 主调度器汇总所有路径结果、投票过程、最终选择到 master log | ✅ 已实现 | P1 |
| **EA-008** | 路径数动态配置 | 通过环境变量 `NUM_PATHS` 或配置文件控制并行路径数 | ✅ 已实现 | P1 |
| **EA-009** | 早停机制 | 当前 K 条路径达成共识时，取消剩余路径以节省成本 | ✅ 已实现 | P1 |
| **EA-010** | 路径预算分配 | 不同策略分配不同的 max_turns 预算（如广搜少、深搜多） | ✅ 已实现 | P2 |
| **EA-011** | 异步流式输出 | 各路径的中间思考过程实时流式输出到前端 | ✅ 已实现 | P2 |
| **EA-012** | 路径失败重试 | 路径因 API 错误等原因失败时，自动用备选策略重启 | ✅ 已实现 | P2 |

### 3.2 第二层：跨任务策略进化（Cross-task）— 重新设计

> **设计原则**: 竞争进化 + 经验进化双驱动，EA-307 (OpenViking) 作为唯一存储层。
> **设计参考**: Self-Improving Agent (pskoett/self-improving-agent)

| 编号 | 功能名称 | 描述 | 存储位置 | 状态 | 优先级 |
|------|---------|------|---------|------|--------|
| **EA-101** | 策略战绩记录器 | 每次任务结束后记录 `{策略, 任务类型, 是否获胜, turns, cost, 失败原因}` | `viking://agent/memories/strategy_results/` | ❌ 待开发 | P1 |
| **EA-102** | 策略画像引擎 | 聚合历史战绩 → 生成策略效果画像 (胜率/擅长任务/弱点/平均cost) | `viking://agent/memories/strategy_profiles/` | ❌ 待开发 | P1 |
| **EA-103** | 任务分类器 | 自动判断任务类型 (search/compute/creative/verify/multi-hop) | `viking://resources/task_taxonomy/` | ❌ 待开发 | P1 |
| **EA-104** | 自适应策略选择 | 根据任务类型 + 策略画像，动态选择最优策略组合 (Exploit + Explore) | `viking://agent/instructions/selection_rules/` | ❌ 待开发 | P1 |
| **EA-105** | 策略参数微调 | 基于历史数据微调 max_turns / prompt_suffix 等参数 | `viking://agent/skills/strategies/` | ❌ 待开发 | P2 |
| **EA-106** | 策略淘汰机制 | 胜率 < 阈值 且样本 ≥ N → 标记淘汰；支持复活机制 | `viking://agent/memories/strategy_profiles/` | ❌ 待开发 | P2 |
| **EA-107** | 策略种群管理 | 维护活跃策略池 = 内置策略 + 进化策略 + 用户自定义策略 | `viking://agent/skills/strategies/` | ❌ 待开发 | P2 |
| **EA-108** | 经验提取器 | 从执行日志中提取 learnings (失败模式/成功模式/最佳实践) | `viking://agent/memories/learnings/` | ❌ 待开发 | P2 |

### 3.3 第三层：元进化（Meta-evolution）— 重新设计

> **设计原则**: 当 EA-307.5 记忆自迭代检测到进化信号时触发。

| 编号 | 功能名称 | 描述 | 触发条件 | 状态 | 优先级 |
|------|---------|------|---------|------|--------|
| **EA-201** | LLM 策略生成器 | 用 LLM 生成全新搜索策略 (name + prompt_suffix + max_turns) | 空白区域 / 失败模式 ≥ 3 次 / 策略退化 | ❌ 待开发 | P3 |
| **EA-202** | 策略代码进化 | 将策略表示为可执行代码而非纯 prompt，支持代码级进化 | 策略 prompt 优化饱和 | ❌ 待开发 | P3 |
| **EA-203** | 跨维度自适应 | 自动调整 "路径数 × 深度 × 多样性" 的最优组合 | 积累 ≥ 100 任务数据 | ❌ 待开发 | P3 |

### 3.4 基础设施 / 工具改造 ✅ 100%

| 编号 | 功能名称 | 描述 | 状态 | 优先级 |
|------|---------|------|------|--------|
| **EA-301** | 本地 Python 沙箱 | 替代 E2B 云沙箱，使用本地 subprocess 执行代码 | ✅ 已实现 | P0 |
| **EA-302** | DuckDuckGo 搜索替代 | 替代 Serper API，使用免费 DuckDuckGo 搜索 | ✅ 已实现 | P0 |
| **EA-303** | OpenRouter LLM 配置 | 支持 OpenRouter 多模型路由 | ✅ 已实现 | P0 |
| **EA-304** | 成本追踪器 | 记录每条路径的 token 消耗和 API 成本，用于成本优化决策 | ✅ 已实现 | P1 |
| **EA-305** | 路径间通信总线 | 允许路径间共享中间发现，避免重复工作 | 🔄 通过 EA-307 实现 | P2 |
| **EA-306** | 结果缓存层 | 工具调用结果缓存，同一 URL/查询在不同路径中复用结果 | 🔄 通过 EA-307 实现 | P2 |
| **EA-307** | OpenViking 集成 | 上下文存储层：分层加载 / 目录检索 / 记忆自迭代 / 跨路径共享 | ✅ 已实现 | P1 |

### 3.5 测试与评估

| 编号 | 功能名称 | 描述 | 状态 | 优先级 |
|------|---------|------|------|--------|
| **EA-401** | 单元测试 - 多路径调度 | 测试 N 条路径正确并发启动和结果收集 | ✅ 已实现 | P0 |
| **EA-402** | 单元测试 - 投票机制 | 测试多数投票和 LLM Judge 的正确性 | ✅ 已实现 | P0 |
| **EA-403** | 单元测试 - 策略注入 | 测试不同策略正确注入到 system prompt | ✅ 已实现 | P0 |
| **EA-404** | 集成测试 - 端到端 | 使用真实 API 运行完整多路径流程 | ❌ 待开发 | P1 |
| **EA-405** | 基准对比测试 | 在 GAIA/HLE 子集上对比单路径 vs 多路径的正确率 | ❌ 待开发 | P1 |
| **EA-406** | 成本效益分析 | 对比不同路径数（1/2/3/5）的正确率与成本比 | ❌ 待开发 | P2 |
| **EA-407** | 策略消融实验 | 单独测试每个策略变体的独立贡献 | ❌ 待开发 | P2 |
| **EA-408** | 持续预测引擎 | 多路径初始预测 + 滚动更新，产生完整预测轨迹 | ✅ 已实现 | P1 |
| **EA-409** | 预测更新调度器 | 按时间间隔或突发事件触发预测更新，自适应调频 | ✅ 已实现 | P1 |
| **EA-410** | 预测验证与轨迹分析 | 对比预测vs实际，分析更新轨迹收敛/发散，提取经验 | ✅ 已实现 | P1 |

---

## 4. EA-307 驱动的进化数据架构

### 4.1 OpenViking 目录结构

```
viking://
├── agent/
│   ├── memories/
│   │   ├── strategy_results/              ← EA-101: 原始战绩
│   │   │   ├── .abstract                   L0: "共执行 150 次, breadth_first 胜率 72%"
│   │   │   ├── .overview                   L1: 按任务类型的胜率矩阵
│   │   │   ├── task_20260314_001.json       L2: 完整执行记录
│   │   │   └── task_20260314_002.json
│   │   │
│   │   ├── strategy_profiles/             ← EA-102: 策略画像
│   │   │   ├── .abstract                   L0: "4 个活跃策略, 1 个待淘汰"
│   │   │   ├── breadth_first.json          L1: 完整画像
│   │   │   ├── depth_first.json
│   │   │   ├── lateral_thinking.json
│   │   │   └── verification_heavy.json
│   │   │
│   │   └── learnings/                     ← EA-108: 经验库
│   │       ├── LEARNINGS.md                结构化学习记录
│   │       └── ERRORS.md                   失败模式记录
│   │
│   ├── skills/
│   │   └── strategies/                    ← EA-107: 策略种群
│   │       ├── breadth_first/              内置策略
│   │       │   └── strategy.json
│   │       ├── depth_first/
│   │       ├── lateral_thinking/
│   │       ├── verification_heavy/
│   │       └── evolved_001/                EA-201 生成的新策略
│   │           └── strategy.json
│   │
│   └── instructions/
│       └── selection_rules/               ← EA-104: 策略选择规则
│           └── task_strategy_map.json       "search → breadth_first, compute → depth_first"
│
└── resources/
    ├── discoveries/                       ← EA-307.4: 跨路径共享
    └── task_taxonomy/                     ← EA-103: 任务分类体系
        ├── .abstract                       L0: "5 种任务类型"
        └── taxonomy.json                   完整分类规则
```

### 4.2 分层加载策略 (Token 成本控制)

| 场景 | 加载层级 | Token 消耗 | 说明 |
|------|---------|-----------|------|
| 任务开始 → 选择策略 | L0 | ~100 | 只读 `.abstract` 快速获取胜率 |
| 策略选择需要细节 | L1 | ~2k | 读取策略画像判断适用性 |
| 经验分析/策略生成 | L2 | 按需 | 完整执行日志用于深度分析 |
| EA-307.5 自迭代 | L1 | ~2k/策略 | 定期聚合更新画像 |

---

## 5. 进化引擎：EA-307.5 自迭代流程

`trigger_memory_iteration()` 是整个进化系统的 **心跳**。

```
每次任务结束
    │
    ▼ EA-101: 记录原始结果
    │  save_strategy_result() → strategy_results/task_xxx.json
    │
    ▼ (积累 N 次后触发自迭代)
    │
trigger_memory_iteration()
    │
    ├── Step 1: 聚合统计 (EA-102)
    │   读取 strategy_results/*.json
    │   → 更新 strategy_profiles/*.json
    │   "breadth_first: 最近20次胜率70%, 平均cost $0.018, 擅长search型"
    │
    ├── Step 2: 分类归纳 (EA-103)
    │   分析任务描述 → 更新 task_taxonomy/taxonomy.json
    │   "搜索型(42%), 计算型(23%), 创意型(15%), 验证型(12%), 多跳(8%)"
    │
    ├── Step 3: 提取经验 (EA-108, Self-Improving)
    │   从失败案例中提取 learnings
    │   → 追加到 learnings/LEARNINGS.md
    │   "[LRN-20260314-001] breadth_first 在精确数值任务中频繁失败"
    │   "[LRN-20260314-002] lateral_thinking 在常规搜索失败时有奇效"
    │
    ├── Step 4: 更新选择规则 (EA-104)
    │   基于画像 + 经验 → 更新 selection_rules/task_strategy_map.json
    │   {
    │     "search": ["breadth_first", "lateral_thinking"],
    │     "compute": ["depth_first", "verification_heavy"],
    │     "creative": ["lateral_thinking", "breadth_first"]
    │   }
    │
    ├── Step 5: 检查晋升/淘汰 (EA-106)
    │   if 胜率 > 80% && N > 20 → 标记为 "首选"
    │   if 胜率 < 30% && N > 20 → 标记为 "待淘汰"
    │   if 新策略胜率 > 平均 → 晋升到正式策略池
    │
    └── Step 6: 检测进化信号 (EA-201)
        if 某任务类型所有策略胜率 < 50% → 触发新策略生成
        if learnings 中同类失败 ≥ 3 → 触发修正型策略
        if 某策略近期胜率持续下降 → 触发替代策略
```

---

## 6. EA-104 自适应策略选择算法

### 6.1 从静态选择到动态选择

```python
# === 当前实现 (静态) ===
strategies = STRATEGY_VARIANTS[:num_paths]

# === 重新设计 (自适应) ===
async def select_strategies(
    task: str, 
    num_paths: int, 
    ov_context: OpenVikingContext
) -> List[Dict]:
    """
    EA-104: Exploit + Explore 平衡的策略选择
    
    类似 Multi-Armed Bandit 问题：
    - Exploitation: 选择历史最优策略
    - Exploration: 给低频/新策略分配尝试机会
    """
    # 1. 任务分类 (EA-103) — 加载 L0 (~100 tokens)
    task_type = await classify_task(task, ov_context)
    
    # 2. 加载策略画像 (EA-102) — 加载 L0 (~100 tokens)
    rankings = await ov_context.get_strategy_rankings(task_type)
    
    # 3. 构建策略组合
    selected = []
    
    # 位置 1: 最优策略 (Exploit)
    if rankings:
        selected.append(rankings[0])
    else:
        selected.append(STRATEGY_VARIANTS[0])  # 冷启动默认
    
    # 位置 2: 次优或互补策略 (Exploit)
    if num_paths >= 2 and len(rankings) >= 2:
        selected.append(rankings[1])
    elif num_paths >= 2:
        selected.append(STRATEGY_VARIANTS[1])
    
    # 位置 3+: 探索性策略 (Explore)
    for i in range(2, num_paths):
        # 优先选择: 新生成的策略 > 低样本策略 > 随机
        evolved = await ov_context.get_untested_strategies(task_type)
        if evolved:
            selected.append(evolved[0])
        else:
            low_sample = await ov_context.get_low_sample_strategies(task_type)
            if low_sample:
                selected.append(low_sample[0])
            else:
                selected.append(random.choice(STRATEGY_VARIANTS))
    
    return selected
```

### 6.2 Explore/Exploit 比例

| 路径数 | Exploit 位置 | Explore 位置 | 说明 |
|--------|-------------|-------------|------|
| 2 | 1 | 1 | 50/50 平衡 |
| 3 | 2 | 1 | 67/33，偏向利用 |
| 4 | 2 | 2 | 50/50 平衡 |
| 5 | 3 | 2 | 60/40，偏向利用 |

---

## 7. EA-108 经验记录格式 (Self-Improving 借鉴)

### 7.1 Learning Entry 格式

```markdown
## [LRN-YYYYMMDD-XXX] category

**Logged**: ISO-8601 timestamp
**Priority**: low | medium | high | critical
**Status**: pending | resolved | promoted_to_rule | promoted_to_strategy
**Task Type**: search | compute | creative | verify | multi-hop

### Summary
一句话描述学到了什么

### Details
完整上下文: 发生了什么, 哪里出错, 什么是正确的

### Suggested Action
具体的改进建议

### Metadata
- Source: competition_result | error_analysis | user_feedback
- Strategy: breadth_first
- Win Rate Impact: -5% (estimated)
- Related: LRN-20260313-001
- Pattern-Key: strategy.breadth_fail_on_numeric
- Recurrence-Count: 3
```

### 7.2 Error Entry 格式

```markdown
## [ERR-YYYYMMDD-XXX] strategy_name

**Logged**: ISO-8601 timestamp
**Priority**: high
**Task Type**: compute

### Summary
breadth_first 在精确数值查询中返回近似值

### Error
Expected: "42.7 million" Got: "approximately 40 million"

### Root Cause
breadth_first 策略倾向于综合多源，导致精确值被平均化

### Strategy Impact
breadth_first 在 compute 型任务中胜率下降 15%
```

### 7.3 三层晋升机制

| 层级 | 存储 | 条件 | 动作 |
|------|------|------|------|
| **L1 记录** | `learnings/LEARNINGS.md` | 任何非平凡的执行发现 | 追加条目 |
| **L2 规则** | `selection_rules/task_strategy_map.json` | `Recurrence-Count ≥ 3` 且 `Status = resolved` | 更新选择规则 |
| **L3 策略** | `skills/strategies/evolved_xxx/` | 发现新模式 + LLM 验证可行 | 生成新策略 |

---

## 8. EA-201 元进化触发机制

### 8.1 触发信号

| 信号 | 检测方法 | 触发动作 |
|------|---------|---------|
| **空白区域** | 某任务类型所有策略胜率 < 50% | 生成针对性新策略 |
| **失败聚集** | `learnings/` 中同类 Pattern-Key ≥ 3 | 生成修正型策略 |
| **策略退化** | 某策略近 10 次胜率 vs 历史胜率下降 > 20% | 生成替代策略 |
| **用户覆盖** | 用户手动选择策略 ≥ 3 次 | 学习偏好生成策略 |
| **种群稀疏** | 活跃策略数 < 最低阈值 (3) | 变异/交叉生成新策略 |

### 8.2 LLM 策略生成流程

```python
async def generate_evolved_strategy(
    signal: str,
    context: List[ContextBlock],   # EA-307 提供的 L1/L2 上下文
    learnings: List[str],          # EA-108 提取的相关经验
    ov_context: OpenVikingContext
) -> Dict:
    """EA-201: 基于进化信号生成新策略"""
    
    prompt = f"""
    你是一个策略设计专家。根据以下信息设计一个新的 Agent 搜索策略。
    
    ## 触发信号
    {signal}
    
    ## 历史经验
    {learnings}
    
    ## 现有策略画像
    {context}
    
    ## 输出格式 (JSON)
    {{
        "name": "策略名称 (英文, 下划线分隔)",
        "description": "一句话描述",
        "prompt_suffix": "注入到 Agent 的详细策略指令 (200字以内)",
        "max_turns": 建议最大轮次 (50-300),
        "target_task_types": ["适用的任务类型"],
        "rationale": "设计理由"
    }}
    """
    
    # 生成 → 验证 → 写入策略种群
    strategy = await llm_generate(prompt)
    
    # 写入 viking://agent/skills/strategies/evolved_xxx/
    await ov_context.register_strategy(strategy)
    
    return strategy
```

---

## 9. 策略定义规范 (更新版)

```python
{
    "name": "strategy_unique_name",       # 策略唯一标识
    "description": "Human-readable description",
    "prompt_suffix": "...",               # 注入到 system prompt 末尾
    "max_turns": 100,                     # 最大轮次 (EA-010)
    "origin": "builtin | evolved | user", # 策略来源 (新增)
    "generation": 0,                      # 进化代数 (新增)
    "parent": null,                       # 父策略名称 (新增, 用于回溯)
    "target_task_types": [],              # 目标任务类型 (新增)
    "params": {                           # 可选参数 (EA-105)
        "search_breadth": 3,
        "tool_preference_order": [],
        "verification_rounds": 1,
    },
    "stats": {                            # 运行时统计 (新增)
        "total_runs": 0,
        "wins": 0,
        "win_rate": 0.0,
        "avg_cost_usd": 0.0,
        "avg_turns": 0,
        "status": "active",              # active | probation | retired
        "last_run": null,
    }
}
```

### 9.1 策略生命周期

```
      创建 (builtin / evolved / user)
         │
         ▼
    ┌──────────┐
    │  active   │ ← 正常参与选择
    └────┬─────┘
         │ 胜率 < 30% && N > 20
         ▼
    ┌──────────┐
    │ probation │ ← 观察期, 降低选择概率
    └────┬─────┘
         │ 连续 10 次败 || 有更优替代
         ▼
    ┌──────────┐
    │ retired   │ ← 不再参与选择, 保留历史记录
    └──────────┘
         │ 环境变化 / 用户复活
         ▼
    ┌──────────┐
    │ active    │ ← 复活机制
    └──────────┘
```

---

## 10. 预定义策略

| 策略名 | 编号 | 核心思路 | max_turns |
|--------|------|---------|-----------|
| `breadth_first` | STR-01 | 先广泛搜索多个来源，再交叉验证 | 100 |
| `depth_first` | STR-02 | 找到一个权威来源后深入挖掘 | 300 |
| `lateral_thinking` | STR-03 | 从侧面角度切入，利用代码计算辅助 | 200 |
| `verification_heavy` | STR-04 | 找到答案后用多种方式交叉验证 | 150 |

---

## 11. 数据流 (更新版)

```
输入任务
    │
    ▼
┌─────────────────────────────────┐
│ EA-CTL: 调度中心                 │
│                                 │
│ 1. 接收任务                      │
│ 2. EA-103: 任务分类 (L0 ~100t)  │
│ 3. EA-104: 策略选择 (L0 ~100t)  │
│ 4. EA-001: 分配路径              │
└──────────────┬──────────────────┘
               │
     ┌─────────┼─────────┐
     │         │         │
     ▼         ▼         ▼
   Path0     Path1     Path2
  (Exploit)  (Exploit)  (Explore)  ← EA-104 动态分配
     │         │         │
     ▼         ▼         ▼
   Ans0      Ans1      Ans2
     │         │         │
     └─────────┼─────────┘
               │
     ┌─────────▼─────────┐
     │ EA-003/004: 投票   │
     └─────────┬─────────┘
               │
     ┌─────────▼─────────────────────────┐
     │ 最终答案                           │
     └─────────┬─────────────────────────┘
               │
     ┌─────────▼─────────────────────────┐
     │ 进化记录 (写入 EA-307)              │
     │                                   │
     │ EA-101: 战绩 → strategy_results/  │
     │ EA-108: 经验 → learnings/          │
     │ EA-304: 成本 → cost_tracking/      │
     └─────────┬─────────────────────────┘
               │
     ┌─────────▼─────────────────────────┐
     │ EA-307.5: 自迭代 (周期性触发)       │
     │                                   │
     │ → EA-102: 更新策略画像             │
     │ → EA-103: 更新任务分类             │
     │ → EA-104: 更新选择规则             │
     │ → EA-106: 检查淘汰                │
     │ → EA-201: 检测进化信号             │
     └───────────────────────────────────┘
```

---

## 12. 文件结构 (更新版)

```
apps/miroflow-agent/
├── main.py                          # 原版单路径入口
├── main_multipath.py                # 多路径入口 (EA-001, EA-008)
├── conf/
│   ├── llm/openrouter-local.yaml    # OpenRouter 配置 (EA-303)
│   └── evoagent/                    # [待创建] EvoAgent 配置
│       ├── default.yaml             # 默认多路径配置
│       ├── strategies.yaml          # 内置策略定义
│       └── evolution.yaml           # 进化参数配置
├── src/
│   ├── core/
│   │   ├── orchestrator.py          # 原版编排器
│   │   ├── multi_path.py            # 多路径核心 (EA-001~012)
│   │   ├── pipeline.py              # 管道（含多路径入口）
│   │   ├── cost_tracker.py          # 成本追踪 (EA-304)
│   │   ├── streaming.py             # 流式输出 (EA-011)
│   │   └── openviking_context.py    # OpenViking 集成 (EA-307)
│   ├── evolving/                    # [待创建] 进化模块
│   │   ├── strategy_recorder.py     # EA-101 战绩记录
│   │   ├── strategy_profiler.py     # EA-102 画像引擎
│   │   ├── task_classifier.py       # EA-103 任务分类
│   │   ├── adaptive_selector.py     # EA-104 自适应选择
│   │   ├── strategy_tuner.py        # EA-105 参数微调
│   │   ├── strategy_lifecycle.py    # EA-106 淘汰/复活
│   │   ├── strategy_pool.py         # EA-107 种群管理
│   │   ├── experience_extractor.py  # EA-108 经验提取
│   │   └── strategy_generator.py    # EA-201 LLM 策略生成
│   └── tests/
│       ├── test_multi_path.py       # EA-001~008 测试
│       ├── test_early_stopping.py   # EA-009 测试
│       ├── test_path_budget.py      # EA-010 测试
│       ├── test_streaming.py        # EA-011 测试
│       ├── test_retry.py            # EA-012 测试
│       ├── test_cost_tracker.py     # EA-304 测试
│       ├── test_openviking.py       # EA-307 测试
│       ├── test_strategy_recorder.py    # [待创建] EA-101
│       ├── test_strategy_profiler.py    # [待创建] EA-102
│       ├── test_task_classifier.py      # [待创建] EA-103
│       ├── test_adaptive_selector.py    # [待创建] EA-104
│       └── test_experience_extractor.py # [待创建] EA-108
│
libs/miroflow-tools/src/miroflow_tools/
├── mcp_servers/
│   └── python_mcp_server_local.py   # 本地沙箱 (EA-301)
└── dev_mcp_servers/
    └── search_and_scrape_webpage_local.py  # DuckDuckGo 搜索 (EA-302)

docs/design/
├── EVOAGENT_DESIGN.md               # 本文档
├── OPENVIKING_INTEGRATION.md        # OpenViking 集成分析
├── CHANGELOG.md                     # 变更记录
└── TEST_REPORT.md                   # 测试报告
```

---

## 13. 开发路线图 (更新版)

### Phase 1: 基础多路径 ✅ 完成
- EA-001~012, EA-301~307
- 目标：验证多路径探索比单路径更优
- 测试：109 个单元测试通过

### Phase 2: 进化基础 (下一阶段)
- EA-101 (战绩记录) → EA-103 (任务分类) → EA-102 (画像引擎) → EA-108 (经验提取)
- 依赖：EA-307 (OpenViking) 作为存储后端
- 目标：积累进化数据，建立策略画像

### Phase 3: 自适应选择
- EA-104 (自适应选择) → EA-106 (淘汰机制) → EA-107 (种群管理) → EA-105 (参数微调)
- 依赖：Phase 2 积累的数据
- 目标：策略选择从静态变为动态

### Phase 4: 元进化（实验性）
- EA-201 (LLM 策略生成) → EA-203 (跨维度自适应) → EA-202 (代码进化)
- 依赖：Phase 3 的淘汰机制 + 进化信号检测
- 目标：探索自我进化的上限

### Phase 5: 评估与优化
- EA-404~407 (集成测试、基准对比、消融实验)
- 目标：量化进化效果

---

## 14. 已验证的测试结果

### 测试 1: arxiv 论文查询 (2026-03-13)

| 配置 | 答案 | 正确性 |
|------|------|--------|
| 单路径 (原版) | `{Not available}` | ❌ |
| 2路径 (breadth + depth) | 50篇论文标题列表 | ✅ |

- **depth_first** 成功抓取 `arxiv.org/list/cs/new` 并提取论文标题
- **LLM Judge** 正确选择了 depth_first 的答案
- Token 消耗：单路径 ~15K vs 多路径 ~85K（5.5倍）
- 耗时：单路径 ~87s vs 多路径 ~4min

---

## 15. 设计决策记录

| 编号 | 决策 | 理由 | 日期 |
|------|------|------|------|
| DD-001 | 策略通过 prompt suffix 注入而非修改代码逻辑 | 最小侵入性，不改变原版 Orchestrator | 2026-03-13 |
| DD-002 | 每条路径使用独立 ToolManager | MCP 连接有状态，共享会导致冲突 | 2026-03-13 |
| DD-003 | 投票采用"多数优先 + LLM Judge 兜底" | 多数投票零成本，LLM Judge 仅在分歧时启用 | 2026-03-13 |
| DD-004 | 用 DuckDuckGo 替代 Serper | Serper key 无效，DuckDuckGo 免费且足够 | 2026-03-13 |
| DD-005 | 用本地 subprocess 替代 E2B | 无 E2B key，本地执行对测试足够 | 2026-03-13 |
| DD-006 | EA-307 (OpenViking) 作为进化系统的唯一存储层 | 统一存储避免数据碎片化，L0/L1/L2 控制成本 | 2026-03-14 |
| DD-007 | 融合竞争进化 + 经验进化双范式 | 竞争回答"谁赢"，经验回答"为什么赢" | 2026-03-14 |
| DD-008 | EA-307.5 自迭代作为进化系统心跳 | 无需额外调度器，利用现有基础设施驱动进化 | 2026-03-14 |
| DD-009 | 策略选择采用 Exploit + Explore 平衡 | 类似 Multi-Armed Bandit，避免陷入局部最优 | 2026-03-14 |
| DD-010 | 经验记录采用 Self-Improving Agent 格式 | 结构化 ID/Priority/Status 便于追溯和提升 | 2026-03-14 |

---

## 16. 风险与缓解

| 风险 | 影响 | 概率 | 缓解措施 |
|------|------|------|---------|
| Token 成本 N 倍增长 | 高 | 高 | EA-009 早停、EA-306 缓存、EA-010 预算、L0 快速决策 |
| 并行路径竞争 API 限速 | 中 | 中 | 错开启动时间、实现退避机制 |
| 策略进化需要大量历史数据 | 中 | 中 | Phase 2 先积累、冷启动时用内置策略 |
| LLM Judge 选错答案 | 中 | 低 | 多维评分（置信度 + 证据数量 + 来源可靠性） |
| 进化过拟合 (策略只适应历史数据) | 中 | 中 | Explore 机制强制尝试新策略 |
| OpenViking 服务不可用 | 低 | 中 | EA-307 fallback 模式自动降级 |

---

## 17. 术语表

| 术语 | 定义 |
|------|------|
| **Path（路径）** | 一次独立的 Agent ReAct 循环执行 |
| **Strategy（策略）** | 指导 Agent 搜索行为的 prompt 模板 + 参数 |
| **Vote（投票）** | 多路径结果汇聚后的最优选择过程 |
| **Judge（裁判）** | 评选最优答案的 LLM 调用 |
| **Turn（轮次）** | ReAct 循环中 LLM 调用 + 工具执行的一个周期 |
| **Population（种群）** | 当前活跃的策略集合 |
| **Fitness（适应度）** | 策略在特定任务类型上的历史正确率 |
| **Profile（画像）** | 策略的综合效果描述 (胜率/成本/擅长/弱点) |
| **Learning（学习）** | 从执行中提取的结构化经验条目 |
| **Promotion（晋升）** | 经验从记录层提升到规则层或策略层 |
| **Exploit（利用）** | 选择历史最优策略 |
| **Explore（探索）** | 尝试低频/新策略以发现更优方案 |
| **Evolution Signal（进化信号）** | 触发新策略生成的条件 |
| **Self-Iteration（自迭代）** | EA-307.5 周期性聚合分析，驱动整个进化循环 |

---

## 18. 外部研究支撑

### 18.1 谢一凡硕士论文 (上海交通大学, 2025)

**论文**: 《基于大语言模型的金融问答研究》

**核心发现对 EvoAgent 的影响**:

| 论文发现 | EvoAgent 影响 | 对应模块 |
|---------|--------------|---------|
| CoT 效果与任务复杂度正相关 | 验证 EA-104 自适应选择的理论基础 | EA-104 |
| 辩论系统 (92.86%) > 简单投票 (87.14%) | 验证 EA-003 LLM Judge 优于纯多数投票 | EA-003 |
| 裁判模型选择影响系统性能 | EA-003 应支持可配置 Judge 模型 | EA-003 |
| 共识性错误是系统瓶颈 | Explore 机制 + 外部知识验证 (EA-307) | EA-104, EA-307 |
| 裁判被"专业包装"误导 | Judge prompt 强调实质准确性 > 表述自信度 | EA-003 |

**提问框架借鉴**:

| 框架 | 来源 | 应用场景 |
|------|------|---------|
| CoT 五步模板 | 论文第4章 | EA-108 经验提取分析结构 |
| 辩论五阶段流程 | 论文第5章 | EA-307.5 自迭代评估流程 |
| 三类错误分类 | 论文第5章 | EA-108 Learning Entry 的 Pattern-Key |

### 18.2 相关文献索引

| 文献 | 核心贡献 | 与 EvoAgent 关系 |
|------|---------|-----------------|
| Wei et al. (2022) - CoT | 思维链推理 | EA-002 策略 prompt 设计理论基础 |
| Wang et al. (2022) - Self-Consistency | 多路径采样 + 多数投票 | EA-004 多数投票的理论来源 |
| Du et al. (2023) - Multi-Agent Debate | 多智能体辩论框架 | EA-003 LLM Judge 的理论来源 |
| Yao et al. (2023) - ToT | 思维树多路径探索 | EA-001 多路径调度的理论基础 |
| OpenViking (2025) | 文件系统范式管理 Agent 上下文 | EA-307 存储架构 |
| Self-Improving Agent (pskoett) | 结构化经验记录 + 三层晋升 | EA-108 经验提取设计 |
