# Meta-Evolve 方案评审

> 评审对象：`/home/chenzhewen/meta-evolve-plan.txt`
> 评审时间：2026-03-18
> 基于 EvoAgent 当前架构（multi_path.py 三路径 + LLM Judge 投票）

---

## 一、总体评价

方案的方向是对的。核心洞察——**预测不是搜答案，而是并行构造多种未来解释并更新信念**——直接命中了当前系统的根本缺陷。现在的三路径系统（breadth_first / depth_first / lateral_thinking）本质上是同一个 agent 换了个 system prompt，搜索行为高度趋同，"多样性"靠运气而不是设计。

**能不能做？能做。但不能一步到位。**

方案描述的是一个理想态的完整系统，如果一次性实现，工程量巨大且调试困难。建议分 4 个阶段逐步落地，每个阶段都能独立验证和出数据。

---

## 二、方案里最有价值的部分（建议优先做）

### 2.1 专家角色差异化（替换现有三路径）

**现状问题**：breadth_first / depth_first / lateral_thinking 只是 prompt 里一句话的区别，实际搜索行为几乎一样。R5 Grammy 三路径分裂不是因为策略不同，而是搜索结果随机性。

**方案亮点**：5 类专家（News / Mechanism / Market / Historical / Counterfactual）在观察对象、query 目标、更新速度、停止条件上有真实差异。

**可行性**：✅ **高**。这基本就是改 system prompt + query 生成逻辑，不需要大改架构。当前 `multi_path.py` 的 `_build_path_config()` 方法已经支持按路径传不同的 agent config。

**建议调整**：
- 不一定每题都开 5 个专家。用题目分类决定开哪 3 个：
  - 政治/选举题 → News + Mechanism + Counterfactual
  - 体育/娱乐题 → News + Market(赔率) + Historical
  - 科技/产品题 → News + Mechanism + Historical
  - 金融题 → Market + Mechanism + Counterfactual
- 这样保持 3 路径的资源开销，但路径组合因题而异

### 2.2 结构化输出（概率 + 证据 + 风险）

**现状问题**：每条路径只输出一个 `\boxed{X}` 答案，没有置信度、推理链、关键证据。Judge 投票时只能看摘要，信息损失巨大。

**方案亮点**：要求每个专家输出 `(p, direction, rationale, support, risks)`。

**可行性**：✅ **高**。改 agent 的 final answer prompt 格式即可。让 agent 在 `\boxed{}` 之外再输出一个 JSON 结构。

**建议调整**：
- 概率 p 不需要精确到小数。LLM 做概率校准很差，但做"高/中/低置信度"分档还行
- 输出格式建议：`confidence: high/medium/low`，比 `p=0.73` 更可靠
- 关键证据直接引用搜索结果的 URL + 摘要，而不是 agent 自己总结（减少幻觉）

### 2.3 QuerySpec 分层生成

**现状问题**：query 完全由 LLM 自由生成，经常生成冗余或偏题的搜索词。

**方案亮点**：代码层生成 QuerySpec（mode, goal, must_include, constraints），LLM 层生成具体 query。

**可行性**：✅ **中高**。需要在 agent 的 tool call 流程里加一层 query 校验/重写。不需要改 MCP server，在 ToolManager 或 agent prompt 层做。

---

## 三、方案里需要谨慎对待的部分

### 3.1 概率聚合（加权平均）

方案建议 `p̂ = Σ w̃ᵢ pᵢ`，这在理论上很优雅，但实际问题是：

1. **LLM 不会输出校准的概率**。GPT-5 说 p=0.7 和 p=0.3 之间的区别，很可能只是 prompt 措辞不同导致的，不代表真实的置信度差异
2. **专家不独立**。5 个专家用同一个 LLM、搜同一个互联网，输出高度相关。独立假设不成立，加权平均会低估不确定性
3. **FutureX benchmark 是多选题**，最终要输出 A/B/C/D 而不是概率。概率只是中间产物

**建议**：
- 第一版不做概率聚合，继续用投票制，但用**加权投票**（按置信度加权）
- 高置信度的专家票数更大，低置信度的票数更小
- 如果多个高置信专家一致 → 直接采用
- 如果高置信专家分裂 → 触发 Judge 仲裁（现有逻辑）
- 概率聚合留到有连续概率输出的 benchmark 时再做

### 3.2 UCB 调度

方案建议用 UCB/Bandit 算法给专家分配预算，谁近期更有价值谁拿更多资源。

**问题**：
- 单道题内，每个专家通常只跑 1-2 轮。UCB 需要足够的探索才能生效，单题数据太少
- 跨题积累统计是可能的，但需要持久化专家表现数据
- 实现复杂度高，而当前瓶颈不在资源分配

**建议**：
- 第一版不做 UCB，固定每个专家跑相同轮数
- 积累 50+ 题的专家表现数据后，再考虑基于统计的调度
- 更实际的优化是**提前终止**：如果某个专家连续两轮搜不到新信息，直接停

### 3.3 元进化触发与变异

