# Strategy Evolution Architecture — EvoAgent v2

> 版本：2026-03-20 v1.0
> 前置文档：`meta-evolve-plan.txt`、`META_EVOLVE_REVIEW.md`、`THREE_PILLARS.md`
> 核心参考：SkyDiscover（AdaEvolve + EvoX 双层进化框架）

---

## 〇、一句话总结

**3 个异构策略岛，每个岛出 1 条路径，3 条路径投票。策略在岛内靠 质量+新颖度 联合筛选防趋同，岛间靠迁移交换好策略，停滞时用 LLM 生成新的进化方向。**

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
| **策略趋同** | 3 条路径搜索行为几乎一样，投票失去意义 | prompt_suffix 只是一句话的差异，不影响实际行为 |
| **不能进化** | 策略池永远是那 4 个 | 没有生成新策略的机制 |
| **不知道什么时候该变** | 连续答错也不会调整 | 没有停滞检测 |
| **不知道往哪个方向变** | reflector 只记"这题错了"，不分析方向 | 没有进化方向生成 |
| **多样性靠人拍** | breadth/depth/lateral 是人为定义的角色 | 没有数学上的多样性保证 |

---

## 二、目标架构

### 2.1 总体设计

```
┌─────────────────────────────────────────────────────────┐
│                    EvoAgent Controller                   │
│                                                         │
│  ┌─────────────┐  ┌──────────────┐  ┌───────────────┐  │
│  │ Stagnation   │  │  Direction   │  │  Evolution    │  │
│  │ Detector     │→ │  Generator   │→ │  Scorer       │  │
│  └─────────────┘  └──────────────┘  └───────────────┘  │
│         ↑                                    ↓          │
└─────────┼────────────────────────────────────┼──────────┘
          │                                    │
    ┌─────┴────────────────────────────────────┴─────┐
    │              Strategy Island Pool               │
    │                                                 │
    │  ┌──────────┐  ┌──────────┐  ┌──────────┐     │
    │  │ Island 0  │  │ Island 1  │  │ Island 2  │    │
    │  │ (Quality) │  │(Balanced) │  │(Explore)  │    │
    │  │           │←→│           │←→│           │    │
    │  │ Archive   │  │ Archive   │  │ Archive   │    │
    │  └─────┬─────┘  └─────┬─────┘  └─────┬─────┘   │
    │        │              │              │          │
    └────────┼──────────────┼──────────────┼──────────┘
             │              │              │
             ▼              ▼              ▼
         Path 0         Path 1         Path 2
       (exploit)       (balanced)     (explore)
             │              │              │
             └──────────────┼──────────────┘
                            ▼
                     投票 / Judge
                            ▼
                       最终答案
```

### 2.2 核心原则

1. **方向和内容分离**：策略（方向）= 结构化的 8 维定义；执行（内容）= MiroThinker ReAct 循环不变
2. **多样性由数学保证**：elite_score = 质量 + 新颖度，不靠人为标签
3. **每个岛出 1 条路径**：3 个异构岛 × 1 路径 = 3 个不同方向的答案
4. **停滞触发进化**：不是每题都进化，连续 N 题没提升才触发
5. **LLM 确定方向，数据验证效果**：进化方向由 LLM 分析生成，效果由后续任务表现评估

---

## 三、策略定义：8 维结构化

### 3.1 维度定义

每个策略是一个结构化 dict，包含 8 个独立维度（源自 `meta-evolve-plan.txt` 的 Si 元组）：

```python
@dataclass
class StrategyDefinition:
    """一个策略的完整定义"""
    
    # 身份
    id: str                    # UUID
    name: str                  # 可读名称（可选，进化生成的可以没有）
    
    # 8 个维度
    hypothesis_framing: str    # Hi: 从什么视角切入（latest-event / driver-analysis / 
                               #     historical-analogy / counterfactual / market-signal）
    query_policy: str          # Qi: 怎么生成搜索词（latest-update / driver-analysis / 
                               #     counter-evidence / historical-analogy / market-signal）
    evidence_source: str       # Ei: 优先信什么来源（news-first / official-first / 
                               #     analysis-first / market-first / archive-first）
    retrieval_depth: str       # Ri: 搜多深（shallow / medium / deep）
    update_policy: str         # Ui: 拿到新证据后怎么更新（fast / moderate / conservative）
    audit_policy: str          # Ai: 什么时候自我质疑（source-check / logic-chain / 
                               #     consensus-challenge / none）
    termination_policy: str    # Ti: 什么时候停（stall-stop / coverage-stop / 
                               #     confidence-stop / budget-stop）
    max_turns: int             # 最大轮次
    
    # 元数据
    parent_id: Optional[str] = None       # 从谁变异来的
    iteration_found: int = 0              # 第几轮发现的
    metrics: Dict[str, float] = field(default_factory=dict)  # 胜率等统计
```

