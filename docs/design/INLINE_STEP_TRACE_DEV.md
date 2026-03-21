# Inline Step Trace 开发文档

> **模块代号**: IST (Inline Step Trace)  
> **基线项目**: EvoAgent v1.0 (多路径系统已实现)  
> **核心理念**: 在运行时每一步留下结构化痕迹，路径执行完毕自动生成摘要，反思和进化只读摘要不读原始 log，实现零额外 API 调用的 97% token 压缩  
> **分支**: `main`  
> **创建日期**: 2026-03-20  
> **最后更新**: 2026-03-20  
> **前置文档**: `EVOAGENT_DESIGN.md` 第 12 章, `STRATEGY_EVOLVE_ARCHITECTURE.md` 第 11 章  
> **设计参考**: 现有 `reflector.py` 的 `_extract_trace_summary()`, 现有 `task_logger.py` 的 `step_logs` 格式

---

## 1. 架构总览

```
Agent 每步执行
    │
    ├─── 工具调用 ─→ TracingToolWrapper ─→ 自动提取 key_info (~80 chars)
    │                       │
    │                       ▼
    │               StepTraceCollector.record_tool_call()
    │
    ├─── 模型输出 ─→ ConclusionExtractor ─→ 解析 <conclusion> 标签
    │                       │
    │                       ▼
    │               StepTraceCollector.record_conclusion()
    │
    ... (重复 N 步)
    │
    ▼
Path 执行完毕
    │
    ▼
StepTraceCollector.finalize()
    │
    ├── L0: PathSummary (答案 + 置信度)                    ~30 tokens
    ├── L1: PathDigest  (推理链 + 关键发现 + 全部 trace)   ~300-400 tokens
    └── L2: 原始 step_logs 引用                            ~5,000-15,000 tokens (按需)
    │
    ▼
DigestStore 写入 (本地 JSON / OpenViking)
    │
    ▼
Reflector / Evolver 读 L1 (不读原始 log)
```

---

## 2. 现状问题与目标

### 2.1 现状数据 (基于 logs/futurex_cat10_evolved/ 实测)

| 文件 | 步数 | step_logs 原始 | message_history | Reflector 截取 |
|------|------|---------------|-----------------|---------------|
| task_69493a09 path0 | 54 步 | ~3,903 tokens | ~12,885 tokens | ~598 tokens |
| task_69493cb1 path1 | 80 步 | ~6,760 tokens | ~17,891 tokens | ~598 tokens |
| task_69493a09 path2 | 70 步 | ~5,157 tokens | ~14,218 tokens | ~601 tokens |

### 2.2 核心矛盾

- **读 message_history**：~15,000 tokens/路径，太贵
- **Reflector 截取 step_logs**：~600 tokens/路径，丢失推理链和关键结论
- **事后用 LLM 生成摘要**：多一次 API 调用，增加成本和延迟

### 2.3 目标

| 指标 | 目标值 |
|------|--------|
| 反思输入 token | ≤400 tokens/路径 (vs 现在 600-15,000) |
| 额外 API 调用 | 0 次 |
| 信息完整度 | ≥80% (覆盖推理链 + 关键发现 + 潜在问题) |
| Agent 答案影响 | 零影响 (不修改 Agent 核心逻辑) |
| 原有测试回归 | 37 个单元测试全部通过 |

---

## 3. 功能清单与编号

### 3.1 第一层：运行时痕迹采集 (Run-time Tracing)

| 编号 | 功能名称 | 描述 | 状态 | 优先级 |
|------|---------|------|------|--------|
| **IST-001** | StepTrace 数据结构 | 单步痕迹记录：step / action / query / key_info / conclusion / confidence | ✅ 已完成 | P0 |
| **IST-002** | TracingToolWrapper | 包装现有 ToolManager，每次工具调用后自动提取 key_info (≤80 chars) | ✅ 已完成 | P0 |
| **IST-003** | key_info 提取策略 — 搜索 | 搜索结果取第一条 title + snippet | ✅ 已完成 | P0 |
| **IST-004** | key_info 提取策略 — 网页浏览 | 网页取标题 + 首段摘要 | ✅ 已完成 | P0 |
| **IST-005** | key_info 提取策略 — 代码执行 | stdout 最后几行 | ✅ 已完成 | P0 |
| **IST-006** | key_info 提取策略 — 兜底 | 未知工具类型截取前 80 字符 | ✅ 已完成 | P1 |
| **IST-007** | ConclusionExtractor | 从 Agent 输出中解析 `<conclusion>` 和 `<confidence>` XML 标签 | ✅ 已完成 | P0 |
| **IST-008** | System Prompt 注入 | Agent system prompt 末尾追加 trace 输出要求（每步输出 conclusion + confidence 标签） | ✅ 已完成 | P0 |
| **IST-009** | 标签清理 | 从 Agent 输出中移除 trace 标签，不影响下游显示 | ✅ 已完成 | P1 |
| **IST-010** | StepTraceCollector | 收集器：记录 tool_call → 补填 conclusion → 维护步骤序号 | ✅ 已完成 | P0 |
| **IST-011** | Collector 孤立 conclusion 处理 | 非 tool-use 时的 conclusion 自动创建 action="reason" 步骤 | ✅ 已完成 | P1 |
| **IST-012** | Collector Token 累计 | 每步记录 token 消耗，汇总到路径级 | ✅ 已完成 | P2 |

