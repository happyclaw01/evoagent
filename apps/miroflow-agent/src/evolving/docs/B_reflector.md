# 子模块 B：Reflector（反思引擎）

## 1. 目标

任务执行完成后，自动分析执行过程，生成结构化经验写入 ExperienceStore。修复当前 reflector.py 中的 bug，并实现自动触发。

## 2. 需求

### 2.1 修复现有 Bug

| Bug | 位置 | 修复方案 |
|-----|------|---------|
| 字段名不匹配 | `reflector.py:50` — `task_log.get("steps", [])` | 改为 `task_log.get("step_logs", [])` |
| StepLog 字段名不匹配 | `reflector.py:61-66` — 读取 `level`/`label`/`content` | 改为 `info_level`/`step_name`/`message`（对齐 `StepLog` dataclass） |
| 硬编码 OpenAI | `reflector.py:20-21, 158` — 只能用 OpenAI API | 复用项目已有 LLM 配置，或通过参数传入 client |

### 2.2 反思 Prompt 升级

当前 REFLECTION_PROMPT 输出 7 个字段，需扩展为子模块 A 定义的完整 schema：

```
新增输出字段：
- reasoning_type:  "numerical_computation" | "logical_reasoning" | "info_retrieval" | "multi_step" | "planning"
- knowledge_domain: "finance" | "sports" | "geopolitics" | "tech" | "entertainment" | "science" | "other"
- tools_used:       ["web_search", "code_execution", "solver", "browsing"]（从 trace 中提取）
- strategy_name:    agent 实际采用的策略名称
```

### 2.3 自动触发

在 `pipeline.py` 中任务完成后自动调用反思，无需手动跑脚本：

- 成功路径（`pipeline.py:115-118`）：有 ground_truth 时触发
- 失败路径（`pipeline.py:138-141`）：同样触发（失败经验更有价值）
- 反思失败不影响主流程（try/except 包裹，只 log warning）
- 反思应异步执行，不阻塞主 pipeline 返回

### 2.4 LLM Client 复用

不再自己创建 OpenAI client，而是：
- 优先复用 pipeline 中已有的 `ClientFactory` / LLM 配置
- 支持通过 `evolving.reflection_model` 配置项指定反思用的模型（可以用便宜模型）
- 如果未配置，fallback 到主 agent 使用的模型

### 2.5 保留手动批量反思

现有 `scripts/run_reflection.py` 的批量模式保留，用于：
- 对历史 log 补做反思
- 对新一轮 benchmark 跑完后批量生成经验

## 3. 接口设计

```python
# === 核心反思函数（重构后） ===

async def reflect_on_task(
    task_log: dict,
    ground_truth: str,
    llm_client: Any,           # 项目通用 LLM client，不再限定 OpenAI
    model: str = "",           # 为空时使用 client 默认模型
    experience_store: Optional[ExperienceStore] = None,  # 直接写入 store
) -> Optional[dict]:
    """
    对单个任务做反思，生成符合 Experience schema 的经验 dict。
    如果传入 experience_store，自动写入。

    Args:
        task_log: 任务日志 dict（从 TaskLog.to_json() 反序列化）
        ground_truth: 标准答案
        llm_client: LLM 调用客户端
        model: 反思用模型名
        experience_store: 可选，自动写入

    Returns:
        Experience dict，或 None（反思失败时）
    """


async def reflect_on_batch(
    log_dir: str,
    ground_truths: dict,           # task_id -> ground_truth
    experience_store: ExperienceStore,
    llm_client: Any,
    model: str = "",
) -> List[dict]:
    """
    批量反思一个目录下的所有任务日志。

    Returns:
        生成的经验列表
    """


# === Pipeline 自动触发入口 ===

async def auto_reflect_after_task(
    task_log: TaskLog,
    cfg: DictConfig,
    experience_store: ExperienceStore,
) -> None:
    """
    在 pipeline.py 中任务完成后调用。
    仅当 evolving.enabled=True 且 ground_truth 存在时执行。
    内部 try/except，不向外抛异常。

    Args:
        task_log: 当前任务的 TaskLog 实例
        cfg: Hydra 配置
        experience_store: 经验存储实例
    """
```

### 内部辅助函数（重构）

```python
def _extract_trace_summary(task_log: dict, max_steps: int = 15) -> str:
    """
    从 task_log 提取执行轨迹摘要。
    修复字段映射：step_logs -> info_level/step_name/message
    """


def _extract_tools_used(task_log: dict) -> List[str]:
    """
    从 step_logs 中提取实际使用的工具列表。
    扫描 step_name 中的 [TOOL>]、[SEARCH]、[BROWSER]、[PY] 等标记。

    Returns:
        去重后的工具名列表，如 ["web_search", "code_execution", "browsing"]
    """
```

## 4. 接入点（改动位置）

| 位置 | 改动 |
|------|------|
| `src/evolving/reflector.py` | **重构**：修复 bug + 升级 prompt + 新增 `auto_reflect_after_task()` |
| `src/core/pipeline.py:115-118` | 成功路径插入自动反思调用 |
| `src/core/pipeline.py:138-141` | 失败路径插入自动反思调用 |
| `conf/config.yaml` | 新增 `evolving.reflection_model` 配置 |
| `scripts/run_reflection.py` | 适配新接口，改用 `ExperienceStore` |

## 5. Pipeline 接入示意

```python
# pipeline.py 改动示意（成功路径）

    try:
        # ... 现有代码 ...
        final_summary, final_boxed_answer = await orchestrator.run_main_agent(...)
        llm_client.close()

        task_log.final_boxed_answer = final_boxed_answer
        task_log.status = "success"

        # >>> 新增：自动反思 <<<
        if cfg.get("evolving", {}).get("enabled", False) and task_log.ground_truth:
            from ..evolving.reflector import auto_reflect_after_task
            from ..evolving.experience_store import ExperienceStore
            store = ExperienceStore(cfg.evolving.experience_file)
            await auto_reflect_after_task(task_log, cfg, store)

        log_file_path = task_log.save()
        return final_summary, final_boxed_answer, log_file_path
```

## 6. 配置扩展

```yaml
# conf/config.yaml
evolving:
  enabled: false
  experience_file: "../../data/experiences.jsonl"
  max_experiences: 5
  # 新增
  reflection_model: ""          # 反思用模型，空则用主模型
  auto_reflect: true            # 是否在 pipeline 中自动触发反思
```

## 7. 测试要点

- 字段映射修复：验证 trace_summary 不再返回 "(no execution trace available)"
- 工具提取：从真实 task_log 中正确提取 tools_used
- LLM 调用：验证非 OpenAI client 也能正常工作
- 自动触发：pipeline 完成后经验自动写入 ExperienceStore
- 异常安全：反思失败不影响 pipeline 返回值
- 反思输出符合完整 Experience schema