### 3.2 初始策略池

系统启动时预置 5 个策略（对应 meta-evolve-plan 的 5 类专家），分布到 3 个岛：

| 策略 | framing | query_policy | evidence_source | retrieval_depth | update | audit | termination | max_turns |
|------|---------|-------------|----------------|----------------|--------|-------|-------------|-----------|
| news_expert | latest-event | latest-update | news-first | medium | fast | source-check | stall-stop | 100 |
| mechanism_expert | driver-analysis | driver-analysis | official-first | deep | conservative | logic-chain | coverage-stop | 200 |
| historical_expert | historical-analogy | historical-analogy | archive-first | deep | conservative | logic-chain | coverage-stop | 150 |
| market_expert | market-signal | market-signal | market-first | medium | fast | source-check | stall-stop | 100 |
| counterfactual_expert | counterfactual | counter-evidence | analysis-first | medium | moderate | consensus-challenge | stall-stop | 150 |

初始分布：
- Island 0 (Quality)：news_expert, mechanism_expert, market_expert
- Island 1 (Balanced)：全部 5 个
- Island 2 (Explore)：historical_expert, counterfactual_expert, news_expert

### 3.3 策略编译器

将结构化维度编译成 prompt_suffix，供 MiroThinker 使用：

```python
# src/core/strategy_compiler.py

def compile_strategy(strategy: StrategyDefinition) -> dict:
    """将 8 维结构化策略编译成可执行的策略配置"""
    prompt_parts = []
    prompt_parts.append(FRAMING_TEMPLATES[strategy.hypothesis_framing])
    prompt_parts.append(QUERY_TEMPLATES[strategy.query_policy])
    prompt_parts.append(EVIDENCE_TEMPLATES[strategy.evidence_source])
    prompt_parts.append(RETRIEVAL_TEMPLATES[strategy.retrieval_depth])
    prompt_parts.append(UPDATE_TEMPLATES[strategy.update_policy])
    prompt_parts.append(AUDIT_TEMPLATES[strategy.audit_policy])
    prompt_parts.append(TERMINATION_TEMPLATES[strategy.termination_policy])
    
    return {
        "name": strategy.name or strategy.id[:8],
        "description": f"{strategy.hypothesis_framing} + {strategy.query_policy}",
        "max_turns": strategy.max_turns,
        "prompt_suffix": "\n\n".join(prompt_parts),
        "_strategy_def": strategy,  # 保留原始定义，方便进化
    }
```

**每个维度的模板是独立可替换的**。进化时可以只换一个维度的值，不影响其他维度。

---

## 四、策略岛：异构多池设计

### 4.1 岛的配置

借鉴 SkyDiscover 的 `ISLAND_CONFIG_PRESETS`，每个岛用不同的 elite_score 权重：

```python
ISLAND_CONFIGS = [
    {
        "name": "quality",
        "description": "主力岛，偏重胜率",
        "fitness_weight": 0.7,    # 重胜率
        "novelty_weight": 0.2,    # 轻多样性
        "elite_ratio": 0.3,       # 保护更多精英
        "max_size": 10,           # 最多容纳 10 个策略
        "sampling_mode": "exploitation",  # 倾向选胜率最高的
    },
    {
        "name": "balanced",
        "description": "平衡岛，质量与多样性兼顾",
        "fitness_weight": 0.4,
        "novelty_weight": 0.4,
        "elite_ratio": 0.2,
        "max_size": 10,
        "sampling_mode": "balanced",
    },
    {
        "name": "exploration",
        "description": "探索岛，偏重新颖度",
        "fitness_weight": 0.2,
        "novelty_weight": 0.6,
        "elite_ratio": 0.05,      # 几乎不保护精英，大量换血
        "max_size": 10,
        "sampling_mode": "exploration",  # 倾向选最独特的
    },
]
```

### 4.2 策略距离（多样性度量）

SkyDiscover 用代码 token 的 Jaccard 距离。EvoAgent 的策略是结构化的 8 维定义，用**维度差异数**：