### 3.2 第二层：路径摘要生成 (Path Digest)

| 编号 | 功能名称 | 描述 | 状态 | 优先级 |
|------|---------|------|------|--------|
| **IST-101** | PathDigest 数据结构 | 路径摘要：answer / confidence / traces / reasoning_chain / key_findings / potential_issues | ✅ 已完成 | P0 |
| **IST-102** | Collector.finalize() | 路径执行完毕 → 自动汇总生成 PathDigest | ✅ 已完成 | P0 |
| **IST-103** | reasoning_chain 自动拼接 | 从 conclusions 中取首/中/尾三条拼接为推理链 (2-3 句话) | ✅ 已完成 | P0 |
| **IST-104** | key_findings 自动提取 | 从 key_info 中提取有价值的发现 (≤5 条) | ✅ 已完成 | P1 |
| **IST-105** | potential_issues 自动识别 | 低置信度步骤 + 空搜索结果 → 标记为潜在问题 (≤3 条) | ✅ 已完成 | P1 |
| **IST-106** | L0/L1/L2 分层输出 | PathDigest 支持三层导出：L0 (~30 tokens) / L1 (~400 tokens) / L2 (完整) | ✅ 已完成 | P0 |
| **IST-107** | TaskDigestBundle | 任务级聚合：所有路径的 PathDigest + 投票结果 + 正确性 | ✅ 已完成 | P1 |
| **IST-108** | 多路径对比视图 | TaskDigestBundle.get_comparison_view() 供进化模块使用 (~800-1200 tokens for 5 paths) | ✅ 已完成 | P1 |

### 3.3 第三层：存储与检索 (Digest Store)

| 编号 | 功能名称 | 描述 | 存储位置 | 状态 | 优先级 |
|------|---------|------|---------|------|--------|
| **IST-201** | DigestStore 接口定义 | save / load / query 的统一接口 | — | ✅ 已完成 | P0 |
| **IST-202** | 本地 JSON 后端 | 降级模式：PathDigest → `data/digests/task_xxx_pathN.json` | `data/digests/` | ✅ 已完成 | P0 |
| **IST-203** | OpenViking 后端 | 正式模式：PathDigest → `viking://agent/memories/task_digests/` | `viking://agent/memories/task_digests/` | ⏭️ P2 延后 | P2 |
| **IST-204** | 按层级加载 | `load(task_id, path_index, depth="l0"|"l1"|"l2")` 按需返回不同详细度 | — | ✅ 已完成 | P0 |
| **IST-205** | TaskBundle 存储 | 任务级聚合保存为 `task_xxx_bundle.json` | `data/digests/` | ✅ 已完成 | P1 |
| **IST-206** | 对比视图加载 | `load_task_comparison(task_id)` 返回格式化的多路径对比文本 | — | ✅ 已完成 | P1 |

### 3.4 第四层：下游集成 (Integration)

| 编号 | 功能名称 | 描述 | 修改文件 | 状态 | 优先级 |
|------|---------|------|---------|------|--------|
| **IST-301** | multi_path.py 集成 — Collector 创建 | 每条路径执行前创建 StepTraceCollector | `multi_path.py` | ❌ 待开发 | P0 |
| **IST-302** | multi_path.py 集成 — Wrapper 包装 | 用 TracingToolWrapper 包装 ToolManager | `multi_path.py` | ❌ 待开发 | P0 |
| **IST-303** | multi_path.py 集成 — conclusion 提取 | 路径执行完后从 message_history 提取 conclusions | `multi_path.py` | ❌ 待开发 | P0 |
| **IST-304** | multi_path.py 集成 — digest 保存 | finalize() 后保存 PathDigest 和 TaskDigestBundle | `multi_path.py` | ❌ 待开发 | P0 |
| **IST-305** | reflector.py 改造 — 读 digest | 反思时优先读 L1 digest，不读原始 log | `reflector.py` | ❌ 待开发 | P0 |
| **IST-306** | reflector.py 改造 — 降级兼容 | digest 不存在时自动降级读原始 step_logs（兼容旧数据） | `reflector.py` | ❌ 待开发 | P1 |
| **IST-307** | reflector.py 改造 — 新版 prompt | 针对结构化 trace 优化的反思 prompt 模板 | `reflector.py` | ❌ 待开发 | P1 |
| **IST-308** | system prompt 注入点 | 在 `_build_system_prompt()` 中追加 TRACE_INSTRUCTION | `multi_path.py` | ❌ 待开发 | P0 |

### 3.5 测试与评估

