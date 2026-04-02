# FutureX-49GT 完整测试链路文档

## 概述

本文档描述 `feature/strategy-evolve` 分支上，以 futurex_49gt 数据集为基准的完整测试链路。
链路包含：OpenViking IST 存储、3.4 before_date 搜索限制、QuestionParser 题目解析、
IslandPool UCB 策略选择（29个策略）、多路并发执行、GT 对答案评分、胜率回写+文件锁。

---

## 启动命令

```bash
cd apps/miroflow-agent

PYTHONPATH=".:benchmarks:${PYTHONPATH:-}" \
.venv/bin/python benchmarks/common_benchmark.py \
    benchmark=futurex_49gt \
    llm=openrouter_glm5_turbo \
    llm.async_client=true \
    benchmark.execution.max_concurrent=3 \
    benchmark.execution.pass_at_k=1 \
    agent=single_agent_keep5 \
    question_parser.enabled=true \
    +openviking.enabled=true \
    +openviking.server_url=http://localhost:1933 \
    +storage.openviking.enabled=true \
    +pipeline.auto_reflect=false \
    hydra.run.dir=../../logs/<run_name>
```

> OpenViking 需提前启动：`cd ~/.openclaw/workspace/OpenViking && .venv/bin/openviking-server --port 1933 &`

---

## 数据文件

| 文件 | 说明 |
|------|------|
| `/home/chenzhewen/futurex/online_data_49gt_with_answers.jsonl` | 49题 + ground_truth，benchmark 数据源 |
| `apps/miroflow-agent/data/island_pool/` | 策略池目录（29个策略，5个island） |
| `apps/miroflow-agent/conf/benchmark/futurex_49gt.yaml` | benchmark 配置（max_tasks, multi_path.enabled=true） |
| `apps/miroflow-agent/conf/llm/openrouter_gpt5.yaml` | LLM 配置（async_client=true, model=gpt-5） |
| `apps/miroflow-agent/conf/agent/single_agent_keep5.yaml` | agent 配置（6个工具，keep5路） |

---

## 完整调用链路

### 1. Benchmark Runner 入口
**文件**: `benchmarks/common_benchmark.py`
**函数**: `run_benchmark(cfg)` → `CommonBenchmark.run()` → `CommonBenchmark._run_inference()`

- 读取 `online_data_49gt_with_answers.jsonl`，加载最多 `max_tasks` 道题
- 从题目 `end_time` 字段提取截止日期，设置 `os.environ["SEARCH_BEFORE_DATE"] = end_time - 1day`
  - **before_date 限制来源**: `common_benchmark.py:1001` — `os.environ["SEARCH_BEFORE_DATE"] = search_cutoff`
  - ToolManager 自动注入：`src/tools/tool_manager.py` — 所有搜索 tool call 参数里自动附加 `before_date`
- `benchmark.multi_path.enabled=true` 时调用 `execute_multi_path_task_pipeline()`，传入 `ground_truth`

### 2. 多路 Pipeline 入口
**文件**: `src/core/multi_path.py`
**函数**: `execute_multi_path_task_pipeline(cfg, task_id, task_description, ground_truth, ...)`

#### 2.1 QuestionParser — 题目解析
**文件**: `src/core/question_parser.py`
**类**: `QuestionParser`
**函数**: `QuestionParser.parse(task_description)` → `QuestionParser._call_llm(prompt)` → `base_client.create_message()`

- 触发条件：`cfg.question_parser.enabled=True`
- `multi_path.py:902`: 创建 `TaskLog(task_id="qp_parser")` + `ClientFactory(task_id, cfg, task_log)` 构造 LLM client
- 解析结果：`ParsedQuestion(question_type, key_entities, difficulty_hint, time_window)`
- 失败时 fallback 到 `ParsedQuestion.default()`（type="other"）

#### 2.2 OpenViking 初始化
**文件**: `src/core/openviking_context.py`
**类**: `OpenVikingContext`, `VikingStorageSync`

- `multi_path.py:952`: `ov_enabled = cfg.openviking.enabled`
- 连接 `http://localhost:1933`，失败时 fallback 到内存模式
- `VikingStorageSync` 负责每条 path 完成后写入 IST（路径记忆）

#### 2.3 策略选择 — IslandPool UCB
**文件**: `src/core/multi_path.py`
**函数**: `_select_strategies(cfg, task_description, num_paths, parsed_question)`

- `multi_path.py:354`: 从磁盘加载 pool
  ```python
  pool_dir = "../../data/island_pool"  # 自动 fallback 路径
  _backend = LocalJsonBackend(Path(pool_dir))
  _island_store = IslandStore(primary=_backend)
  pool = _island_store.load()          # 从磁盘读29个策略
  ```
- `pool.sample_all(question_type)` — 每个 island 用 UCB 选一个策略
  - **文件**: `src/core/strategy_island.py`
  - **类**: `IslandPool`
  - **函数**: `IslandPool.sample_all(qt)` → 每个 `StrategyIsland.sample(qt)` → UCB 公式选策略
- 选出策略后调用 `compile_strategy(s)` 生成 prompt_suffix
  - **文件**: `src/core/strategy_compiler.py`
  - **函数**: `compile_strategy(StrategyDefinition)` — 将8维策略参数编译为中文执行指令

#### 2.4 并发执行 5 路 Agent
**文件**: `src/core/multi_path.py`
**函数**: `run_with_retry(path_idx, strategy, max_turns)`

