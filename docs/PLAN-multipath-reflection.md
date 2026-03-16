# 多路径反思系统接入计划

## 现状分析

### 已有组件
- **multi_path.py**: 多路径并发执行，4 种策略 (breadth_first / depth_first / lateral_thinking / verification_heavy)，投票选最佳答案
- **reflector.py**: 单路径反思，分析执行轨迹生成 Experience JSON
- **experience_store.py**: JSONL 存储，按 task_id 去重，多维查询
- **strategy_evolver.py**: 按 question_type × strategy_name 统计胜率，生成 prompt patch
- **experience_injector.py**: 检索相关经验注入 system prompt

### 缺失环节
1. ❌ 多路径反思：现在只有 `_auto_reflect_if_enabled()` 在单路径 pipeline 末尾，多路径 pipeline (`execute_multi_path_pipeline`) 没有调用反思
2. ❌ 每条路径的独立反思：Reflector 只分析一个执行轨迹，不知道同一道题的其他路径做了什么
3. ❌ 路径对比反思：没有"路径 A 对了，路径 B 错了，因为 B 的搜索策略不如 A"这样的对比分析
4. ❌ Strategy 维度的经验记录：`strategy_name` 字段存在但没有在多路径场景下被正确填充
5. ❌ 动态策略权重：StrategyEvolver 能统计胜率，但多路径调度器没有读取这个偏好来动态调整

## 实施计划

### Phase 1: 多路径反思基础接入
**目标**: 每条路径独立反思，正确记录 strategy_name

改动点：
1. `multi_path.py` — `execute_multi_path_pipeline()` 结尾调用反思
2. `reflector.py` — 新增 `reflect_on_multi_path()` 函数，遍历所有路径的 TaskLog
3. Experience 记录中 `strategy_name` 从路径的 strategy 填入

### Phase 2: 路径对比反思
**目标**: 不只看单路径，还对比同题多路径的表现差异

改动点：
1. `reflector.py` — 新增对比反思 prompt，输入多条路径的摘要 + 结果
2. 新增 `comparison_lesson` 字段：跨路径对比经验（如"搜索策略比直接推理更适合此类题"）
3. `experience_store.py` — Experience schema 新增 `comparison_lesson` 和 `path_results` 字段

### Phase 3: 动态策略调整
**目标**: 根据积累的经验，动态调整多路径的策略选择

改动点：
1. `multi_path.py` — `execute_multi_path_pipeline()` 开头读取 StrategyEvolver 的偏好
2. 根据 question_type 的策略胜率，优先选胜率高的策略
3. 淘汰持续低效的策略，替换为新策略

## 数据流（完成后）

```
一道题进来
    │
    ├── ExperienceInjector 注入相关经验到 system prompt
    ├── StrategyEvolver 推荐策略组合（根据 question_type 胜率）
    │
    ▼
多路径并发
    ├── Path 0: breadth_first → TaskLog_0
    ├── Path 1: depth_first → TaskLog_1
    └── Path 2: verification_heavy → TaskLog_2
    │
    ▼
投票选最佳答案
    │
    ▼
多路径反思 (reflect_on_multi_path)
    │
    ├── 每条路径独立反思 → Experience (含 strategy_name)
    ├── 路径对比反思 → comparison Experience
    │
    ▼
ExperienceStore（写入）
    │
    ▼
StrategyEvolver.aggregate_strategy_preferences()
    │ 更新 question_type × strategy_name 胜率表
    ▼
下一道题（闭环）
```