| 编号 | 功能名称 | 描述 | 状态 | 优先级 |
|------|---------|------|------|--------|
| **IST-401** | 单元测试 — StepTrace 数据结构 | 创建、序列化、反序列化 | ✅ 已完成 | P0 |
| **IST-402** | 单元测试 — PathDigest 三层输出 | L0/L1/L2 字段正确性和 token 大小 | ✅ 已完成 | P0 |
| **IST-403** | 单元测试 — ConclusionExtractor | 标准提取 / 无标签 / 畸形标签 / 标签移除 | ✅ 已完成 | P0 |
| **IST-404** | 单元测试 — TracingToolWrapper | 4 种 key_info 提取策略 + 兜底 | ✅ 已完成 | P0 |
| **IST-405** | 单元测试 — StepTraceCollector | 记录 → 补填 → finalize → 汇总 | ✅ 已完成 | P0 |
| **IST-406** | 单元测试 — DigestStore 读写 | 保存 / 加载 / 层级过滤 / 文件不存在 | ✅ 已完成 | P0 |
| **IST-407** | 集成测试 — 完整单路径 trace | 真实工具执行 → 生成 PathDigest → 验证内容 | ✅ 已完成 | P1 |
| **IST-408** | 集成测试 — 多路径 bundle | 多路径执行 → TaskDigestBundle → 对比视图 | ✅ 已完成 | P1 |
| **IST-409** | 集成测试 — Reflector 读 digest | Reflector 从 digest 构建反思输入 | ❌ 待开发 | P1 |
| **IST-410** | 集成测试 — Reflector 降级 | digest 不存在时走旧路径读原始 log | ❌ 待开发 | P1 |
| **IST-411** | 回归测试 — 现有测试全通过 | 加入 IST 后 37 个已有单元测试不受影响 | ✅ 已完成 | P0 |
| **IST-412** | 回归测试 — Agent 答案不变 | TracingWrapper 不影响 Agent 的最终输出 | ✅ 已完成 | P0 |
| **IST-413** | 回归测试 — step_logs 仍生成 | 原始 step_logs 格式不变，仍然写入 | ❌ 待开发 | P0 |
| **IST-414** | 回归测试 — 零额外 API 调用 | 加入 IST 后无新增 LLM API 调用 | ✅ 已完成 | P0 |
| **IST-415** | 性能测试 — token 压缩率 | 反思输入 token 对比：旧 vs 新 | ⏭️ 需集成后测 | P1 |
| **IST-416** | 性能测试 — Wrapper 延迟 | TracingToolWrapper 增加的延迟 ≤5ms/step | ⏭️ 需集成后测 | P2 |
| **IST-417** | 性能测试 — conclusion 输出率 | cat10 上 conclusion 标签的实际输出比例 ≥70% | ⏭️ 需真实LLM | P1 |
| **IST-418** | 性能测试 — digest 文件大小 | PathDigest JSON ≤5KB/path | ⏭️ 需集成后测 | P2 |
| **IST-419** | 真实数据验证 | 用 logs/futurex_cat10_evolved/ 的 5 个 log 模拟 trace 提取，验证 L1 < 500 tokens | ⏭️ 需真实数据 | P1 |

---

## 4. IST 驱动的数据架构

### 4.1 数据流对比

```
=== 改造前 ===
Agent 执行 → step_logs (原始) → Reflector 截取 (max15步×300字符)
                                        ↓
                                ~600 tokens, 丢失推理链
                                        ↓
                                   反思 prompt


=== 改造后 ===
Agent 执行 → step_logs (原始, 仍保留)
     │
     ├── TracingToolWrapper → key_info (每步)
     ├── ConclusionExtractor → conclusion (每步)
     │
     ▼
StepTraceCollector → PathDigest
     │
     ├── L0 (~30 tokens)  → 投票、快速统计
     ├── L1 (~400 tokens) → 反思、进化              ← 默认消费层
     └── L2 (完整)         → 深度分析 (按需)
     │
     ▼
DigestStore (本地 JSON / OpenViking)
     │
     ▼
Reflector 读 L1 → 反思 prompt
```

### 4.2 存储目录结构

```
data/
├── digests/                               ← IST-202: 本地 JSON 后端
│   ├── task_69493a09_path0.json            PathDigest (L2 完整版)
│   ├── task_69493a09_path1.json
│   ├── task_69493a09_path2.json
│   ├── task_69493a09_bundle.json           TaskDigestBundle
│   └── ...
│
logs/                                      ← 不修改，原始 log 仍然写入
│   ├── task_69493a09_path0_breadth_first.json
│   └── ...
```

**OpenViking 映射** (IST-203):

```
viking://
├── agent/
│   └── memories/
│       └── task_digests/                  ← IST-203
│           ├── .abstract                   L0: "共 150 条路径摘要, 平均 8.3 步"
│           ├── .overview                   L1: 按题型/策略的摘要统计
│           ├── task_69493a09_path0.json     L2: 完整 PathDigest
│           └── task_69493a09_bundle.json    TaskDigestBundle
```

### 4.3 分层加载策略 (Token 成本控制)

| 场景 | 加载层级 | Token 消耗 | 说明 |
|------|---------|-----------|------|
| 投票 / 快速统计 | L0 | ~30/路径 | 只要 answer + confidence |
| Reflector 反思 | L1 | ~400/路径 | 推理链 + 关键发现 + 全部 trace |
| 多路径对比反思 | L1 × N | ~2,000 (5路径) | 所有路径的 L1 拼接 |
| 进化模块深度分析 | L2 | ~2,000/路径 | 完整 trace + 时间戳 + 元数据 |
| 调试 / 可视化 | 原始 log | ~15,000/路径 | 不走 IST，直接读 logs/ |