```python
def strategy_distance(a: StrategyDefinition, b: StrategyDefinition) -> float:
    """两个策略有几个维度不同（归一化到 0-1）"""
    dimensions = [
        "hypothesis_framing", "query_policy", "evidence_source",
        "retrieval_depth", "update_policy", "audit_policy",
        "termination_policy",
    ]
    diff_count = sum(
        1 for d in dimensions 
        if getattr(a, d) != getattr(b, d)
    )
    return diff_count / len(dimensions)
```

距离 = 0：完全相同的策略
距离 = 1：所有维度都不同

### 4.3 Elite Score

每个策略在岛内的存活分数：

```
elite_score = fitness_weight × fitness_percentile + novelty_weight × novelty_percentile
```

- **fitness_percentile**：按胜率排名的百分位
- **novelty_percentile**：按 k-NN 距离排名的百分位（与池内最近 k 个邻居的平均距离）

### 4.4 淘汰规则（确定性拥挤）

岛满了要加新策略时：
1. 找和新策略**最相似**的非精英策略
2. 比较 elite_score，新的高就替换
3. **效果**：相似策略互相竞争，不同方向的策略不受影响

### 4.5 环形迁移

每 N 道题后，岛之间单向交换 top 策略：

```
Island 0 → Island 1 → Island 2 → Island 0
```

- 复制 top K 策略到下一个岛
- 到了目标岛要过 elite_score 筛选才能留下
- 重复策略（距离 < 阈值）不迁移

**迁移频率**：每 10 道题一次（EvoAgent 每个岛每道题只积累 1 条记录，需要较频繁的迁移来加速传播）。

---

## 五、进化机制

### 5.1 停滞检测

```python
# src/core/stagnation_detector.py

class StagnationDetector:
    def __init__(self, window=10, threshold=0.05):
        self.window = window
        self.threshold = threshold
        self.history = []  # [(task_id, island_idx, strategy_id, won: bool)]
    
    def record(self, task_id, island_idx, strategy_id, won):
        self.history.append((task_id, island_idx, strategy_id, won))
    
    def should_evolve(self) -> bool:
        """最近 N 次 vs 之前 N 次，胜率没提升就触发"""
        if len(self.history) < 2 * self.window:
            return False
        recent = [h[3] for h in self.history[-self.window:]]
        older = [h[3] for h in self.history[-2*self.window:-self.window]]
        recent_wr = sum(recent) / len(recent)
        older_wr = sum(older) / len(older)
        return (recent_wr - older_wr) < self.threshold
    
    def get_failure_analysis(self) -> dict:
        """按题型、按策略维度分析失败原因"""
        # 返回最近失败的策略维度统计
```

### 5.2 进化方向生成

停滞触发后，用 LLM 生成两类进化方向（借鉴 SkyDiscover 的 `variation_operator_generator`）：

```python
# src/evolving/direction_generator.py

DIRECTION_SYSTEM_PROMPT = """
你是预测系统的策略优化专家。

## 策略的 8 个维度
{维度说明}

## 任务
分析策略池的表现数据和失败案例，生成两个进化方向：

1. **DIVERGE（发散变异）**：设计一个全新类型的策略
   - 至少 3 个维度与现有所有策略不同
   - 目标是填补策略池的盲区

2. **REFINE（局部优化）**：改进当前最优策略
   - 只改 1-2 个维度
   - 保留有效的部分，修复薄弱环节

## 输出格式
```json
{
  "diverge": {
    "name": "新策略名",
    "rationale": "为什么需要这个方向",
    "dimensions": { ... 完整 8 维定义 ... }
  },
  "refine": {
    "base_strategy": "要改进的策略 ID",
    "rationale": "为什么改这些维度",
    "changes": { "维度名": "新值", ... }
  }
}
```
"""

async def generate_evolution_direction(
    strategy_stats: dict,
    failure_analysis: dict,
    current_strategies: List[StrategyDefinition],
) -> dict:
    user_prompt = f"""
## 当前策略池（{len(current_strategies)} 个策略）
{format_strategies(current_strategies)}

## 策略表现统计
{json.dumps(strategy_stats, ensure_ascii=False, indent=2)}

## 最近失败分析
{json.dumps(failure_analysis, ensure_ascii=False, indent=2)}

请生成 DIVERGE 和 REFINE 两个进化方向。
"""
    response = await llm_call(DIRECTION_SYSTEM_PROMPT, user_prompt)
    return parse_direction(response)
```

### 5.3 进化效果评估

