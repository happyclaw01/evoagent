# MiroThinker 搜索工具逻辑详解

本文档详细说明三个核心搜索工具的搜索逻辑、输入输出、过滤规则和重试机制。

---

## 1. Google 搜索（searching_google_mcp_server）

**文件**: `libs/miroflow-tools/src/miroflow_tools/mcp_servers/searching_google_mcp_server.py`

### 架构特点

该工具是一个**两层架构**：上层 MCP Server 通过 stdio 协议调用底层 `serper_mcp_server` 子进程完成实际搜索。

```
Agent → searching_google_mcp_server（上层）
            ↓ stdio_client 子进程调用
        serper_mcp_server（底层，直接调 Serper HTTP API）
```

### 输入参数

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `q` | str | 必填 | 搜索关键词 |
| `gl` | str | `"us"` | 地区代码（ISO 3166-1 alpha-2），影响搜索结果地域优先级 |
| `hl` | str | `"en"` | 语言代码（ISO 639-1），影响摘要语言 |
| `location` | str | None | 城市级别位置，如 `"SoHo, New York, United States"` |
| `num` | int | 10 | 返回结果数量 |
| `tbs` | str | None | 时间过滤：`qdr:h`(小时), `qdr:d`(天), `qdr:w`(周), `qdr:m`(月), `qdr:y`(年) |
| `page` | int | 1 | 结果页码 |

### 搜索流程

```
1. 验证 SERPER_API_KEY 是否设置
2. 构建搜索参数 payload（q, gl, hl, num, page, autocorrect=False, 可选 location/tbs）
3. 启动 serper_mcp_server 子进程（通过 StdioServerParameters）
4. 通过 MCP ClientSession 调用子进程的 google_search 工具
5. 获取返回文本 → 断言非空
6. 调用 filter_google_search_result() 进行结果过滤
7. 返回过滤后的 JSON 字符串
```

### 结果过滤

根据环境变量控制，过滤搜索结果中的特定字段：

| 环境变量 | 效果 |
|---------|------|
| `REMOVE_SNIPPETS=true` | 移除 organic 和 peopleAlsoAsk 中的 `snippet` 字段 |
| `REMOVE_KNOWLEDGE_GRAPH=true` | 移除整个 `knowledgeGraph` 对象 |
| `REMOVE_ANSWER_BOX=true` | 移除整个 `answerBox` 对象 |

底层 `serper_mcp_server` 还会：
- 过滤 HuggingFace dataset/space URL
- 对 URL 进行解码（`decode_http_urls_in_dict`）

### 返回结果

返回 JSON 字符串，包含：
```json
{
  "organic": [
    {
      "title": "...",
      "link": "...",
      "snippet": "...",   // 可能被移除
      "date": "...",
      "position": 1
    }
  ],
  "knowledgeGraph": { ... },  // 可能被移除
  "answerBox": { ... },       // 可能被移除
  "peopleAlsoAsk": [ ... ],
  "relatedSearches": [ ... ],
  "searchParameters": { ... }
}
```

### 重试机制

- 最多重试 **3 次**
- 等待时间：指数退避 `min(2^retry_count, 60)` 秒
- 触发条件：任何异常（子进程调用失败、结果为空等）

### 附加工具（已注释，未启用）

- `wiki_get_page_content`: 获取 Wikipedia 页面内容
- `search_wiki_revision`: 搜索 Wikipedia 页面指定月份的修订历史
- `search_archived_webpage`: 搜索 Wayback Machine 的网页存档
- `scrape_website`: 通过 Jina.ai 抓取网页内容

---

## 2. Search & Scrape 组合工具（search_and_scrape_webpage）

**文件**: `libs/miroflow-tools/src/miroflow_tools/dev_mcp_servers/search_and_scrape_webpage.py`

### 架构特点

这是一个**增强版 Google 搜索工具**，直接调用 Serper HTTP API（不经过子进程），增加了日期过滤和智能引号重试功能。

```
Agent → search_and_scrape_webpage
            ↓ 直接 HTTP POST
        Serper API (google.serper.dev/search)
```

### 输入参数

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `q` | str | 必填 | 搜索关键词 |
| `gl` | str | `"us"` | 地区代码 |
| `hl` | str | `"en"` | 语言代码 |
| `location` | str | None | 城市级别位置 |
| `num` | int | 10 | 返回结果数量 |
| `tbs` | str | None | 时间过滤 |
| `page` | int | None | 结果页码 |
| `autocorrect` | bool | None | 是否自动纠正拼写 |
| `before_date` | str | None | **日期过滤**，格式 `YYYY-MM-DD`，排除该日期及之后发布的结果 |

### 搜索流程

```
1. 验证 SERPER_API_KEY 和查询词非空
2. 构建 payload 并调用 make_serper_request() 发送 HTTP POST
3. 从返回的 JSON 中提取 organic 结果
4. 过滤掉 HuggingFace dataset/space URL
5. 【智能引号重试】如果无结果且查询含引号 → 去掉引号重新搜索
6. 【日期过滤】如果指定了 before_date → 过滤掉 date >= before_date 的结果
7. URL 解码（decode_http_urls_in_dict）
8. 返回结果字典
```