---

## 5. StepTrace 数据结构

### 5.1 单步痕迹

```python
@dataclass
class StepTrace:
    step: int                          # 步骤序号 (1-indexed)
    action: str                        # 动作类型: search | browse | calculate | reason | tool_call
    query: str                         # 输入 (搜索词 / URL / 表达式)
    key_info: Optional[str] = None     # 工具层自动提取 (≤80 chars)    ← IST-002~006
    conclusion: Optional[str] = None   # 模型当步结论 (≤120 chars)     ← IST-007
    confidence: Optional[float] = None # 当前置信度 0.0-1.0            ← IST-007
    timestamp: Optional[float] = None  # Unix timestamp
    tool_name: Optional[str] = None    # 具体工具名
    tokens_used: Optional[int] = None  # 该步 token 消耗              ← IST-012
```

### 5.2 路径摘要

```python
@dataclass
class PathDigest:
    # 身份
    task_id: str
    path_index: int
    island_id: Optional[str] = None
    strategy_name: Optional[str] = None
    
    # 执行结果
    answer: str = ""
    confidence: str = "medium"         # high / medium / low
    total_steps: int = 0
    total_tokens: int = 0
    
    # 步骤痕迹
    traces: List[StepTrace] = field(default_factory=list)
    
    # 自动汇总 (IST-103~105)
    reasoning_chain: str = ""          # 首/中/尾三条 conclusion 拼接
    key_findings: List[str] = field(default_factory=list)   # ≤5 条
    potential_issues: List[str] = field(default_factory=list) # ≤3 条
    tools_used: List[str] = field(default_factory=list)
    
    # 时间
    start_time: Optional[float] = None
    end_time: Optional[float] = None
```

### 5.3 任务级聚合

```python
@dataclass
class TaskDigestBundle:
    task_id: str
    question: str
    question_type: Optional[str] = None
    ground_truth: Optional[str] = None
    
    path_digests: List[PathDigest] = field(default_factory=list)
    
    voted_answer: Optional[str] = None
    vote_method: str = "majority"
    was_correct: Optional[bool] = None
```

### 5.4 示例：8 步路径的完整 trace

```json
{
  "task_id": "69493a09",
  "path_index": 0,
  "strategy_name": "breadth_first",
  "answer": "Hopfield & Hinton",
  "confidence": "high",
  "total_steps": 8,
  "total_tokens": 12345,
  "reasoning_chain": "Two Nobel winners confirmed → Official source verified names → Both pioneered neural network theory",
  "key_findings": [
    "Hopfield & Hinton won 2024 Nobel Physics",
    "John Hopfield (Princeton), Geoffrey Hinton (U of Toronto)",
    "Prize: 11M SEK shared equally"
  ],
  "potential_issues": [],
  "tools_used": ["web_search", "browse_webpage", "python_exec"],
  "traces": [
    {"step": 1, "action": "search", "query": "2024 Nobel Physics laureates",
     "key_info": "Hopfield & Hinton won for neural network foundations",
     "conclusion": "Two winners confirmed, both from AI/neural-net domain"},
    {"step": 2, "action": "browse", "query": "nobelprize.org/prizes/physics/2024",
     "key_info": "John Hopfield (Princeton), Geoffrey Hinton (U of Toronto)",
     "conclusion": "Official source confirms names and affiliations"},
    {"step": 3, "action": "search", "query": "Hopfield network contribution",
     "key_info": "1982 Hopfield network, associative memory, energy-based model",
     "conclusion": "Hopfield's key contribution is the Hopfield network for associative memory"},
    {"step": 4, "action": "search", "query": "Hinton backpropagation deep learning",
     "key_info": "Backpropagation popularization, Boltzmann machines, dropout",
     "conclusion": "Hinton is foundational to modern deep learning"},
    {"step": 5, "action": "reason", "query": "(synthesize findings)",
     "key_info": null,
     "conclusion": "Both laureates pioneered neural network theory enabling modern AI"},
    {"step": 6, "action": "search", "query": "Nobel Physics 2024 prize amount",
     "key_info": "11 million SEK (~$1.1M USD), shared equally",
     "conclusion": "Standard Nobel prize amount, split 50/50"},
    {"step": 7, "action": "calculate", "query": "11000000 / 2",
     "key_info": "5500000.0",
     "conclusion": "Each laureate receives 5.5 million SEK"},
    {"step": 8, "action": "reason", "query": "(formulate final answer)",
     "key_info": null,
     "conclusion": "High confidence answer ready: Hopfield & Hinton, shared prize"}
  ]
}
```

**L1 序列化大小**: ~380 tokens — 远低于原始 log 的 ~15,000 tokens。

---

## 6. TracingToolWrapper 提取策略

### 6.1 工具分类映射

```python
TOOL_ACTION_MAP = {
    # 搜索类
    "web_search": "search",
    "searching_with_google": "search",
    "duckduckgo_search": "search",
    "searching_with_sougou": "search",
    
    # 浏览类
    "browse_webpage": "browse",
    "read_webpage": "browse",
    "reading_content": "browse",
    
    # 代码执行类
    "python_exec": "calculate",
    "code_execution": "calculate",
    
    # 推理类
    "reasoning": "reason",
    "deep_think": "reason",
}
```