方案建议在"全局停滞"时触发策略变异（`Sᵢ → Sᵢ'`）。

**问题**：
- 单题内"停滞检测"需要多轮迭代数据，当前每条路径通常只跑 7-12 步
- "单点变异 + 模板重组"的搜索空间定义不清——变异哪个维度？变成什么？
- 变异后的策略如何评估？没有 A/B 对照，无法判断变异是否有效

**建议**：
- 元进化不要在单题内做实时变异，而是**跨轮次进化**：
  - R6 用策略 A，R7 根据 R6 的经验调整策略 → 这就是现有 experience 系统该做的事
  - 现有 reflector 的 `_reflect_comparison` 已经在做跨路径比较，只是没有反馈到策略调整
- 第一版的"元进化"就是：**让 reflector 不仅记录"哪道题错了"，还记录"哪种专家在哪类题上表现好/差"**
- 这些统计直接影响下一轮的专家组合选择

### 3.4 专家自评分 F_i

方案定义了 `Fᵢ = w₁·I + w₂·R + w₃·C + w₄·V - w₅·N - w₆·Cost`。

**问题**：
- Information Gain、Noise、Causal Coherence 这些都需要额外的 LLM 调用来评估
- 评估本身也有噪声，形成"用噪声评估噪声"的循环
- 6 个权重的调参空间很大

**建议**：
- 第一版用简单指标：`搜到新信息条数 × 置信度变化幅度 / 总 token 消耗`
- 不需要 LLM 评估，纯数值计算
- 后续有数据了再加复杂评分

---

## 四、方案完全没提但很重要的问题

### 4.1 before_date 瓶颈

当前系统最大的实际瓶颈是 `SEARCH_BEFORE_DATE` 限制。不管专家多聪明，如果 end_time - 1 day 搜不到关键信息，就是搜不到。

方案里的五类专家可以缓解但不能解决这个问题：
- Historical Analogy Expert 不受 before_date 影响（历史数据本来就是旧的）
- Mechanism Expert 也相对不受影响（因果分析不依赖最新新闻）
- 但 News Expert 和 Market Expert 在 before_date 很紧的题上几乎无用

**建议**：在专家选择时，考虑 before_date 与事件日期的间距：
- 间距 ≤ 1 天 → 加重 Mechanism + Historical 权重
- 间距 > 7 天 → 加重 News + Market 权重

### 4.2 经验注入的分类匹配问题

我们刚发现的 bug：R5 有 4 道题经验完全没注入，因为分类规则 `_QUESTION_TYPE_RULES` 太粗，导致 `other` 匹配不到任何经验。

方案里的 Meta-Evolution Memory 层需要先解决这个基础问题：
- 经验存储和检索应该用语义匹配（embedding similarity），不是关键词分类
- 或者至少让分类规则和经验标签用同一套 taxonomy

### 4.3 成本控制

5 个专家 × 多轮迭代 × 每轮多次搜索 + LLM 评估 = 成本可能是当前的 3-5 倍。

当前 10 题跑一轮大约多少 token/cost？如果成本翻 3 倍，是否可接受？

**建议**：设硬性预算上限（比如每题最多 X 次搜索 + Y tokens），在预算内让控制器分配。

### 4.4 与 FutureX Benchmark 的适配

FutureX 是选择题，最终要输出 `\boxed{A}` 而不是概率。方案里的概率输出 → 选项映射这一步没有描述。

一种方式：每个专家直接输出选项 + 置信度，而不是概率。这跟现有系统更兼容。

---

## 五、建议实施路径

### Phase 1：专家差异化（1-2 周）
- 替换 breadth_first / depth_first / lateral_thinking 为基于题型的专家组合
- 每个专家有独立的 system prompt、query 策略、停止条件
- 保持现有的 3 路径并行 + 投票框架
- **验证指标**：跑 cat10，看三路径答案一致率是否下降（越低说明差异越大）

### Phase 2：结构化输出 + 加权投票（1 周）
- 每个专家输出 answer + confidence + key_evidence + risks
- 投票改为加权投票（置信度加权）
- Judge 在需要仲裁时，能看到各专家的证据和风险分析
- **验证指标**：看 Judge 选错的概率是否下降（比如 Grammy 那种情况）

### Phase 3：经验系统重构（1-2 周）
- 经验匹配改为语义检索（embedding similarity）或至少统一分类体系
- reflector 记录"哪种专家在哪类题上的表现"
- 下一轮自动根据统计调整专家组合
- **验证指标**：经验注入覆盖率从 6/10 提升到 9/10+

### Phase 4：控制器 + 元进化（2-3 周）
- 加入提前终止（搜不到新信息就停）
- 加入 before_date 感知的专家权重调整
- 跨轮次策略进化（基于历史表现自动微调专家 prompt）
- **验证指标**：总体正确率 + token 效率

---

## 六、总结

