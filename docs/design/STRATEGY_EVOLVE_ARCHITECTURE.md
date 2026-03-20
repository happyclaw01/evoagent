# Strategy Evolution Architecture — EvoAgent v2

> 版本：2026-03-20 v2.0
> 前置文档：`meta-evolve-plan.txt`、`META_EVOLVE_REVIEW.md`、`THREE_PILLARS.md`
> 核心参考：SkyDiscover（AdaEvolve + EvoX 双层进化框架）

---

## 〇、一句话总结

**5 个专家视角岛，每次任务由 Question Parser 解析题型后，所有岛各出 1 条路径（5 路径并行），投票选最优答案。每轮题结束后所有岛各自进化（refine + diverge）。某类题型所有岛都不擅长时，LLM 定义新专家视角，动态开新岛。**

---

## 一、现状问题

### 1.1 当前架构

```
STRATEGY_VARIANTS (硬编码 4 个)
    ├── breadth_first   → prompt_suffix: "广泛搜索..."
    ├── depth_first     → prompt_suffix: "深度挖掘..."
    ├── lateral_thinking→ prompt_suffix: "换个角度..."
    └── verification    → prompt_suffix: "交叉验证..."

每次任务: 选 3 个 → 并行跑 3 条路径 → 投票
```

### 1.2 核心缺陷

| 问题 | 表现 | 根因 |
|------|------|------|
| **策略趋同** | 3 条路径搜索行为几乎一样 | prompt_suffix 只是一句话的差异 |
| **不能进化** | 策略池永远是那 4 个 | 没有进化机制 |
| **没有题型感知** | 政治题和娱乐题用同样的策略组合 | 没有 Question Parser |
| **不能生成新策略** | 只能在 4 个里选 | 没有方向生成 |
| **多样性靠人拍** | breadth/depth/lateral 是人为定义的 | 没有数学保证 |

---

## 二、目标架构

### 2.1 总体设计

```
Task 进入
    │
    ▼
┌──────────────────┐
│  Question Parser  │  ← 代码层调 LLM 一次（不走 ReAct）
│  输出: 题型/实体   │     可用小模型，成本低
│  /时间窗/criteria  │
└────────┬─────────┘
         │
         ▼
┌────────────────────────────────────────────────────────────────┐
│                        Island Pool                             │
│                                                                │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌─────┐ │
│  │ Island 0  │ │ Island 1  │ │ Island 2  │ │ Island 3  │ │ ... │ │
│  │ 信息追踪   │ │ 机制分析   │ │ 历史类比   │ │ 市场信号   │ │     │ │
│  │ 专家视角   │ │ 专家视角   │ │ 专家视角   │ │ 专家视角   │ │     │ │
│  │           │ │           │ │           │ │           │ │     │ │
│  │ [策略池]   │ │ [策略池]   │ │ [策略池]   │ │ [策略池]   │ │     │ │
│  └──────────┘ └──────────┘ └──────────┘ └──────────┘ └─────┘ │
│       │             │            │                             │
│  所有岛全部参与，每个岛各出 1 条路径                               │
│                                                                │
└──┬────────────┬────────────┬────────────┬────────────┬─────────┘
   │            │            │            │            │
 Island 0    Island 1    Island 2    Island 3    Island 4
 选 1 策略    选 1 策略    选 1 策略    选 1 策略    选 1 策略
   │            │            │            │            │
   ▼            ▼            ▼            ▼            ▼
 Path 0      Path 1      Path 2      Path 3      Path 4
(MiroThinker)(MiroThinker)(MiroThinker)(MiroThinker)(MiroThinker)
   │            │            │            │            │
   └────────────┴────────────┼────────────┴────────────┘
                             ▼
                       投票 / Judge
                             ▼
                         最终答案
                         │
                    记录结果
                         │
              ┌──────────┴──────────┐
              │  一轮题结束后        │
              │  所有岛各自进化       │
              │  (refine + diverge)  │
              │                     │
              │  检查是否需要开新岛   │
              └─────────────────────┘
```