### 6.2 key_info 提取策略

| 工具类型 | 提取策略 | 最大长度 | 示例 |
|---------|---------|---------|------|
| **search** (IST-003) | 第一条结果的 title + snippet | 80 chars | `"Hopfield & Hinton won 2024 Nobel Physics for neural networks"` |
| **browse** (IST-004) | 页面标题 + 首段摘要 | 80 chars | `"Nobel Prize Physics 2024 \| Awarded for foundational discoveries"` |
| **calculate** (IST-005) | stdout 最后 2 行 | 80 chars | `"5500000.0"` |
| **reason** | 无工具返回，key_info = None | — | `null` |
| **兜底** (IST-006) | 截取前 80 字符 | 80 chars | `"(raw output truncated)"` |

### 6.3 query 提取策略

```python
def _extract_query(tool_name: str, arguments: dict) -> str:
    """从工具参数中提取查询内容，优先级: query > url > code > question > input"""
    for key in ["query", "url", "code", "question", "input"]:
        if key in arguments:
            return str(arguments[key])[:100]
    return str(arguments)[:100]
```

---

## 7. ConclusionExtractor 解析规则

### 7.1 System Prompt 注入内容

```
## Execution Trace Protocol

After each tool use, before deciding your next action, output:

<conclusion>One-sentence takeaway from this step (max 120 chars)</conclusion>
<confidence>0.0-1.0 your current confidence in the final answer</confidence>

Rules:
- conclusion: focus on what you LEARNED, not what you did
- confidence: how close you are to a reliable answer
- Output these after EVERY tool result
- These tags will be stripped from visible output
```

### 7.2 解析规则

```python
CONCLUSION_PATTERN = re.compile(r'<conclusion>(.*?)</conclusion>', re.DOTALL | re.IGNORECASE)
CONFIDENCE_PATTERN = re.compile(r'<confidence>([\d.]+)</confidence>', re.IGNORECASE)
```

| 输入 | conclusion | confidence |
|------|-----------|-----------|
| `"blah <conclusion>Found X</conclusion> <confidence>0.8</confidence> blah"` | `"Found X"` | `0.8` |
| `"no tags here"` | `None` | `None` |
| `"<conclusion>Unclosed tag"` | `None` | `None` |
| `"<conclusion></conclusion>"` | `""` → 视为 `None` | `None` |
| `"<CONCLUSION>Case insensitive</CONCLUSION>"` | `"Case insensitive"` | `None` |

### 7.3 降级策略

模型不输出 conclusion 标签时：
- StepTrace.conclusion = None
- reasoning_chain 降级为用 key_info 拼接（质量降低但不为空）
- 反思仍然可以基于 key_info 工作

---

## 8. StepTraceCollector 收集流程

### 8.1 生命周期

```
创建 (per-path)
    │
    ▼
record_tool_call()  ← TracingToolWrapper 调用，记录 action/query/key_info
    │
    ▼
record_conclusion() ← Agent 输出后处理调用，补填 conclusion/confidence
    │
    ▼
record_tokens()     ← 可选，累计 token 消耗
    │
    ... (重复 N 步)
    │
    ▼
finalize(answer, confidence) → PathDigest
    │
    ├── _build_reasoning_chain()     从 conclusions 取首/中/尾 3 条
    ├── _extract_key_findings()      从 key_info 取有效发现 ≤5 条
    ├── _extract_issues()            低置信度 + 空搜索 → 潜在问题 ≤3 条
    └── 去重 tools_used
```

### 8.2 pending trace 匹配机制

```
时间线:
  t1: record_tool_call(search, "query X", key_info="found Y")  → 创建 trace, 标记为 pending
  t2: record_conclusion("Y confirms Z", 0.7)                    → 补填到 pending trace
  t3: record_tool_call(browse, "url A", key_info="page says B") → 新 trace, 标记为 pending
  t4: record_conclusion("B supports Z", 0.85)                   → 补填到 pending trace
  t5: (Agent 直接推理，无 tool call)
  t6: record_conclusion("Final synthesis", 0.9)                  → 无 pending → 创建 reason 步骤
```

### 8.3 reasoning_chain 构建规则

```python
def _build_reasoning_chain(self) -> str:
    conclusions = [t.conclusion for t in self._traces if t.conclusion and len(t.conclusion) > 10]
    
    if not conclusions:
        # 降级：用 key_info 拼接
        key_infos = [t.key_info for t in self._traces if t.key_info and len(t.key_info) > 15]
        return " → ".join(key_infos[:3]) if key_infos else "(no reasoning chain captured)"
    
    if len(conclusions) <= 3:
        return " → ".join(conclusions)
    
    # 取首、中、尾
    return " → ".join([
        conclusions[0],
        conclusions[len(conclusions) // 2],
        conclusions[-1],
    ])
```

---

## 9. DigestStore 存储接口

### 9.1 接口定义

```python
class DigestStore:
    async def save_path_digest(self, digest: PathDigest) -> None
    async def save_task_bundle(self, bundle: TaskDigestBundle) -> None
    async def load_path_digest(self, task_id: str, path_index: int, depth: str = "l1") -> Optional[dict]
    async def load_task_comparison(self, task_id: str) -> Optional[str]
```