- 每路独立创建 `ToolManager` + `LLMClient`（`ClientFactory`）
- 每路完成后：
  - `OpenVikingContext.save_path_result()` — 写 IST 记忆到 OpenViking
  - 广播 `shared_discovery`（跨路共享）

#### 2.5 投票 + Judge
**文件**: `src/core/weighted_voting.py`
**函数**: `weighted_majority_vote(results, strategies, pool)`

- 按策略历史胜率加权投票
- 分散时调用 Judge LLM 仲裁
- 返回最终答案

#### 2.6 胜率回写 — 文件锁保护
**文件**: `src/core/multi_path.py`，`src/core/strategy_island.py`

- `multi_path.py:1368`: 触发条件 `qp_cfg.enabled=True and parsed_question is not None`
- 加文件锁：
  ```python
  _pool_lock = filelock.FileLock("data/island_pool/.pool.lock", timeout=60)
  _pool_lock.acquire()
  pool = _island_store.load()     # 重新从磁盘读（防止并发覆盖）
  ```
- GT 对答案：`_normalize_answer(ground_truth)` vs `_normalize_answer(path_answer)`
  - 支持格式：`"['A']"`, `"{A}"`, `"A"`, `"B,C"` 等
- 每路调用 `pool.record_result(island_id, strategy_def, question_type, won)`
  - **函数**: `IslandPool.record_result()` → `StrategyIsland.record_result()` → 更新 `total_wins/total_attempts`
- 保存并释放锁：
  ```python
  _island_store.save(pool)        # 写回磁盘
  _pool_lock.release()
  ```

---

## 关键文件索引

| 文件 | 职责 |
|------|------|
| `benchmarks/common_benchmark.py` | 入口：读数据、设 before_date、调 pipeline |
| `src/core/multi_path.py` | 核心协调：QP、OV初始化、策略选、并发跑、投票、胜率回写 |
| `src/core/question_parser.py` | 题目解析，输出 ParsedQuestion |
| `src/core/strategy_island.py` | IslandPool / IslandStore / LocalJsonBackend / UCB 采样 |
| `src/core/strategy_compiler.py` | 将 StrategyDefinition 编译为 prompt_suffix（8维模板）|
| `src/core/openviking_context.py` | OpenViking IST 存储、跨路共享发现 |
| `src/core/weighted_voting.py` | 加权投票 + Judge 仲裁 |
| `src/llm/factory.py` | ClientFactory — 构造 LLM client |
| `src/llm/providers/openai_client.py` | OpenAI/OpenRouter LLM client（含 httpx timeout）|
| `conf/benchmark/futurex_49gt.yaml` | benchmark 配置（数据路径、multi_path、max_tasks）|
| `conf/llm/openrouter_gpt5.yaml` | LLM 配置（async_client=true）|
| `data/island_pool/` | 策略池持久化存储（5 island × 5-6 策略 = 29 个）|

---

## 数据流图

```
common_benchmark.py
  └─ 读 online_data_49gt_with_answers.jsonl
  └─ 设 SEARCH_BEFORE_DATE = end_time - 1day
  └─ execute_multi_path_task_pipeline(ground_truth=GT)
       │
       ├─ QuestionParser.parse()          → ParsedQuestion(type, entities, difficulty)
       ├─ OpenVikingContext.__init__()     → 连接 localhost:1933
       ├─ _select_strategies()
       │    └─ IslandStore.load()         → 从磁盘读 29 个策略
       │    └─ IslandPool.sample_all(qt)  → UCB 选 5 个策略
       │    └─ compile_strategy()         → 生成 prompt_suffix
       │
       ├─ [并发] 5路 Agent
       │    ├─ google_search(before_date=2026-03-03)
       │    ├─ 生成答案 {A/B/C...}
       │    └─ OpenVikingContext.save_path_result()  → IST 写入
       │
       ├─ weighted_majority_vote()        → 投票/Judge → 最终答案
       │
       └─ 胜率回写
            ├─ filelock.acquire()
            ├─ IslandStore.load()
            ├─ _normalize_answer(GT) vs _normalize_answer(path_answer)
            ├─ IslandPool.record_result(island_id, strategy, qt, won)
            ├─ IslandStore.save()
            └─ filelock.release()
```

---

## 已知修复（本分支 vs main）

| Bug | 修复位置 |
|-----|---------|
| QP: `ClientFactory.create` 不存在 | `multi_path.py:902` 改用 `ClientFactory(task_id, cfg, task_log)` |
| QP: `_call_llm` 接口不匹配 | `question_parser.py` 改用 `create_message()` 适配 base_client |
| QP: `ClientFactory` 需要 `task_log` | `multi_path.py:903` 传入 `TaskLog(task_id="qp_parser")` |
| 策略选择: 空 pool | `_select_strategies` 从磁盘 load 而非 `IslandPool()` |
| 胜率回写: `target_island_name` 未定义 | 改回 `island_id` |
| openrouter.yaml: `async_client=false` | 改为 `true`（防 Clash 代理 CLOSE-WAIT）|
| strategy_compiler: 42 个进化维度模板缺失 | 补全 105/105 匹配 |
| OpenAI client: httpx 无 timeout | 加 connect=30s, read=300s |
| pool 并发写冲突 | filelock `.pool.lock` 保护 load-record-save |
