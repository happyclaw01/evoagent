# 修复报告：工具超时 + 数据泄漏

**日期**: 2026-03-17  
**Commit**: `1d29f6b`  
**分支**: `feature/serpapi-search`

---

## 问题 1：工具初始化超时导致路径无工具

### 现象

R3 测试中，Grammy 和票房两题的 3 条路径全部工具超时（搜索 0 次），只能靠 LLM 猜测，直接导致答错。R2 中也有部分路径超时，只是恰好有路径幸免。

日志特征：
```
WARNING - Timed out fetching tool definitions for main agent after 30s; continuing with empty tool list.
```

### 根因

`execute_multi_path_pipeline` 为每条路径创建独立的 ToolManager（EA-005 设计），每个 ToolManager 在 Orchestrator 里各自调用 `get_all_tool_definitions()`。这个方法对每个 MCP server 都启动一个子进程（`stdio_client`），连接、初始化、获取 tool list、断开。

3 条路径 × 3 个 MCP server = **9 个并发子进程启动**，在系统负载较高时很容易超过 30 秒超时限制。

### 修复

**文件**: `apps/miroflow-agent/src/core/multi_path.py`

在创建路径之前，用一个临时 ToolManager **预取一次** tool definitions，然后通过已有的 `tool_definitions` 参数传给所有路径：

```python
# 修复前：每条路径各自获取 tool definitions（9 个并发子进程）
for i in range(len(strategies)):
    path_tm = ToolManager(...)
    # → orchestrator 内部再调 get_all_tool_definitions() → 超时风险

# 修复后：预取一次，共享给所有路径
_prefetch_tm = ToolManager(...)
tool_definitions = await _prefetch_tm.get_all_tool_definitions()  # 1 次，3 个子进程
# → 传给所有路径，orchestrator 跳过重新获取
```

**安全性**：tool definitions 是纯 schema 数据（tool name、description、inputSchema），不含运行时状态。各路径的实际工具调用仍通过各自独立的 ToolManager 执行，不会串路径。

**容错**：如果预取失败，`tool_definitions` 设为 `None`，各路径回退到原有的独立获取行为。

---

## 问题 2：Agent 手动传 before_date 覆盖安全边界

### 现象

Benchmark runner 在 commit `c61fdde` 中设置了 `SEARCH_BEFORE_DATE = end_time - 1 day`，防止搜到解题当天的结果。但实际上 R3 的搜索日志显示 `before_date` 仍然是 `end_time` 当天（如 `2026-01-22`），和 R2 完全一样。

### 根因

Agent（LLM）从 prompt 中的 "resolve around 2026-01-22" 提取日期，在 tool call 参数中手动传入：
```json
{"q": "...", "before_date": "2026-01-22"}
```

ToolManager 的 auto-inject 逻辑是：
```python
if "before_date" not in arguments:  # ← agent 已经传了，跳过注入
    arguments["before_date"] = env_var
```

Agent 显式传的值**优先于**环境变量，`-1 day` 的安全边界被绕过。

### 修复

**文件**: `libs/miroflow-tools/src/miroflow_tools/manager.py`

环境变量 `SEARCH_BEFORE_DATE` 现在**始终覆盖** agent 传的 `before_date`：

```python
# 修复前：agent 传了就不注入
if tool_name in self._SEARCH_TOOLS and "before_date" not in arguments:
    ...

# 修复后：env var 始终覆盖
if tool_name in self._SEARCH_TOOLS:
    search_before_date = os.environ.get("SEARCH_BEFORE_DATE", "")
    if search_before_date:
        arguments = {**arguments, "before_date": search_before_date}  # 覆盖
```

如果 agent 传的值和 env var 不同，会打一条 override 日志便于调试。

---

## 影响评估

| 问题 | 影响范围 | 修复后预期 |
|------|---------|-----------|
| 工具超时 | R3 中 5 次超时，Grammy + 票房全军覆没 | 降到 0（预取只启 3 个子进程而非 9 个） |
| before_date 泄漏 | R2 的 CECOT、票房搜到了当天结果 | env var 强制覆盖，杜绝泄漏 |

### 预期对 R4 的影响

- 工具超时修复：Grammy、票房等题不再因为"没工具"而纯靠猜，准确率应该回升
- before_date 修复：搜索范围真正限制在 end_time - 1 天，R2 的 9/10 可能会降（因为那里有泄漏分），但这才是真实预测能力
- 两个修复组合后，R4 应该比 R3 (5/10) 好（工具恢复），但可能不如 R2 (9/10)（去掉泄漏分）

---

## 变更文件清单

| 文件 | 改动 | 行数 |
|------|------|------|
| `apps/miroflow-agent/src/core/multi_path.py` | 新增 `import os`；预取 tool definitions 逻辑 | +50 |
| `libs/miroflow-tools/src/miroflow_tools/manager.py` | `SEARCH_BEFORE_DATE` 强制覆盖 agent before_date | +10 -4 |