### 9.2 L0/L1/L2 返回字段

| 层级 | 包含字段 | 估算 Token |
|------|---------|-----------|
| **L0** | answer, confidence, total_tokens, total_steps | ~30 |
| **L1** | L0 + strategy_name, reasoning_chain, key_findings, potential_issues, tools_used, traces (简化版) | ~300-400 |
| **L2** | L1 + traces (完整版含 timestamp/tokens_used), start_time, end_time | ~600-800 |

### 9.3 文件命名规范

```
{task_id}_path{path_index}.json     → PathDigest
{task_id}_bundle.json               → TaskDigestBundle
```

---

## 10. 下游集成改造

### 10.1 multi_path.py 改造 (IST-301~304, IST-308)

```python
# === 改造前 ===
async def _run_single_path(cfg, task, path_index, strategy, ...):
    tool_manager = ToolManager(...)
    orchestrator = Orchestrator(cfg, tool_manager, ...)
    result = await orchestrator.run(task)
    return result

# === 改造后 ===
async def _run_single_path(cfg, task, path_index, strategy, ...):
    # IST-301: 创建 Collector
    collector = StepTraceCollector(
        task_id=task.id, path_index=path_index,
        island_id=strategy.get("island_id"),
        strategy_name=strategy["name"],
    )
    
    # IST-302: 包装 ToolManager
    tool_manager = ToolManager(...)
    tracing_wrapper = TracingToolWrapper(tool_manager, collector)
    
    # IST-308: system prompt 追加 TRACE_INSTRUCTION
    system_prompt = _build_system_prompt(base_prompt, strategy["prompt_suffix"])
    
    orchestrator = Orchestrator(cfg, tracing_wrapper, system_prompt=system_prompt, ...)
    result = await orchestrator.run(task)
    
    # IST-303: 从 message_history 提取 conclusions
    _extract_conclusions_from_history(orchestrator.message_history, collector)
    
    # IST-304: finalize 并保存
    digest = collector.finalize(answer=result.answer, final_confidence=result.confidence or "medium")
    await digest_store.save_path_digest(digest)
    
    return result, digest
```

### 10.2 reflector.py 改造 (IST-305~307)

```python
# === 改造前 ===
trace_summary = _extract_trace_summary(task_log)  # ~600 tokens, 丢失推理链

# === 改造后 ===
# IST-305: 优先读 digest
digest = await digest_store.load_path_digest(task_id, path_index, depth="l1")

if digest:
    # IST-307: 新版 prompt，利用结构化字段
    reflection_input = REFLECTION_PROMPT_V2.format(
        trace_summary=json.dumps(digest["traces"], ensure_ascii=False),
        reasoning_chain=digest["reasoning_chain"],
        key_findings=", ".join(digest["key_findings"]),
        potential_issues=", ".join(digest["potential_issues"]),
        ...
    )
else:
    # IST-306: 降级读原始 log
    reflection_input = _build_reflection_input_legacy(task_log)
```

---

## 11. 降级策略

| 故障场景 | 概率 | 降级方式 | 影响 |
|---------|------|---------|------|
| 模型不输出 `<conclusion>` 标签 | 中 | conclusion=None，reasoning_chain 用 key_info 拼接 | 信息完整度从 80% 降到 50%，但不影响执行 |
| 工具返回格式异常 | 低 | `_extract_default_key_info()` 截取前 80 字符 | key_info 质量下降，但保证不为空 |
| DigestStore 写入失败 | 极低 | 不阻塞主流程，Reflector 走旧路径读原始 log | 等同于 IST 未启用 |
| Collector 内部异常 | 极低 | try-except 包裹，返回空 PathDigest | digest 缺失，触发 IST-306 降级 |

---

## 12. 数据流 (完整版)

```
输入任务
    │
    ▼
┌─────────────────────────────────┐
│ EA-CTL: 调度中心                 │
│ (现有 multi_path.py)            │
│                                 │
│ 1. 接收任务                      │
│ 2. 选择策略                      │
│ 3. 创建 N 个 StepTraceCollector  │  ← IST-301
│ 4. 包装 N 个 TracingToolWrapper  │  ← IST-302
│ 5. 注入 TRACE_INSTRUCTION        │  ← IST-308
│ 6. 分配路径                      │
└──────────────┬──────────────────┘
               │
     ┌─────────┼─────────┐
     │         │         │
     ▼         ▼         ▼
   Path0     Path1     Path2
   + Wrapper + Wrapper + Wrapper    ← IST-002 (每步 key_info)
   + Collector+ Collector+ Collector ← IST-010 (每步记录)
     │         │         │
     ▼         ▼         ▼
   完毕       完毕       完毕
     │         │         │
     ├── 提取 conclusions          ← IST-303
     ├── finalize() → PathDigest   ← IST-102
     └── save to DigestStore       ← IST-304
     │         │         │
     └─────────┼─────────┘
               │
     ┌─────────▼─────────┐
     │ EA-003/004: 投票   │  可读 L0 做加权
     └─────────┬─────────┘
               │
     ┌─────────▼─────────────────────────┐
     │ 最终答案                           │
     │ 保存 TaskDigestBundle             │  ← IST-205
     └─────────┬─────────────────────────┘
               │
     ┌─────────▼─────────────────────────┐
     │ Reflector (事后反思)               │
     │                                   │
     │ 读 L1 digest (~400 tokens/路径)    │  ← IST-305
     │ 而非原始 log (~15,000 tokens/路径) │
     │                                   │
     │ 如果 digest 不存在:                │  ← IST-306
     │   降级读原始 step_logs             │
     └───────────────────────────────────┘
```

