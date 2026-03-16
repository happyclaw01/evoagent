# 多路径反思系统 — 计划与实施报告

## 一、现状分析

### 已有组件（改动前）
| 组件 | 文件 | 状态 |
|------|------|------|
| 多路径执行器 | `multi_path.py` | ✅ 完整，4 种策略 + 投票 |
| 单路径反思 | `reflector.py` | ✅ 完整，但只在单路径 pipeline 调用 |
| 经验存储 | `experience_store.py` | ✅ 完整 |
| 策略进化 | `strategy_evolver.py` | ✅ 完整，但没被多路径调度器使用 |
| 经验注入 | `experience_injector.py` | ✅ 完整 |
| 配置开关 | `config.yaml` | `evolving.enabled: false` |

### 缺失环节（改动前）
1. ❌ `execute_multi_path_pipeline()` 没有调用反思
2. ❌ 没有按路径记录 `strategy_name`
3. ❌ 没有跨路径对比分析
4. ❌ 多路径调度器不读取策略偏好
5. ❌ 策略胜率表在多路径反思后不会自动更新

---

## 二、实施方案

### Phase 1: 多路径反思基础接入 ✅

**改动文件**: `reflector.py`, `multi_path.py`

**新增函数**:
- `reflect_on_multi_path(path_results, task_description, ground_truth, llm_client, ...)` 
  - 遍历所有路径的 TaskLog
  - 逐条调用 `reflect_on_task()` 做独立反思
  - 从 path metadata 填入正确的 `strategy_name`
  - 写入 ExperienceStore

- `auto_reflect_multi_path(path_results, task_description, ground_truth, cfg, store)`
  - multi_path.py 调用的入口函数
  - 检查 `evolving.enabled` + `auto_reflect` + `ground_truth`
  - 初始化 LLM client，调用 `reflect_on_multi_path()`
  - 反思完成后自动触发 `StrategyEvolver.aggregate_strategy_preferences()`

**multi_path.py 改动**:
- 在投票选出最佳答案后、保存 master_log 前，调用 `auto_reflect_multi_path()`
- 传入 `processed_results`（包含所有路径的 summary/answer/log_path/strategy/metadata）

### Phase 2: 路径对比反思 ✅

**改动文件**: `reflector.py`

**新增 Prompt**: `MULTI_PATH_COMPARISON_PROMPT`
- 输入: 题目 + ground_truth + 所有路径的摘要（策略名、答案、对错、耗时、步数）
- 输出 JSON:
  ```json
  {
    "question_type": "sports_event",
    "question_summary": "...",
    "winning_strategy": "breadth_first",
    "losing_strategies": ["depth_first", "lateral_thinking"],
    "comparison_lesson": "广搜策略在体育赛事预测中表现更好，因为...",
    "strategy_insights": {
      "breadth_first": "搜了 5 个独立来源，交叉验证有效",
      "depth_first": "只深挖了 1 个来源，信息片面"
    },
    "recommended_strategies": ["breadth_first", "verification_heavy"],
    "avoid_strategies": ["direct_reasoning"]
  }
  ```

**新增函数**: `_reflect_comparison(path_results, task_description, ground_truth, llm_client, model)`
- 构建各路径的结果摘要
- 调用 LLM 生成对比分析
- 返回 comparison experience（task_id 为 `comparison_YYYYMMDDHHMMSS`）

### Phase 3: 动态策略选择 ✅

**改动文件**: `multi_path.py`

**新增函数**: `_select_strategies(cfg, task_description, num_paths)`
- 用 `ExperienceInjector._classify_via_rules()` 识别 question_type
- 从 `StrategyEvolver.load_strategy_preferences()` 读取推荐策略
- 推荐策略优先排列，不足的用默认策略补充
- 无数据时降级为 `STRATEGY_VARIANTS[:num_paths]`

**调度器改动**:
- `execute_multi_path_pipeline()` 开头：`strategies = _select_strategies(cfg, task_description, num_paths)`
- 替换原来的固定 `STRATEGY_VARIANTS[:num_paths]`

---

## 三、完整数据流