### 2.2 核心原则

1. **按专家视角分岛**：每个岛代表一种看问题的方式，岛内策略是同一视角下的不同变种
2. **Question Parser 前置**：多路径之前解析题型，驱动岛内策略采样、结果记录和进化方向
3. **所有岛全参与**：每次任务所有岛各出 1 条路径，不做选岛，投票多样性最大化
4. **每轮全岛进化**：一轮题（如 10 题）结束后，每个岛各自做 refine + diverge，不靠停滞检测
5. **动态开岛**：某类题型所有岛都不擅长 → LLM 定义新视角 → spawn 新岛，路径数随之增加
6. **方向和内容分离**：策略（方向）= 结构化 8 维定义；执行（内容）= MiroThinker 不变

---

## 三、Question Parser

### 3.1 定位

Question Parser 是**代码层模块**，在 `execute_multi_path_pipeline()` 最前面调用，不进入 agent 的 ReAct 循环。

```python
# multi_path.py
async def execute_multi_path_pipeline(cfg, task_description, ...):
    # Step 0: 解析题目（代码直接调 LLM，1 次调用）
    parsed = await question_parser.parse(task_description)
    
    # Step 1: 所有岛各选一个策略（根据题型选岛内最优）
    strategies = [island.sample(parsed.question_type) for island in island_pool.all_islands]
    
    # Step 2: 编译策略 → prompt_suffix
    # Step 3: 3 条路径并行跑
    # Step 4: 投票
```

### 3.2 输出结构

```python
@dataclass
class ParsedQuestion:
    question_type: str        # politics / entertainment / sports / finance / tech / ...
    key_entities: List[str]   # 关键实体
    time_window: str          # 时间窗口描述
    resolution_criteria: str  # 判定标准
    difficulty_hint: str      # easy / medium / hard（可选，用于预算分配）
```

### 3.3 实现

可以用小模型（GPT-4o-mini 级别），一次调用，结构化输出：

```python
PARSER_PROMPT = """
分析以下预测题目，提取结构化信息。

题目：{task_description}

输出 JSON:
{
    "question_type": "politics|entertainment|sports|finance|tech|science|other",
    "key_entities": ["实体1", "实体2"],
    "time_window": "时间范围描述",
    "resolution_criteria": "判定标准",
    "difficulty_hint": "easy|medium|hard"
}
"""
```

---

## 四、策略定义：8 维结构化

### 4.1 维度定义

```python
@dataclass
class StrategyDefinition:
    """一个策略的完整定义"""
    
    # 身份
    id: str
    name: str
    island_id: str             # 属于哪个岛
    
    # 8 个维度（来自 meta-evolve-plan 的 Si 元组）
    hypothesis_framing: str    # Hi: 从什么视角切入
    query_policy: str          # Qi: 怎么生成搜索词
    evidence_source: str       # Ei: 优先信什么来源
    retrieval_depth: str       # Ri: 搜多深 (shallow/medium/deep)
    update_policy: str         # Ui: 证据更新速度 (fast/moderate/conservative)
    audit_policy: str          # Ai: 自我质疑策略
    termination_policy: str    # Ti: 停止条件
    max_turns: int             # 最大轮次
    
    # 元数据
    parent_id: Optional[str] = None
    iteration_found: int = 0
    
    # 按题型拆分的胜率
    metrics: Dict[str, Any] = field(default_factory=lambda: {
        "overall": {"wins": 0, "total": 0, "rate": 0.0},
        "by_type": {},  # {"politics": {"wins": 5, "total": 8, "rate": 0.625}, ...}
    })
```

### 4.2 策略编译器

将 8 维定义编译成 prompt_suffix：