---

## 13. 文件结构

### 13.1 新增文件

```
apps/miroflow-agent/src/
├── core/
│   ├── step_trace.py              # IST-001, IST-101, IST-107: 数据结构
│   ├── tracing_tool_wrapper.py    # IST-002~006: 工具层 key_info 提取
│   ├── conclusion_extractor.py    # IST-007, IST-009: 标签解析 + 清理
│   ├── step_trace_collector.py    # IST-010~012, IST-102~105: 收集 + finalize
│   └── digest_store.py            # IST-201~206: 存储 / 检索
└── tests/
    ├── test_step_trace.py         # IST-401, IST-402
    ├── test_conclusion_extractor.py # IST-403
    ├── test_tracing_wrapper.py    # IST-404
    ├── test_step_trace_collector.py # IST-405
    ├── test_digest_store.py       # IST-406
    ├── test_ist_integration.py    # IST-407~410
    └── test_ist_regression.py     # IST-411~414, IST-415~419
```

### 13.2 修改文件

```
apps/miroflow-agent/src/
├── core/
│   └── multi_path.py              # IST-301~304, IST-308: 集成 Collector/Wrapper
└── evolving/
    └── reflector.py               # IST-305~307: 读 digest 替代原始 log
```

### 13.3 不修改

```
apps/miroflow-agent/src/
├── core/
│   ├── orchestrator.py            # ReAct 循环不变
│   ├── pipeline.py                # 管道不变
│   └── streaming.py               # 流式输出不变
├── llm/                           # LLM 调用层不变
├── logging/
│   └── task_logger.py             # 原始 log 仍然生成，格式不变
└── ...

libs/miroflow-tools/               # 工具层不变 (Wrapper 在外层包装)
```

### 13.4 新增数据目录

```
data/
└── digests/                       # IST-202: PathDigest / TaskDigestBundle JSON 文件
```

---

## 14. 开发路线图

### Phase 1: 数据结构 + 提取器 (1 天)

- IST-001: StepTrace 数据结构
- IST-101, IST-106: PathDigest + L0/L1/L2
- IST-107: TaskDigestBundle
- IST-007, IST-009: ConclusionExtractor
- IST-401, IST-402, IST-403: 对应单元测试

**验收**: 所有数据结构可创建、序列化、分层输出；Extractor 正确处理 6 种输入场景

### Phase 2: 工具层包装 + 收集器 + 存储 (1 天)

- IST-002~006: TracingToolWrapper + 4 种提取策略 + 兜底
- IST-010~012: StepTraceCollector
- IST-102~105: finalize 汇总逻辑
- IST-201~206: DigestStore (本地 JSON)
- IST-404, IST-405, IST-406: 对应单元测试

**验收**: Wrapper 可包装真实工具；Collector 按序记录并正确汇总；Store 读写正常

### Phase 3: 集成 multi_path.py (1 天)

- IST-301~304: Collector 创建 → Wrapper 包装 → conclusion 提取 → digest 保存
- IST-308: system prompt 注入
- IST-411~414: 回归测试
- IST-407, IST-408: 集成测试

**验收**: 37 个已有测试全通过；Agent 答案不变；digest 文件生成

### Phase 4: 接入 Reflector (0.5 天)

- IST-305~307: Reflector 读 digest + 降级兼容 + 新版 prompt
- IST-409, IST-410: 集成测试

**验收**: 反思输入 token 下降 90%+；旧数据降级正常

### Phase 5: 验证 + 性能测试 (0.5 天)

- IST-415~419: 性能测试 + 真实数据验证
- 在 cat10 上完整运行，测量所有指标

**验收标准**:

| 指标 | 目标 | 测试编号 |
|------|------|---------|
| 反思 token 压缩率 | ≥90% | IST-415 |
| Wrapper 延迟 | ≤5ms/step | IST-416 |
| conclusion 标签输出率 | ≥70% | IST-417 |
| digest 文件大小 | ≤5KB/path | IST-418 |
| L1 token 量 | ≤500 tokens | IST-419 |
| 已有测试回归 | 37/37 通过 | IST-411 |
| Agent 答案影响 | 零 | IST-412 |

**总计**: ~4 天, 5 个新文件 + 2 个修改文件 + 7 个测试文件 + 19 个测试编号 (34+ 个测试用例)

---

## 15. Token 消耗对比 (预期效果)

### 15.1 单路径反思

| | 改造前 (原始 log) | 改造前 (Reflector 截取) | 改造后 (L1 digest) |
|---|---|---|---|
| Token 消耗 | ~15,000 | ~600 | **~400** |
| 信息完整度 | 100% (含噪音) | ~30% | **~80%** |
| 推理链 | 有 (淹没在噪音中) | 无 | **有 (结构化)** |
| 关键结论 | 有 (需人工找) | 无 | **有 (每步标注)** |
| 潜在问题 | 需要分析 | 无 | **有 (自动识别)** |