| 维度 | 评价 |
|------|------|
| 方向 | ✅ 完全正确，预测系统需要专家差异化 + 信念聚合 |
| 理论深度 | ✅ 策略 8 元组、UCB 调度、概率聚合都有理论基础 |
| 工程可行性 | ⚠️ 一次性全做不现实，需要分阶段 |
| 与现有架构兼容性 | ✅ Phase 1-2 可以在现有 multi_path.py 上改，不需要重写 |
| 成本考量 | ⚠️ 方案没讨论，5 专家多轮会显著增加成本 |
| 关键缺失 | ❌ before_date 瓶颈、经验分类 bug、FutureX 选择题适配 |
| 优先级建议 | 先做 Phase 1（专家差异化），效果最大、改动最小 |

**一句话：方案是好方案，但要按 Phase 1 → 2 → 3 → 4 逐步落地，每步验证后再进下一步。Phase 1 单独就能显著改善路径多样性。**

---

## 七、2026-03-18 补充：聚合、进化节奏、经验匹配方案

### 7.1 聚合方式确认

加权投票，权重 = 置信度（high/medium/low 映射为 3/2/1）。不做概率加权平均。

### 7.2 进化节奏

**不在单题内做实时变异，按批次进化**。建议：

- 最小批次：**10 题**（跟 cat10 对齐，能快速迭代）
- 标准批次：**50 题**（统计意义更强，每类专家有足够样本）
- 每批结束后 reflector 自动生成：
  1. 每种专家在每类题上的胜率
  2. 每种专家被 Judge 采纳的比例
  3. 哪些专家组合效果最好
- 这些统计反馈到下一批的专家组合选择 + prompt 微调

**10 题的定位是粗筛**：能发现"Historical Expert 在政治题上 5/5 全错"这种强信号，足够做方向性调整（砍掉明显差的、强化明显好的）。但 10 题不够做精确调参（区分 60% vs 70% 胜率）。

**建议起步用 10 题快速迭代 3-4 轮，稳定后切 50 题做精调。**

### 7.3 经验匹配：用 OpenViking 替代关键词分类

当前经验注入的核心 bug：

```
ExperienceInjector._classify_via_rules()  →  question_type = "other"
ExperienceStore.query(question_type="other")  →  0 条匹配
```

问题出在两层不对齐：
- **存储时**：reflector 用 LLM 生成 `question_type`（如 `entertainment_award`、`media_broadcast`）
- **检索时**：injector 用硬编码规则分类（如 `_QUESTION_TYPE_RULES`），跟 LLM 生成的标签对不上

**OpenViking 可以彻底解决这个问题**，因为它的检索是基于 embedding similarity 的：

#### 方案 A：OpenViking 纯替代（推荐）

```
经验存储：
  reflector → experience dict → OpenViking Memory 写入
  （question_summary, lesson, failure_pattern 等文本自动 embedding）

经验检索：
  新题 task_description → OpenViking 语义检索 → top-K 相似经验
  （不需要分类，不需要标签匹配，纯语义相似度）
```

**优点**：
- 彻底消灭分类标签不对齐的问题
- "CECOT 60 Minutes" 能匹配到 "TV programming" 相关经验，因为语义相近
- 不需要维护 `_QUESTION_TYPE_RULES`
- OpenViking 的分层加载（L0/L1/L2）自动控制注入量

**改动量**：
- `ExperienceStore` 加一个 `OpenVikingBackend`，实现 `add()` 和 `query()` 接口
- `ExperienceInjector._classify_via_rules()` 可以保留作为辅助标签，但不再作为检索的唯一依据
- `query()` 改为先走 OpenViking 语义检索，fallback 到关键词匹配

#### 方案 B：轻量替代（不用 OpenViking）

如果不想引入 OpenViking 依赖：

```python
# experience_store.py 加一个 semantic_query()
def semantic_query(self, task_description: str, max_count: int = 5) -> List[dict]:
    """用 LLM embedding 做语义检索"""
    # 1. 对 task_description 算 embedding
    # 2. 对所有经验的 question_summary 算 embedding（缓存）
    # 3. cosine similarity top-K
    # 4. 返回最相似的经验
```

**优点**：不引入新依赖，改动小
**缺点**：需要自己管 embedding 缓存、没有 OpenViking 的分层加载优化

#### 推荐：直接走 OpenViking

OpenViking 架构已经集成在 `multi_path.py` 和 `openviking_context.py` 里了，只是当前实现是 fallback 空壳。不存在"架构重"的问题——架构已经在了，只需要把经验存储和检索接上 OpenViking 的 embedding 检索能力。

**具体做法**：
1. `ExperienceStore` 的 `query()` 方法接入 OpenViking 的语义检索（embedding similarity）
2. `ExperienceInjector.inject()` 不再依赖 `_classify_via_rules()` 做硬匹配，而是把 `task_description` 直接丢给 OpenViking 做语义搜索
3. 经验写入时同时写 JSONL（兼容现有流程）和 OpenViking Memory

这样经验注入的分类匹配问题彻底解决：
- "CECOT 60 Minutes" 能语义匹配到 "TV programming / media broadcast" 相关经验
- "Grammy" (entertainment) 能匹配到 "entertainment_award" 经验
- 不需要维护 `_QUESTION_TYPE_RULES` 硬编码规则