```python
def compile_strategy(strategy: StrategyDefinition) -> dict:
    """8 维 → prompt_suffix，供 MiroThinker 使用"""
    prompt_parts = [
        FRAMING_TEMPLATES[strategy.hypothesis_framing],
        QUERY_TEMPLATES[strategy.query_policy],
        EVIDENCE_TEMPLATES[strategy.evidence_source],
        RETRIEVAL_TEMPLATES[strategy.retrieval_depth],
        UPDATE_TEMPLATES[strategy.update_policy],
        AUDIT_TEMPLATES[strategy.audit_policy],
        TERMINATION_TEMPLATES[strategy.termination_policy],
    ]
    return {
        "name": strategy.name,
        "max_turns": strategy.max_turns,
        "prompt_suffix": "\n\n".join(prompt_parts),
        "_strategy_def": strategy,
    }
```

### 4.3 策略距离

```python
def strategy_distance(a: StrategyDefinition, b: StrategyDefinition) -> float:
    """维度差异数 / 总维度数，归一化到 0-1"""
    dims = ["hypothesis_framing", "query_policy", "evidence_source",
            "retrieval_depth", "update_policy", "audit_policy", "termination_policy"]
    diff = sum(1 for d in dims if getattr(a, d) != getattr(b, d))
    return diff / len(dims)
```

---

## 五、策略岛

### 5.1 岛的定义

每个岛代表一种**专家视角**——看问题的角度。岛内有多个策略，是同一视角下的不同变种。

```python
@dataclass
class IslandConfig:
    name: str                  # 岛名（= 专家视角名）
    perspective: str           # 视角描述（给 LLM 看的）
    max_size: int = 10         # 最多容纳多少个策略
    elite_ratio: float = 0.2   # 精英保护比例
    fitness_weight: float = 0.6
    novelty_weight: float = 0.4
```

### 5.2 初始 5 个岛

开局设置 5 个岛，对应 meta-evolve-plan 的 5 类专家：

| 岛 | 视角 | 初始策略 | 擅长场景 |
|---|---|---|---|
| **信息追踪** | 追踪最新事件进展 | news_expert | 时事题、突发事件 |
| **机制分析** | 分析结构性驱动因素 | mechanism_expert | 政策题、选举题 |
| **历史类比** | 找相似历史案例 | historical_expert | 规律性题、base rate |
| **市场信号** | 从赔率/价格提取信号 | market_expert | 金融题、有赔率的题 |
| **对抗验证** | 专门攻击主流判断 | counterfactual_expert | 所有题（作为纠偏） |

每个岛开局只有 1 个策略（种子），后续通过进化逐步填充到 max_size。

### 5.3 岛内管理

#### Elite Score

```
elite_score = fitness_weight × fitness_percentile + novelty_weight × novelty_percentile
```

- **fitness**：该策略在特定题型上的胜率（条件化的，不是全局的）
- **novelty**：该策略与岛内其他策略的平均距离（k-NN）

#### 淘汰（确定性拥挤）

岛满了要加新策略：
1. 找和新策略最相似的非精英策略
2. 新的 elite_score 更高就替换
3. 同视角的策略互相竞争，不影响其他视角

### 5.4 岛间迁移

每轮进化后，岛间环形迁移 top 策略：

```
Island 0 → Island 1 → Island 2 → Island 3 → Island 4 → Island 0
```

- 复制 top 1 策略到下一个岛
- 到目标岛要过 elite_score 筛选
- 距离太近（< 0.3）的不迁移

**意义**：一个信息追踪岛的好策略迁移到机制分析岛，大概率因为视角太不同被拒。但偶尔一个"既会追新闻又会做机制分析"的混合策略能跨岛存活——这是有价值的发现。

---

## 六、策略选择

### 6.1 全部岛参与

**每次任务，所有岛都出 1 条路径。** 不做选岛——5 个岛 = 5 条路径，全部并行跑，最后投票。

这保证了每道题都有 5 个不同视角的答案，投票质量最高。动态开了新岛后，路径数随之增加（6 个岛 = 6 条路径）。

Question Parser 的解析结果不用于选岛（因为全上），而用于：
- **岛内策略采样**：每个岛选出该题型上胜率最高的策略
- **结果记录**：按题型记录各策略的胜率
- **进化方向**：分析哪类题型在哪个岛上表现差

### 6.2 岛内策略采样