```
FutureX 题目
    │
    ▼
prepare_task_description()
    │  设置 SEARCH_BEFORE_DATE（日期过滤）
    │  注入时间约束 prompt
    │
    ▼
execute_multi_path_pipeline()
    │
    ├── _select_strategies()
    │   ├── 识别 question_type（关键词规则）
    │   ├── 读取 strategy_preferences.json
    │   └── 返回推荐策略列表（或默认）
    │
    ├── ExperienceInjector.inject()
    │   ├── 检索同类型失败/成功经验
    │   ├── 检索策略推荐
    │   ├── 检索 prompt patch
    │   └── 拼接注入 system prompt
    │
    ├── 多路径并发
    │   ├── Path 0: breadth_first → TaskLog_0
    │   ├── Path 1: depth_first → TaskLog_1
    │   └── Path 2: verification_heavy → TaskLog_2
    │
    ├── 投票 → 选最佳答案
    │
    └── auto_reflect_multi_path()
        ├── 逐路径独立反思 → 3 个 Experience（含 strategy_name）
        ├── 跨路径对比反思 → 1 个 comparison Experience
        ├── 全部写入 ExperienceStore
        └── StrategyEvolver.aggregate_strategy_preferences()
            └── 更新 question_type × strategy_name 胜率表
    │
    ▼
下一道题（闭环）
```

---

## 四、Experience 记录示例

### 单路径反思记录
```json
{
  "task_id": "task_001_path0_breadth_first",
  "question_type": "sports_event",
  "question_summary": "2026年NBA总决赛冠军预测",
  "strategy_name": "breadth_first",
  "was_correct": true,
  "lesson": "搜索多个独立体育新闻来源进行交叉验证比只看一个来源更可靠",
  "failure_pattern": null,
  "reasoning_type": "info_retrieval",
  "knowledge_domain": "sports",
  "tools_used": ["web_search"],
  "level": 2
}
```

### 跨路径对比记录
```json
{
  "task_id": "comparison_20260316071000",
  "question_type": "sports_event",
  "question_summary": "2026年NBA总决赛冠军预测",
  "winning_strategy": "breadth_first",
  "losing_strategies": ["depth_first", "lateral_thinking"],
  "comparison_lesson": "广搜策略在体育赛事预测中表现更好。depth_first 只深挖了一个来源导致信息偏差，lateral_thinking 搜索角度过于发散没找到关键信息。",
  "strategy_insights": {
    "breadth_first": "搜了5个独立来源，交叉验证有效",
    "depth_first": "只深挖了1个来源，信息片面",
    "lateral_thinking": "搜索角度发散但没命中关键信息"
  },
  "recommended_strategies": ["breadth_first", "verification_heavy"],
  "avoid_strategies": ["lateral_thinking"]
}
```

### 策略偏好表（自动生成）
```json
{
  "stats": {
    "sports_event": {
      "breadth_first": {"total": 10, "correct": 8, "accuracy": 0.8},
      "depth_first": {"total": 10, "correct": 5, "accuracy": 0.5},
      "verification_heavy": {"total": 8, "correct": 6, "accuracy": 0.75},
      "lateral_thinking": {"total": 10, "correct": 3, "accuracy": 0.3}
    }
  },
  "recommendations": {
    "sports_event": ["breadth_first", "verification_heavy"]
  }
}
```

---

## 五、开启方式

```yaml
# conf/config.yaml
evolving:
  enabled: true                    # ← 改这一行
  auto_reflect: true               # 每题自动反思
  experience_file: "../../data/experiences.jsonl"
  strategy_preferences_file: "../../data/strategy_preferences.json"
  prompt_overrides_file: "../../data/prompt_overrides.jsonl"
  max_experiences: 5
  min_samples_for_recommendation: 3
```

无需其他改动，多路径执行器自动：
1. 读取策略偏好 → 选策略
2. 注入历史经验 → 跑多路径
3. 反思每条路径 + 对比分析 → 写入经验
4. 更新策略偏好表 → 闭环

## 六、风险与注意事项

| 风险 | 应对 |
|------|------|
| 反思 LLM 调用增加成本 | 每题增加 1+1 次调用（N 条路径反思 + 1 次对比），可用便宜模型 |
| 路径 TaskLog 文件不存在 | `reflect_on_multi_path` 已做 try/except 保护 |
| 经验积累初期数据少 | `_select_strategies` 数据不足时降级为默认策略 |
| 并行执行题目间经验不共享 | 同一 batch 内无法互相利用，但 batch 间可以 |
| 反思失败影响主流程 | 所有反思调用都 try/except 包裹，永远不阻塞主 pipeline |