### 核心特性详解

#### 智能引号重试

```python
# 如果查询含引号且无结果，自动去引号重试
if not organic_results and '"' in original_query:
    query_without_quotes = original_query.replace('"', "").strip()
    organic_results, search_params = await perform_search(query_without_quotes)
```

**场景**：用户搜索 `"exact phrase match"` 但没有精确匹配的结果时，自动退化为普通搜索。

#### 日期过滤

```python
def _filter_results_by_date(results, before_date):
    cutoff = datetime.strptime(before_date, "%Y-%m-%d")
    for item in results:
        item_date = _parse_serper_date(item.get("date", ""))
        if item_date and item_date >= cutoff:
            continue  # 排除
        filtered.append(item)  # 保留（包括无日期的结果）
```

- 支持解析 Serper 返回的日期格式：`"Jan 18, 2026"`, `"April 6, 2025"`, `"2025-01-01"`
- **无日期的结果会被保留**（不会误杀）

#### URL 过滤

过滤两类 URL：
1. **HuggingFace**: `huggingface.co/datasets` 和 `huggingface.co/spaces`（防止直接获取答案数据）
2. **预测市场**（定义了黑名单但在此工具中仅定义未使用，在 Jina 工具中使用）:
   - manifold.markets, polymarket.com, metaculus.com, predictit.org
   - kalshi.com, futuur.com, insightprediction.com, smarkets.com

### 返回结果

```json
{
  "organic": [
    {
      "title": "结果标题",
      "link": "https://example.com",
      "snippet": "结果摘要...",
      "date": "Jan 18, 2026",
      "position": 1
    }
  ],
  "searchParameters": {
    "q": "搜索词",
    "gl": "us",
    "hl": "en",
    "num": 10,
    "type": "search"
  }
}
```

失败时返回：
```json
{
  "success": false,
  "error": "错误信息",
  "results": []
}
```

### 重试机制

使用 `tenacity` 库装饰 `make_serper_request()`：
- 最多 **3 次**尝试
- 等待：指数退避，最小 4 秒，最大 10 秒
- 触发条件：`httpx.ConnectError`, `httpx.TimeoutException`, `httpx.HTTPStatusError`

---

## 3. Jina 抓取 + LLM 摘要（jina_scrape_llm_summary）

**文件**: `libs/miroflow-tools/src/miroflow_tools/dev_mcp_servers/jina_scrape_llm_summary.py`

### 架构特点

这是一个**两步流水线**工具：先用 Jina.ai 抓取网页内容，再用 LLM 从内容中提取指定信息。

```
Agent → scrape_and_extract_info
            ↓ 步骤1: HTTP GET
        Jina.ai API (r.jina.ai/{url}) → 获取网页文本
            ↓ 步骤2: HTTP POST
        LLM API (SUMMARY_LLM_BASE_URL) → 提取指定信息
```

### 输入参数

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `url` | str | 必填 | 要抓取的 URL，支持网页、PDF、代码文件等 |
| `info_to_extract` | str | 必填 | 要提取的具体信息（通常是一个问题） |
| `custom_headers` | Dict | None | 自定义请求头 |

### 完整处理流程

```
1. 验证 URL 不是 HuggingFace dataset/space → 是则直接拒绝
2. 【步骤1: Jina 抓取】
   a. 检查 JINA_API_KEY
   b. 避免重复 Jina URL 前缀（防止 https://r.jina.ai/https://r.jina.ai/...）
   c. 发送 GET 请求到 Jina API
   d. 处理各种异常（超时、连接错误、HTTP 错误）
   e. 检查余额不足错误（InsufficientBalanceError）
   f. 截断内容到 max_chars（默认 409,600 字符 ≈ 400KB）
   g. 统计内容行数、字符数等
3. 【预测市场保护】
   如果 URL 属于预测市场 → 剥离 resolution/settlement 信息
4. 【步骤2: LLM 提取】
   a. 构建 prompt（EXTRACT_INFO_PROMPT 模板）
   b. 根据模型类型构建不同 payload：
      - GPT 系列：使用 max_completion_tokens
      - GPT-5：额外添加 service_tier="flex", reasoning_effort="minimal"（省钱）
      - 其他模型：使用 max_tokens, temperature=1.0
   c. 发送 POST 请求到 LLM API
   d. 处理上下文长度超限 → 自动截断内容末尾 40K*attempt 字符重试
   e. 检测重复输出（末尾 50 字符重复 >5 次）→ 重试
   f. 解析响应，提取 choices[0].message.content
5. 组合结果返回
```

### 核心特性详解

#### 预测市场保护

对来自预测市场网站的内容，用正则表达式剥离 resolution 信息：

```python
_RESOLUTION_PATTERNS = re.compile(
    r"(?i)"
    r"(resolved?\s+(yes|no|n/?a|mkt|prob))"      # "Resolved YES"
    r"|(resolution\s*:\s*(yes|no|n/?a|mkt|prob))" # "Resolution: NO"
    r"|(this\s+market\s+(has\s+)?resolved)"        # "This market has resolved"
    r"|(resolved\s+to\s+)"                         # "Resolved to ..."
    r"|(settlement\s*:\s*)"                        # "Settlement: ..."
    r"|(final\s+outcome\s*:\s*)"                   # "Final outcome: ..."
)
```