每个岛从自己的策略池里选 1 个策略：

```python
def sample(self, question_type: str) -> StrategyDefinition:
    """从岛内选该题型上最优的策略"""
    candidates = self.get_all_strategies()
    return max(candidates, key=lambda s: s.get_rate_for_type(question_type))
```

如果某个岛在该题型上没有任何数据，退回全局胜率选择。

---

## 七、进化机制

### 7.1 进化时机

**每轮题结束后，所有岛各自进化一次。**

"一轮" = 一批评测题（如 cat10 的 10 题，或自定义批次）。不靠停滞检测触发——每轮都进化，保持迭代节奏。

```
轮次 1: 跑 10 题 → 记录结果 → 所有岛各自进化 → 检查是否需要开新岛
轮次 2: 跑 10 题 → 记录结果 → 所有岛各自进化 → 检查是否需要开新岛
...
```

### 7.2 每个岛的进化：Refine + Diverge

每轮每个岛做两件事：

#### Refine（调优）

拿岛内胜率最高的策略，让 LLM 微调 1-2 个维度：

```python
REFINE_PROMPT = """
## 当前策略
{best_strategy 的 8 维定义}

## 该策略的表现
{按题型拆分的胜率}

## 最近失败案例（该岛内策略答错的题）
{failure_details}

请微调这个策略的 1-2 个维度，保留有效的部分，改进薄弱环节。
输出修改后的完整 8 维定义。
"""
```

#### Diverge（探索）

在岛的视角范围内，让 LLM 设计一个全新变种：

```python
DIVERGE_PROMPT = """
## 岛的视角定位
{island.perspective}

## 岛内现有策略
{所有策略的 8 维定义}

## 目标
设计一个属于"{island.perspective}"视角、但和现有策略明显不同的新策略。
至少 3 个维度与现有策略不同。
输出完整 8 维定义。
"""
```

每轮每个岛：1 个 refine 子代 + 1 个 diverge 子代 = 2 个新策略。经过 elite_score 筛选后，好的留下，差的淘汰。

### 7.3 进化效果评估

新策略不需要单独的"试用期"——它加入岛后，自然会在后续的轮次中被采样到，积累胜率数据。如果连续几轮胜率都低，自然会被 elite_score 淘汰。

### 7.4 动态开新岛

每轮进化后，检查是否需要开新岛：

```python
def should_spawn_island(question_type_stats: dict) -> Optional[str]:
    """
    检查：是否存在某个题型，所有现有岛的胜率都低于阈值？
    
    question_type_stats = {
        "politics": {"best_island_rate": 0.8},
        "entertainment": {"best_island_rate": 0.2},  ← 所有岛都不擅长
        ...
    }
    """
    for qtype, stats in question_type_stats.items():
        if stats["best_island_rate"] < 0.4 and stats["total_samples"] >= 5:
            return qtype  # 这个题型需要新岛
    return None
```

触发后，让 LLM 定义新的专家视角：

```python
SPAWN_PROMPT = """
## 问题
以下题型在现有的所有专家视角下表现都很差：
- 题型：{question_type}
- 各岛表现：{per_island_rates}
- 典型失败案例：{failure_examples}

## 现有的专家视角
{所有岛的 perspective 描述}

## 任务
设计一个全新的专家视角，专门针对 "{question_type}" 类题目。
要求和现有视角明显不同。

输出：
{
    "perspective": "新视角的描述",
    "initial_strategy": { 完整 8 维定义 },
    "rationale": "为什么这个视角能解决当前短板"
}
"""
```

新岛以 LLM 生成的初始策略为种子，后续和其他岛一样参与进化。

---

## 八、策略评估：题型条件化

### 8.1 按题型记录胜率

每次任务结束后：