新策略生成后，不是直接永久替换，而是**试用 + 评估**：

```python
# src/evolving/evolution_scorer.py

class EvolutionScorer:
    def __init__(self, eval_window=10):
        self.eval_window = eval_window
        self.pending_evolutions = {}  # evolution_id → {策略, 起始位置}
    
    def register(self, evolution_id, new_strategy, island_idx):
        """注册一次进化，开始试用期"""
        self.pending_evolutions[evolution_id] = {
            "strategy": new_strategy,
            "island_idx": island_idx,
            "start_idx": len(self.history),
            "before_winrate": self._current_winrate(island_idx),
        }
    
    def evaluate(self, evolution_id) -> dict:
        """试用期结束后评估"""
        evo = self.pending_evolutions[evolution_id]
        after_winrate = self._current_winrate(evo["island_idx"])
        delta = after_winrate - evo["before_winrate"]
        
        return {
            "before": evo["before_winrate"],
            "after": after_winrate,
            "delta": delta,
            "verdict": "keep" if delta > -0.05 else "rollback",
        }
```

**回退机制**：如果新策略导致胜率下降超过 5%，回滚到之前的策略池快照。

---

## 六、每次任务的执行流程

```
1. [任务到达]
   │
2. [各岛采样策略]
   │  Island 0 (Quality): 选胜率最高的策略 → strategy_0
   │  Island 1 (Balanced): 50/50 exploit/explore → strategy_1  
   │  Island 2 (Explore): 按新颖度加权采样 → strategy_2
   │
3. [策略编译]
   │  strategy_compiler.compile(strategy_0) → prompt_suffix_0
   │  strategy_compiler.compile(strategy_1) → prompt_suffix_1
   │  strategy_compiler.compile(strategy_2) → prompt_suffix_2
   │
4. [并行执行] (MiroThinker × 3，与现有 multi_path 一致)
   │  Path 0: MiroThinker + prompt_suffix_0 → answer_0 + confidence_0
   │  Path 1: MiroThinker + prompt_suffix_1 → answer_1 + confidence_1
   │  Path 2: MiroThinker + prompt_suffix_2 → answer_2 + confidence_2
   │
5. [加权投票]
   │  投票权重 = confidence (high=3, medium=2, low=1)
   │  一致 → 直接采用
   │  分裂 → LLM Judge 仲裁
   │
6. [记录结果]
   │  StagnationDetector.record(task_id, island_idx, strategy_id, won)
   │  各 Island 更新策略的 metrics
   │
7. [周期性操作]
   │  每 10 题: 环形迁移
   │  每 10 题: StagnationDetector.should_evolve()?
   │    → Yes: DirectionGenerator → 生成新策略 → 加入对应岛
   │    → No:  继续
   │  每 10 题: EvolutionScorer.evaluate() 评估进行中的进化
```

---

## 七、与现有代码的映射

### 7.1 需要新增的文件

| 文件 | 职责 | 对标 SkyDiscover |
|------|------|-----------------|
| `src/core/strategy_definition.py` | StrategyDefinition 数据结构 | `base_database.py: Program` |
| `src/core/strategy_compiler.py` | 8 维 → prompt_suffix 编译 | 无（SkyDiscover 不需要编译，进化的就是代码） |
| `src/core/strategy_island.py` | 单个岛的 Archive + 采样 + 淘汰 | `adaevolve/archive/unified_archive.py` |
| `src/core/island_pool.py` | 多岛管理 + 迁移 | `adaevolve/database.py` |
| `src/core/stagnation_detector.py` | 停滞检测 | `adaevolve/database.py: _should_spawn_island()` |
| `src/evolving/direction_generator.py` | LLM 生成进化方向 | `evox/utils/variation_operator_generator.py` |
| `src/evolving/evolution_scorer.py` | 进化效果评估 + 回退 | `evox/controller.py: LogWindowScorer` |

### 7.2 需要修改的文件

| 文件 | 修改内容 |
|------|---------|
| `src/core/multi_path.py` | `STRATEGY_VARIANTS` 改为从 IslandPool 动态采样；`_select_strategies()` 改为各岛各出 1 个 |
| `src/evolving/reflector.py` | 输出增加维度级失败分析（哪个维度导致的失败） |
| `main_multipath.py` | 主循环加入停滞检测、进化触发、迁移调度 |

### 7.3 不需要修改的文件

