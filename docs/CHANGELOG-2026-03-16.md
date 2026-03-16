# EvoAgent 修改报告 — 2026-03-16

## 概要

今天共 15 个 commit，跨 2 个 feature 分支，涉及 18 个文件，净增 ~1265 行代码。
主要工作：搜索日期过滤、SerpAPI 多引擎搜索、多路径反思系统、Bug 修复。

---

## 分支 1: `feature/futurex-date-filter`

### 1. DuckDuckGo 搜索日期过滤 (`74c54a5`)
- **文件:** `libs/miroflow-tools/.../search_and_scrape_webpage_local.py`
- **改动:**
  - `_ddg_search()` 新增 `timelimit` 参数
  - 新增 `_parse_timelimit()` 函数，支持预设 (`d/w/m/y`) 和自定义日期范围 (`YYYY-MM-DD..YYYY-MM-DD`)
  - `google_search` MCP tool 新增 `before_date` 参数
- **目的:** FutureX 题目的 `end_time` 可传入搜索，防止 agent 看到事件解决后的答案

---

## 分支 2: `feature/serpapi-search`

### 2. SerpAPI 多引擎搜索 (`d4385bd`)
- **文件:** `libs/miroflow-tools/.../serpapi_mcp_server.py` (新建, 180 行)
- **改动:** 支持 Google/Bing/Baidu/Yahoo/Yandex 五个搜索引擎
- **后续 (`327b502`):** 精简为 Baidu-only（Google/Bing 走 Serper.dev）

### 3. 全搜索引擎 before_date 支持 (`2997421`)
- **文件:** `searching_google_mcp_server.py`, `searching_serpapi_mcp_server.py`, `searching_sougou_mcp_server.py`
- **改动:** 所有搜索 MCP server 都支持 `before_date` 参数

### 4. end_time 自动注入 (`292730c`, `07662fe`)
- **文件:** `libs/miroflow-tools/.../manager.py`, `src/config/settings.py`
- **改动:**
  - 在 ToolManager 层自动拦截搜索调用，注入 `before_date` 参数
  - 不依赖 LLM 主动传参，在框架层面强制生效
  - 通过环境变量 `EVOAGENT_BEFORE_DATE` 或 config 传入

### 5. 多路径反思系统 — Phase 1-3 (`81c7352`)
- **文件:**
  - `src/evolving/reflector.py` — 新增 256 行，多路径对比反思
  - `src/core/multi_path.py` — 新增 101 行，路径级 TaskLog 采集
  - `docs/PLAN-multipath-reflection.md` — 设计文档 (220 行)
  - `scripts/rerun_reflect.py` — 批量反思脚本 (91 行)
- **核心改动:**
  - 新增 `MULTI_PATH_REFLECTION_PROMPT` — 一次 LLM 调用对比所有路径的搜索策略、信息来源、推理过程
  - 新增 `reflect_on_multi_path_task()` — 从 master TaskLog 提取每条路径的摘要并对比分析
  - Experience schema 新增字段: `strategy_scores`, `voting_issue`, `source_overlap`, `path_details`
  - 每条路径的执行轨迹独立记录到 TaskLog 中

### 6. Benchmark 集成 (`bb8b94f`)
- **文件:**
  - `benchmarks/common_benchmark.py` — 接入多路径 pipeline
  - `conf/benchmark/futurex_l4_10.yaml` — FutureX L4 10 题测试配置
  - `conf/agent/single_agent_futurex.yaml` — FutureX 专用 agent 配置
  - `conf/llm/openrouter_gpt5.yaml` — OpenRouter GPT-5 模型配置
- **改动:** benchmark runner 支持调用 `execute_multi_path_task_pipeline()`

### 7. Bug 修复

#### 7a. 环境变量加载顺序 (`de6e541`)
- `.env` 在 Hydra 初始化之前加载，确保 API key 可用
- reflector 的 interpolation fallback 修复

#### 7b. multi_path.py 缺少 import (`2bdfb27`)
- 补充 `pathlib` import
- `evaluate_accuracy` 增加 None 值检查

#### 7c. LLM 配置补全 (`9a5c995`)
- 所有 LLM 配置文件增加 `max_context_length` 字段

#### 7d. ⚠️ asyncio.wait 死循环 (`fc62c89`)
- **严重程度:** 高
- **现象:** `asyncio.wait()` 每次传入全部 task（含已完成的），导致 while 循环无限执行。日志文件增长到 100 万行，计数器到 84 万+。
- **原因:** 已完成的 asyncio.Task 传给 `asyncio.wait` 会立即返回，但 `pending` 集合未正确缩减。
- **修复:** 只传 `pending` 中的 task 给 `asyncio.wait()`。

---

## 当前运行中的测试

- **配置:** `futurex_l4_10` (FutureX Level 4, 10 题)
- **模型:** OpenRouter GPT-5
- **Self-Evolving:** 已启用，注入 1232 chars 经验
- **状态:** 运行中 (PID 91130, 13:09 UTC 启动)

---

## 待办 (未完成)

1. **Reflector + 多路径结合方案最终确认** — 方案 B (对比式反思) 已实现代码但未在实验中验证
2. **`run_selfevolving_experiment.py` 完整流程测试** — evaluate → reflect → evolve 完整链路从未跑通
3. **SkyDiscover 启发的改进** — 动态策略调整、停滞检测、异构路径参数
4. **信息级联防御** — "someone said" 攻击的解决方案

---

## 文件变更汇总

| 文件 | 变更类型 | 行数 |
|------|---------|------|
| `search_and_scrape_webpage_local.py` | 修改 | +66 |
| `serpapi_mcp_server.py` | 新建 | +180 |
| `searching_serpapi_mcp_server.py` | 新建 | +104 |
| `reflector.py` | 修改 | +256 |
| `multi_path.py` | 修改 | +101 |
| `PLAN-multipath-reflection.md` | 新建 | +220 |
| `rerun_reflect.py` | 新建 | +91 |
| `common_benchmark.py` | 修改 | +66 |
| `manager.py` | 修改 | +19 |
| `settings.py` | 修改 | +34 |
| 配置文件 (4个) | 新建 | +70 |
| 其他搜索 MCP (2个) | 修改 | +77 |
| **合计** | **18 文件** | **+1265 行** |