```python
def record_result(strategy_id, island_id, question_type, won, adopted):
    strategy = get_strategy(strategy_id)
    
    # 更新全局统计
    strategy.metrics["overall"]["total"] += 1
    if won:
        strategy.metrics["overall"]["wins"] += 1
    strategy.metrics["overall"]["rate"] = wins / total
    
    # 更新题型统计
    if question_type not in strategy.metrics["by_type"]:
        strategy.metrics["by_type"][question_type] = {"wins": 0, "total": 0, "rate": 0.0}
    type_stats = strategy.metrics["by_type"][question_type]
    type_stats["total"] += 1
    if won:
        type_stats["wins"] += 1
    type_stats["rate"] = type_stats["wins"] / type_stats["total"]
```

### 8.2 Fitness 计算

岛内排名时，fitness 使用**当前题型的胜率**（而不是全局胜率）：

```python
def get_fitness(strategy, question_type=None):
    if question_type and question_type in strategy.metrics["by_type"]:
        type_stats = strategy.metrics["by_type"][question_type]
        if type_stats["total"] >= 3:  # 至少 3 个样本才用题型胜率
            return type_stats["rate"]
    return strategy.metrics["overall"]["rate"]
```

---

## 九、加权投票

### 9.1 结构化输出

每条路径的 agent 输出增加 confidence：

```
答案：\boxed{A}
置信度：high / medium / low
关键证据：[URL1: 摘要, URL2: 摘要]
主要风险：可能错在哪里
```

### 9.2 投票权重

```
high = 3 票
medium = 2 票
low = 1 票
```

- 一致 → 直接采用
- 分裂 → LLM Judge 仲裁，可以看到各路径的证据和风险分析

---

## 十、每次任务的完整流程

```
1. [Task 到达]
   │
2. [Question Parser] (代码调 LLM 一次，可用小模型)
   │  → question_type, key_entities, time_window, resolution_criteria
   │
3. [所有岛各选策略] 每个岛根据 question_type 选出该题型上最优的策略
   │
4. [编译策略] 每个策略的 8 维 → prompt_suffix
   │
5. [N 条路径并行执行] MiroThinker × N（N = 岛数，初始 5 条）
   │
6. [加权投票] confidence-based，分裂时 Judge 仲裁
   │
8. [记录结果] 每个策略按题型记录 win/lose/adopted
   │
9. [一轮结束后]
   │  a. 所有岛各自进化（1 refine + 1 diverge = 2 个新策略/岛）
   │  b. 岛间环形迁移
   │  c. 检查是否需要开新岛
```

---

## 十一、与现有代码的映射

### 11.1 新增文件

| 文件 | 职责 |
|------|------|
| `src/core/question_parser.py` | 题目解析（题型/实体/时间窗） |
| `src/core/strategy_definition.py` | StrategyDefinition 数据结构 |
| `src/core/strategy_compiler.py` | 8 维 → prompt_suffix 编译 |
| `src/core/strategy_island.py` | 单岛：策略池 + 采样 + 淘汰 + elite_score |
| `src/core/island_pool.py` | 多岛管理：选岛 + 迁移 + 动态开岛 |
| `src/evolving/direction_generator.py` | LLM 生成 refine/diverge 方向 |

### 11.2 修改文件

| 文件 | 修改 |
|------|------|
| `src/core/multi_path.py` | `_select_strategies()` 改为从 IslandPool 采样；最前面加 QuestionParser |
| `src/evolving/reflector.py` | 输出加维度级失败分析 |
| `main_multipath.py` | 主循环加入每轮进化 + 动态开岛 |

### 11.3 不修改

- `src/core/orchestrator.py`：单路径 ReAct 不变
- `src/llm/`：LLM 调用层不变
- `libs/miroflow-tools/`：工具层不变
- 评测、日志等基础设施不变

---

## 十二、与 META_EVOLVE_REVIEW 的对齐