### 15.2 一轮 10 题 × 5 路径的反思

| | 改造前 | 改造后 | 节省 |
|---|---|---|---|
| 单路径反思 | 600 tokens × 50 路径 = 30,000 | 400 × 50 = 20,000 | 33% |
| 多路径对比反思 | 15,000 × 50 = 750,000 | 400 × 50 = 20,000 | **97%** |
| 进化模块 (读对比视图) | N/A | 1,200 × 10 = 12,000 | — |

### 15.3 成本估算 (GPT-4o-mini 价格)

| 场景 | 改造前 | 改造后 | 节省 |
|------|--------|--------|------|
| 一轮反思 (10 题 × 5 路径) | $0.075 | $0.002 | $0.073 |
| 100 轮累计 | $7.50 | $0.20 | **$7.30** |

---

## 16. 设计决策记录

| 编号 | 决策 | 备选方案 | 选择理由 | 日期 |
|------|------|---------|---------|------|
| IST-DD-01 | key_info 由工具层代码提取 | 让模型总结工具返回 | 代码提取 100% 可靠，不增加 token | 2026-03-20 |
| IST-DD-02 | conclusion 由模型 inline 输出 | 事后用小模型生成 | 模型本来就会总结，零额外 API 调用 | 2026-03-20 |
| IST-DD-03 | 用 XML 标签 `<conclusion>` | JSON / 特殊前缀 | XML 标签被主流 LLM 良好支持 | 2026-03-20 |
| IST-DD-04 | conclusion 缺失时降级不失败 | 强制要求必须输出 | 不同模型遵循度不同，降级保证鲁棒性 | 2026-03-20 |
| IST-DD-05 | 保留原始 step_logs | 只保留 digest | 原始 log 用于调试和可视化，成本只是磁盘 | 2026-03-20 |
| IST-DD-06 | L1 作为反思默认层级 | L0(太少) / L2(太多) | ~400 tokens 是信息密度和成本最优平衡点 | 2026-03-20 |
| IST-DD-07 | TracingWrapper 不截断工具返回 | 截断后传给 Agent | Agent 需要完整信息做决策，截断影响答案 | 2026-03-20 |
| IST-DD-08 | Collector 生命周期绑定单路径 | 全局单例 | 多路径并行需隔离，per-path 最安全 | 2026-03-20 |
| IST-DD-09 | reasoning_chain 取首/中/尾三条 | 取全部 | 3 条 ~60 tokens，控制 L1 大小 | 2026-03-20 |
| IST-DD-10 | key_findings 最多 5 条 | 无上限 | 控制 L1 大小，5 条覆盖关键信息 | 2026-03-20 |

---

## 17. 风险与缓解

| 风险 | 影响 | 概率 | 缓解措施 |
|------|------|------|---------|
| 模型不输出 conclusion 标签 | 中 (信息降级到 50%) | 中 | IST-DD-04 降级策略；IST-417 测量实际输出率；必要时换 prompt 格式 |
| key_info 提取策略不匹配新工具 | 低 | 低 | IST-006 兜底截取；新工具加入时扩展 extractor |
| TracingWrapper 影响工具性能 | 低 | 低 | IST-416 测量延迟 ≤5ms；wrapper 只做字符串操作 |
| digest 文件积累占用磁盘 | 低 | 中 | 每个 digest ≤5KB (IST-418)；可定期清理旧文件 |
| conclusion 标签与 Agent 输出冲突 | 低 | 极低 | IST-009 标签清理确保下游不受影响 |
| Reflector 新旧 prompt 效果差异 | 中 | 中 | IST-306 降级兼容；AB 测试对比新旧 prompt 反思质量 |

---

## 18. 术语表

| 术语 | 定义 |
|------|------|
| **StepTrace** | 单步执行痕迹，包含 action/query/key_info/conclusion |
| **key_info** | 工具层自动从返回结果中提取的关键信息 (≤80 chars) |
| **conclusion** | 模型在每步 tool use 后 inline 输出的一句话推理结论 (≤120 chars) |
| **PathDigest** | 一条路径的完整执行摘要，由所有 StepTrace 汇总生成 |
| **TaskDigestBundle** | 一个任务的所有路径摘要 + 投票结果 |
| **L0/L1/L2** | 分层加载深度：L0 最简 (~30 tokens) / L1 默认 (~400 tokens) / L2 完整 |
| **TracingToolWrapper** | 工具包装层，在不修改原始工具的前提下自动提取 key_info |
| **ConclusionExtractor** | 从 Agent 输出中解析 `<conclusion>` 标签的解析器 |
| **StepTraceCollector** | 收集器，管理一条路径的所有 StepTrace 并 finalize 生成 PathDigest |
| **DigestStore** | PathDigest 的持久化存储，支持本地 JSON 和 OpenViking 两种后端 |
| **降级** | 信息缺失时的兜底策略：conclusion 缺失降级为 key_info；digest 缺失降级为原始 log |
| **pending trace** | Collector 中已记录 tool_call 但尚未补填 conclusion 的 StepTrace |