受保护的域名：manifold.markets, polymarket.com, metaculus.com, predictit.org, kalshi.com, futuur.com, insightprediction.com, smarkets.com

#### LLM 提取 Prompt

```
You are given a piece of content and the requirement of information to extract.
Your task is to extract the information specifically requested.

INFORMATION TO EXTRACT:
{info_to_extract}

INSTRUCTIONS:
1. Extract the information relevant to the focus above.
2. If the exact information is not found, extract the most closely related details.
3. Be specific and include exact details when available.
4. Clearly organize the extracted information for easy understanding.
5. Do not include general summaries or unrelated content.
6. CRITICAL: 不得提取预测市场的 resolution/settlement 结果。
7. TIME CONSTRAINT: 如果提取要求含时间限制，只提取该日期之前的信息。

CONTENT TO ANALYZE:
{content}
```

#### 上下文超限自动截断

当 LLM 返回 "exceeds the model's maximum context length" 时：
```python
# 每次重试多截断 40K 字符
prompt = get_prompt_with_truncation(
    info_to_extract, content,
    truncate_last_num_chars=40960 * attempt  # 第1次截40K，第2次截80K...
)
```

### 返回结果

```json
{
  "success": true,
  "url": "https://example.com/article",
  "extracted_info": "LLM 提取出的信息文本...",
  "error": "",
  "scrape_stats": {
    "line_count": 1234,
    "char_count": 56789,
    "last_char_line": 1234,
    "all_content_displayed": true
  },
  "model_used": "gpt-5",
  "tokens_used": 2048
}
```

### 重试机制

**Jina 抓取阶段**和 **LLM 提取阶段**都使用相同的手动重试策略：

- 重试延迟序列：`[1, 2, 4, 8]` 秒（共 4 次机会）
- 可重试的异常类型：

| 异常 | 说明 |
|------|------|
| `ConnectTimeout` | 连接超时 |
| `ConnectError` | 连接错误 |
| `ReadTimeout` | 读取超时 |
| `HTTPStatusError` (5xx) | 服务端错误 |
| `HTTPStatusError` (408) | 请求超时 |
| `HTTPStatusError` (409) | 冲突 |
| `HTTPStatusError` (425) | Too Early |
| `HTTPStatusError` (429) | 请求频率限制 |
| `RequestError` | 其他请求异常（仅 Jina 阶段） |

**不重试**的 HTTP 状态码：400, 401, 403, 404 等其他 4xx 错误。

---

## 三个工具对比总结

| 特性 | Google 搜索 | Search & Scrape | Jina + LLM |
|------|------------|-----------------|-------------|
| **功能** | 纯搜索 | 增强搜索 | 抓取 + 信息提取 |
| **API** | Serper（经子进程） | Serper（直接调用） | Jina.ai + LLM API |
| **输入** | 搜索关键词 | 搜索关键词 + 日期 | URL + 提取要求 |
| **输出** | 搜索结果 JSON 字符串 | 搜索结果字典 | 提取的信息文本 |
| **引号重试** | ❌ | ✅ | N/A |
| **日期过滤** | ❌ | ✅ before_date | ✅ Prompt 级别时间约束 |
| **HuggingFace 过滤** | ✅（底层） | ✅ | ✅ |
| **预测市场保护** | ❌ | ❌（仅定义） | ✅ 正则剥离 + Prompt 约束 |
| **内容截断** | ❌ | ❌ | ✅ 409,600 字符 |
| **重试次数** | 3 | 3 | 4 |
| **重试策略** | 指数退避 2^n（上限60s） | tenacity 指数退避 4-10s | 手动延迟 [1,2,4,8]s |
| **HTTP 库** | requests（同步） | httpx（异步） | httpx（异步） |

---

## 环境变量依赖

| 环境变量 | 用途 | 使用的工具 |
|---------|------|-----------|
| `SERPER_API_KEY` | Serper API 认证 | Google 搜索, Search & Scrape |
| `SERPER_BASE_URL` | Serper API 地址 | Google 搜索, Search & Scrape |
| `JINA_API_KEY` | Jina.ai API 认证 | Google 搜索(scrape), Jina + LLM |
| `JINA_BASE_URL` | Jina.ai API 地址 | Google 搜索(scrape), Jina + LLM |
| `SUMMARY_LLM_BASE_URL` | LLM API 地址 | Jina + LLM |
| `SUMMARY_LLM_MODEL_NAME` | LLM 模型名称 | Jina + LLM |
| `SUMMARY_LLM_API_KEY` | LLM API 认证 | Jina + LLM |
| `REMOVE_SNIPPETS` | 移除搜索摘要 | Google 搜索 |
| `REMOVE_KNOWLEDGE_GRAPH` | 移除知识图谱 | Google 搜索 |
| `REMOVE_ANSWER_BOX` | 移除答案框 | Google 搜索 |