- `src/core/orchestrator.py`：单条路径的执行逻辑不变
- `src/llm/`：LLM 调用层不变
- `libs/miroflow-tools/`：工具层不变
- 评测、日志等基础设施不变

---

## 八、与 META_EVOLVE_REVIEW 的对齐

| Review 建议 | 本方案对应 |
|------------|-----------|
| Phase 1: 专家差异化 | ✅ 5 个初始策略 + 8 维结构化定义 |
| Phase 2: 结构化输出 + 加权投票 | ✅ confidence-based 加权投票 |
| Phase 3: 经验系统重构 | 🔲 不在本方案范围，后续独立做 |
| Phase 4: 控制器 + 元进化 | ✅ StagnationDetector + DirectionGenerator + EvolutionScorer |
| "不在单题内做实时变异，按批次进化" | ✅ 每 10 题检测一次停滞 |
| "before_date 感知" | 🔲 后续做，可在策略选择时加权 |
| "成本控制" | ✅ 3 岛 × 1 路径 = 成本不变（vs 现有 3 路径） |
| "UCB 调度" | ✅ 岛内采样模式（exploit/explore/balanced）替代 UCB |
| "概率聚合 → 加权投票" | ✅ 置信度加权投票，不做概率加权平均 |

---

## 九、与 SkyDiscover 的关键区别

| 维度 | SkyDiscover | EvoAgent Strategy Evolve |
|------|-------------|-------------------------|
| 进化对象 | Python 代码 | 策略的 8 维结构化定义 |
| 距离度量 | 代码 token Jaccard | 维度差异数 / 7 |
| 岛的并行性 | 串行（UCB 选一个岛） | 并行（每个岛同时出 1 条路径） |
| 方向生成 | 分析问题+评估器代码 | 分析失败案例+策略统计 |
| 评估方式 | 代码执行打分 | 预测题正确率 |
| 搜索策略进化 | 有（EvoX 第二层，进化采样逻辑） | 无（第一版不做） |
| 动态生岛 | 有（全局停滞时 spawn） | 无（第一版固定 3 岛） |

---

## 十、实施路径

### Step 1: 策略定义 + 编译器（1-2 天）

- 实现 `StrategyDefinition` 数据结构
- 实现 `StrategyCompiler`（8 维 → prompt_suffix）
- 定义 5 个初始策略
- **验证**：编译出的 prompt_suffix 与现有策略效果相当

### Step 2: 策略岛 + 多岛管理（2-3 天）

- 实现 `StrategyIsland`（单岛的 Archive + 采样 + 淘汰）
- 实现 `IslandPool`（多岛管理 + 迁移）
- 改 `multi_path.py` 的 `_select_strategies()` 从 IslandPool 采样
- **验证**：跑 cat10，3 条路径的答案一致率下降（多样性提升）

### Step 3: 停滞检测 + 进化（2-3 天）

- 实现 `StagnationDetector`
- 实现 `DirectionGenerator`（LLM 生成 diverge/refine）
- 实现 `EvolutionScorer`（效果评估 + 回退）
- **验证**：连续答错后系统能自动生成新策略，且新策略通过试用期

### Step 4: 加权投票 + 结构化输出（1 天）

- Agent 输出增加 confidence: high/medium/low
- 投票改为置信度加权
- **验证**：Judge 仲裁准确率提升

---

## 十一、关键设计决策

| 编号 | 决策 | 理由 |
|------|------|------|
| DD-101 | 每个岛出 1 条路径，不是多条 | 投票需要多样性；同岛多路径会趋同 |
| DD-102 | 策略用 8 维结构化定义，不是自由文本 | 维度可独立进化、可计算距离、可组合 |
| DD-103 | elite_score = 质量 + 新颖度 | 数学保证多样性，不靠人为标签 |
| DD-104 | 进化方向由 LLM 生成 | SkyDiscover 验证了这条路可行 |
| DD-105 | 停滞才进化，不是每题都进化 | 避免过拟合，给策略足够的评估窗口 |
| DD-106 | 进化后有试用期和回退机制 | 防止进化方向错误导致整体退化 |
| DD-107 | 初始策略有预定义角色 | 冷启动需要合理的起点 |
| DD-108 | 进化生成的策略不受角色约束 | 探索空间不被人为限制 |
| DD-109 | 迁移频率较高（每 10 题） | 每岛每题只积累 1 条记录，需要频繁交换 |
| DD-110 | 第一版不做搜索策略的二层进化 | 复杂度控制，先验证一层进化的效果 |