| Review 建议 | 本方案 |
|------------|--------|
| Phase 1: 专家差异化 | ✅ 5 个专家视角岛 |
| Phase 2: 结构化输出 + 加权投票 | ✅ confidence + 加权投票 |
| Phase 3: 经验系统重构 | 🔲 不在本方案范围 |
| Phase 4: 控制器 + 元进化 | ✅ 每轮进化 + 动态开岛 |
| "不在单题内做实时变异，按批次进化" | ✅ 每轮（10 题）进化一次 |
| "before_date 感知" | 🔲 后续可在选岛时加权 |
| "成本控制" | ⚠️ 5 岛全上 = 5 路径，成本约为现有 3 路径的 1.7 倍，动态开岛后会进一步增加 |
| "概率聚合 → 加权投票" | ✅ 置信度加权投票 |

---

## 十三、与 SkyDiscover 的关键区别

| 维度 | SkyDiscover | EvoAgent v2 |
|------|-------------|-------------|
| 进化对象 | Python 代码 | 策略的 8 维定义 |
| 岛的含义 | 管理风格（quality/diversity） | 专家视角（信息追踪/机制分析/...） |
| 岛的数量 | 固定 4 个，可动态 spawn | 初始 5 个，可动态 spawn |
| 进化触发 | 停滞检测 | 每轮都进化 |
| 题型感知 | 无（同一问题反复跑） | 有（Question Parser + 条件化评估） |
| 距离度量 | 代码 token Jaccard | 维度差异数 / 7 |
| 岛的并行性 | 串行（UCB 选 1 个） | 并行（所有岛全出路径） |
| 评估方式 | 同一评估函数反复跑 | 每道新题跑一次，按题型积累 |
| 动态开岛条件 | 全局停滞 | 特定题型全岛表现差 |

---

## 十四、实施路径

### Step 1: Question Parser + 策略定义（1-2 天）

- 实现 `QuestionParser`
- 实现 `StrategyDefinition` + `StrategyCompiler`
- 定义 5 个初始策略
- **验证**：解析 cat10 的 10 道题，确认题型分类准确

### Step 2: 策略岛 + 岛池（2-3 天）

- 实现 `StrategyIsland`（单岛 Archive + 采样 + 淘汰）
- 实现 `IslandPool`（选岛 + 迁移 + 动态开岛）
- 改 `multi_path.py` 的策略来源
- **验证**：跑 cat10，3 条路径的答案一致率下降（多样性提升）

### Step 3: 进化机制（2-3 天）

- 实现 `DirectionGenerator`（refine + diverge）
- 主循环加入每轮进化
- 实现动态开岛
- **验证**：跑 2 轮 cat10，第 2 轮观察到新策略被生成和使用

### Step 4: 加权投票 + 结构化输出（1 天）

- Agent 输出增加 confidence
- 投票改为加权
- **验证**：Judge 仲裁准确率提升

---

## 十五、关键设计决策

| 编号 | 决策 | 理由 |
|------|------|------|
| DD-101 | 按专家视角分岛 | 视角差异 = 真实的搜索行为差异，比 quality/diversity 分法更适合预测场景 |
| DD-102 | 开局 5 个岛 | 对应 meta-evolve-plan 的 5 类专家，冷启动有合理起点 |
| DD-103 | Question Parser 前置 | 驱动选岛、策略评估、进化方向，是整个条件化链路的基础 |
| DD-104 | 每次所有岛全部出路径 | 5 个视角全参与，投票多样性最大化 |
| DD-105 | 动态开岛后路径数随之增加 | 新视角自动加入，不需要淘汰老岛 |
| DD-106 | 每轮全岛进化，不靠停滞检测 | 数据量小（每轮 10 题），等停滞再进化太慢 |
| DD-107 | 每岛每轮 1 refine + 1 diverge | 既优化已有的，又探索新的 |
| DD-108 | 题型条件化评估 | 不同题型适用不同策略，全局胜率会掩盖真实表现 |
| DD-109 | 动态开岛由题型表现触发 | 某类题所有岛都不擅长 → 需要全新视角 |
| DD-110 | 策略用 8 维结构化定义 | 可独立进化、可计算距离、可组合 |
| DD-111 | elite_score = 质量 + 新颖度 | 岛内多样性由数学保证 |
| DD-112 | 进化生成的策略不受视角约束 | diverge 可以探索视角边界，迁移可以跨视角 |
