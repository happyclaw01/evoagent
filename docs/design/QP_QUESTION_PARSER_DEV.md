# Question Parser & Strategy Definition — 开发计划

> **模块代号**: QP (Question Parser) + SD (Strategy Definition)  
> **父文档**: `STRATEGY_EVOLVE_ARCHITECTURE.md` 第三章 & 第四章  
> **基线**: EvoAgent Phase 1 (EA-001~012 已完成, 37 单元测试通过)  
> **创建日期**: 2026-03-20  
> **预计工期**: 2 天  
> **前置依赖**: 无（纯代码层，不依赖 OpenViking Server）

---

## 1. 架构总览

```
┌──────────────────────────────────────────────────────────────────────────┐
│                        execute_multi_path_pipeline()                     │
│                                                                          │
│  ┌────────────────────┐     ┌──────────────────────┐                     │
│  │   QuestionParser    │────▶│   ParsedQuestion      │                    │
│  │  (LLM 一次调用)     │     │  question_type        │                    │
│  │  GPT-4o-mini 级别   │     │  key_entities         │                    │
│  └────────────────────┘     │  time_window          │                    │
│                              │  resolution_criteria  │                    │
│                              │  difficulty_hint      │                    │
│                              └──────────┬───────────┘                    │
│                                         │                                │
│                                         ▼                                │
│  ┌──────────────────────────────────────────────────────────────────┐    │
│  │                    StrategyDefinition Pool                        │    │
│  │                                                                  │    │
│  │  ┌─────────────┐ ┌─────────────┐ ┌─────────────┐ ┌───────────┐  │    │
│  │  │ news_expert │ │ mechanism_  │ │ historical_ │ │ market_   │  │    │
│  │  │ (8维定义)    │ │ expert      │ │ expert      │ │ expert    │  │    │
│  │  └─────────────┘ └─────────────┘ └─────────────┘ └───────────┘  │    │
│  │  ┌─────────────────┐                                             │    │
│  │  │ counterfactual_ │                                             │    │
│  │  │ expert          │                                             │    │
│  │  └─────────────────┘                                             │    │
│  └──────────────────────────────────┬───────────────────────────────┘    │
│                                     │                                    │
│                                     ▼                                    │
│  ┌──────────────────────────────────────────────────────────────────┐    │
│  │                    StrategyCompiler                               │    │
│  │                                                                  │    │
│  │  8维 ──▶ TEMPLATES[dim] ──▶ 拼接 ──▶ prompt_suffix               │    │
│  │                                                                  │    │
│  │  compile_strategy(StrategyDefinition) → {name, prompt_suffix,    │    │
│  │                                          max_turns, _strategy_def}│    │
│  └──────────────────────────────────┬───────────────────────────────┘    │
│                                     │                                    │
│                                     ▼                                    │
│                          N 条路径并行执行 (现有逻辑)                       │
└──────────────────────────────────────────────────────────────────────────┘
```

---

## 2. 功能清单编号表

### 2.1 数据结构层

| 编号 | 功能名称 | 描述 | 状态 | 优先级 |
|------|---------|------|------|--------|
| **QP-001** | ParsedQuestion dataclass | 题目解析结果数据结构：question_type / key_entities / time_window / resolution_criteria / difficulty_hint | ✅ 已完成 | P0 |
| **QP-002** | ParsedQuestion 序列化 | to_dict() / from_dict() 方法，支持 JSON 序列化和日志记录 | ✅ 已完成 | P0 |
| **QP-003** | ParsedQuestion 默认值 | 解析失败时的安全降级默认值（question_type="other", difficulty_hint="medium"） | ✅ 已完成 | P0 |
| **QP-010** | StrategyDefinition dataclass | 8 维策略定义数据结构：id / name / island_id + 8 维 + parent_id / iteration_found + metrics | ✅ 已完成 | P0 |
| **QP-011** | StrategyDefinition metrics | 按题型拆分的胜率统计：overall{wins, total, rate} + by_type{type → {wins, total, rate}} | ✅ 已完成 | P0 |
| **QP-012** | StrategyDefinition.get_rate_for_type() | 获取指定题型的胜率，样本不足时退回 overall rate | ✅ 已完成 | P1 |
| **QP-013** | StrategyDefinition 序列化 | to_dict() / from_dict() 方法，JSON 持久化 | ✅ 已完成 | P0 |
| **QP-014** | 5 个初始种子策略常量 | news_expert / mechanism_expert / historical_expert / market_expert / counterfactual_expert 的完整 8 维定义 | ✅ 已完成 | P0 |

### 2.2 解析层

| 编号 | 功能名称 | 描述 | 状态 | 优先级 |
|------|---------|------|------|--------|
| **QP-101** | QuestionParser 类 | 代码层模块，封装 LLM 调用逻辑，不进入 ReAct 循环 | ✅ 已完成 | P0 |
| **QP-102** | PARSER_PROMPT 模板 | 结构化输出 prompt，引导 LLM 输出 JSON 格式的 ParsedQuestion | ✅ 已完成 | P0 |
| **QP-103** | parse() 异步方法 | async def parse(task_description: str) → ParsedQuestion，单次 LLM 调用 | ✅ 已完成 | P0 |
| **QP-104** | JSON 输出解析 | 从 LLM 响应中提取 JSON，处理 markdown 代码块包裹、多余文本等噪音 | ✅ 已完成 | P0 |
| **QP-105** | 解析失败降级 | LLM 调用失败或 JSON 解析失败时，返回安全默认 ParsedQuestion | ✅ 已完成 | P0 |
| **QP-106** | 小模型配置 | 支持通过配置指定 parser 使用的模型（默认 GPT-4o-mini 级别），与主路径模型解耦 | ✅ 已完成 | P1 |
| **QP-107** | 解析日志记录 | 记录 parse 输入/输出/耗时到 logger，便于调试和审计 | ✅ 已完成 | P1 |

### 2.3 编译层

| 编号 | 功能名称 | 描述 | 状态 | 优先级 |
|------|---------|------|------|--------|
| **QP-201** | 8 维 TEMPLATES 字典 | 每个维度一个 dict，key=维度值, value=prompt 片段 | ✅ 已完成 | P0 |
| **QP-202** | FRAMING_TEMPLATES | hypothesis_framing 维度模板：news_tracking / mechanism_analysis / historical_analogy / market_signal / counterfactual | ✅ 已完成 | P0 |
| **QP-203** | QUERY_TEMPLATES | query_policy 维度模板：broad_diverse / targeted_authoritative / trend_based / contrarian / temporal_sequence | ✅ 已完成 | P0 |
| **QP-204** | EVIDENCE_TEMPLATES | evidence_source 维度模板：news_wire / official_data / academic / market_data / social_signal | ✅ 已完成 | P0 |
| **QP-205** | RETRIEVAL_TEMPLATES | retrieval_depth 维度模板：shallow / medium / deep | ✅ 已完成 | P0 |
| **QP-206** | UPDATE_TEMPLATES | update_policy 维度模板：fast / moderate / conservative | ✅ 已完成 | P0 |
| **QP-207** | AUDIT_TEMPLATES | audit_policy 维度模板：devil_advocate / source_triangulation / base_rate_check / assumption_audit / none | ✅ 已完成 | P0 |
| **QP-208** | TERMINATION_TEMPLATES | termination_policy 维度模板：confidence_threshold / evidence_saturation / time_budget / adversarial_stable | ✅ 已完成 | P0 |
| **QP-209** | compile_strategy() | StrategyDefinition → {name, prompt_suffix, max_turns, _strategy_def}，拼接 8 维模板 | ✅ 已完成 | P0 |
| **QP-210** | strategy_distance() | 计算两个策略的维度差异数 / 总维度数（7 维），归一化 0-1 | ✅ 已完成 | P0 |
| **QP-211** | StrategyCompiler 类 | 封装编译逻辑，支持自定义模板覆盖 | ✅ 已完成 | P1 |

### 2.4 集成层

| 编号 | 功能名称 | 描述 | 状态 | 优先级 |
|------|---------|------|------|--------|
| **QP-301** | multi_path.py 前置 parse | execute_multi_path_pipeline() 最前面调用 QuestionParser.parse() | ✅ 已完成 | P0 |
| **QP-302** | _select_strategies() 改造 | 接收 ParsedQuestion 参数，用于策略选择决策 | ✅ 已完成 | P0 |
| **QP-303** | 旧策略格式兼容 | compile_strategy() 输出与现有 STRATEGY_VARIANTS dict 格式兼容 | ✅ 已完成 | P0 |
| **QP-304** | STRATEGY_VARIANTS 迁移 | 将现有 4 个硬编码策略迁移为 StrategyDefinition + compile，保持行为一致 | ✅ 已完成 | P1 |
| **QP-305** | 5 个种子策略注册 | 新增 5 个种子策略作为默认策略池，与旧策略共存 | ✅ 已完成 | P1 |
| **QP-306** | ParsedQuestion 透传 | ParsedQuestion 通过 pipeline 向下传递，供后续模块使用（日志、结果记录等） | ✅ 已完成 | P1 |
| **QP-307** | Feature flag 开关 | 配置项 `question_parser.enabled` 控制是否启用，禁用时走原有逻辑 | ✅ 已完成 | P0 |

### 2.5 测试层

| 编号 | 功能名称 | 描述 | 状态 | 优先级 |
|------|---------|------|------|--------|
| **QP-401** | 单测: ParsedQuestion 创建 | 测试 dataclass 正确创建、字段默认值 | ✅ 已完成 | P0 |
| **QP-402** | 单测: ParsedQuestion 序列化 | 测试 to_dict() / from_dict() 往返一致性 | ✅ 已完成 | P0 |
| **QP-403** | 单测: Parser prompt 输出解析 | 测试 JSON 提取能力：标准 JSON、markdown 包裹、含噪音文本 | ✅ 已完成 | P0 |
| **QP-404** | 单测: Parser 失败降级 | 测试 LLM 返回无效内容时的安全降级 | ✅ 已完成 | P0 |
| **QP-405** | 单测: StrategyDefinition 创建验证 | 测试 dataclass 正确创建、metrics 初始值、get_rate_for_type() | ✅ 已完成 | P0 |
| **QP-406** | 单测: StrategyDefinition 序列化 | 测试 to_dict() / from_dict() 往返一致性 | ✅ 已完成 | P0 |
| **QP-407** | 单测: StrategyCompiler 编译输出 | 测试 compile_strategy() 输出格式正确、包含所有维度模板 | ✅ 已完成 | P0 |
| **QP-408** | 单测: strategy_distance 计算 | 测试完全相同=0、完全不同=1、部分差异=正确比例 | ✅ 已完成 | P0 |
| **QP-409** | 单测: 5 个种子策略完整性 | 测试 5 个种子策略都能正确创建和编译 | ✅ 已完成 | P0 |
| **QP-410** | 单测: 种子策略两两距离 | 验证 5 个种子策略之间的距离 > 0.3（足够多样） | ✅ 已完成 | P1 |
| **QP-411** | 集测: Parser + 真实 LLM | 用真实 LLM 解析 cat10 的 10 道题，检查 question_type 分类准确率 | ⏭️ 跳过(需真实LLM) | P1 |
| **QP-412** | 集测: 编译后 prompt_suffix 注入 | 验证编译后的策略 dict 能正确注入 multi_path 的 Agent | ⏭️ 跳过(需完整pipeline) | P1 |
| **QP-413** | 回归: 现有 37 个测试不受影响 | 确认所有现有测试继续通过 | ✅ 已完成 | P0 |
| **QP-414** | 单测: feature flag 禁用时走原有逻辑 | 测试 question_parser.enabled=false 时行为不变 | ✅ 已完成 | P0 |

---

## 3. 数据架构图

```
┌─────────────────────────────────────────────────────────────────┐
│                        ParsedQuestion                            │
│                                                                  │
│  question_type: str ─────── "politics" | "entertainment" |       │
│                              "sports" | "finance" | "tech" |     │
│                              "science" | "other"                 │
│  key_entities: List[str] ── ["Trump", "2024 election"]           │
│  time_window: str ────────── "2024年11月前"                       │
│  resolution_criteria: str ── "以官方选举结果为准"                   │
│  difficulty_hint: str ────── "easy" | "medium" | "hard"          │
└─────────────────────────────────────────────────────────────────┘
         │
         │ 传入 _select_strategies()
         ▼
┌─────────────────────────────────────────────────────────────────┐
│                      StrategyDefinition                          │
│                                                                  │
│  ── 身份 ──                                                      │
│  id: str ──────────────── "news_expert_v1"                       │
│  name: str ────────────── "信息追踪专家"                           │
│  island_id: str ───────── "island_0_news"                        │
│                                                                  │
│  ── 8 维定义 ──                                                   │
│  hypothesis_framing: str ── "news_tracking"                      │
│  query_policy: str ──────── "broad_diverse"                      │
│  evidence_source: str ───── "news_wire"                          │
│  retrieval_depth: str ───── "shallow"                            │
│  update_policy: str ──────── "fast"                              │
│  audit_policy: str ──────── "source_triangulation"               │
│  termination_policy: str ── "evidence_saturation"                │
│  max_turns: int ──────────── 100                                 │
│                                                                  │
│  ── 元数据 ──                                                     │
│  parent_id: Optional[str] ── None                                │
│  iteration_found: int ────── 0                                   │
│                                                                  │
│  ── 胜率统计 ──                                                   │
│  metrics: Dict ──────────── {                                    │
│    "overall": {"wins": 12, "total": 20, "rate": 0.6},           │
│    "by_type": {                                                  │
│      "politics": {"wins": 8, "total": 10, "rate": 0.8},         │
│      "finance": {"wins": 4, "total": 10, "rate": 0.4}           │
│    }                                                             │
│  }                                                               │
└─────────────────────────────────────────────────────────────────┘
         │
         │ compile_strategy()
         ▼
┌─────────────────────────────────────────────────────────────────┐
│             编译输出（兼容现有 STRATEGY_VARIANTS 格式）             │
│                                                                  │
│  {                                                               │
│    "name": "news_expert_v1",                                     │
│    "description": "信息追踪专家",                                  │
│    "max_turns": 100,                                             │
│    "prompt_suffix": "[Strategy: 信息追踪专家]\n\n                  │
│      [视角] 追踪最新事件...\n\n                                    │
│      [搜索] 使用多样化...\n\n                                      │
│      [来源] 优先新闻通讯社...\n\n                                   │
│      ...(8 维拼接)",                                              │
│    "_strategy_def": <StrategyDefinition 引用>                     │
│  }                                                               │
└─────────────────────────────────────────────────────────────────┘
```

---

## 4. 详细接口设计

### 4.1 ParsedQuestion (`src/core/question_parser.py`)

```python
from dataclasses import dataclass, field, asdict
from typing import List, Optional, Dict, Any
import json


VALID_QUESTION_TYPES = [
    "politics", "entertainment", "sports", "finance",
    "tech", "science", "other",
]
VALID_DIFFICULTY_HINTS = ["easy", "medium", "hard"]


@dataclass
class ParsedQuestion:
    """题目解析结果 — QP-001/002/003"""
    
    question_type: str = "other"
    key_entities: List[str] = field(default_factory=list)
    time_window: str = ""
    resolution_criteria: str = ""
    difficulty_hint: str = "medium"
    
    def __post_init__(self):
        """QP-003: 验证并修正非法值"""
        if self.question_type not in VALID_QUESTION_TYPES:
            self.question_type = "other"
        if self.difficulty_hint not in VALID_DIFFICULTY_HINTS:
            self.difficulty_hint = "medium"
    
    def to_dict(self) -> Dict[str, Any]:
        """QP-002: 序列化为 dict"""
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ParsedQuestion":
        """QP-002: 从 dict 反序列化"""
        return cls(
            question_type=data.get("question_type", "other"),
            key_entities=data.get("key_entities", []),
            time_window=data.get("time_window", ""),
            resolution_criteria=data.get("resolution_criteria", ""),
            difficulty_hint=data.get("difficulty_hint", "medium"),
        )
    
    @classmethod
    def default(cls) -> "ParsedQuestion":
        """QP-003: 安全降级默认值"""
        return cls()
```

### 4.2 QuestionParser (`src/core/question_parser.py`)

```python
import logging
import time
import re
from typing import Optional

logger = logging.getLogger(__name__)


PARSER_PROMPT = """分析以下预测题目，提取结构化信息。

题目：{task_description}

输出 JSON（不要包含任何其他文本）:
{{
    "question_type": "politics|entertainment|sports|finance|tech|science|other",
    "key_entities": ["实体1", "实体2"],
    "time_window": "时间范围描述",
    "resolution_criteria": "判定标准",
    "difficulty_hint": "easy|medium|hard"
}}

规则：
- question_type 必须是给定的 7 种之一
- key_entities 提取题目中的关键人物/组织/事件名称
- time_window 描述题目涉及的时间窗口，无法判断则留空字符串
- resolution_criteria 描述如何判定答案正确，无法判断则留空字符串
- difficulty_hint: easy=事实查询, medium=需要推理, hard=多因素预测
"""


class QuestionParser:
    """题目解析器 — QP-101~107
    
    代码层模块，调 LLM 一次解析题目结构，不进入 ReAct 循环。
    """
    
    def __init__(
        self,
        llm_client,                    # LLM 客户端实例
        model: str = "",               # 指定模型，空则用 client 默认
        timeout: float = 30.0,         # 超时秒数
    ):
        self._client = llm_client
        self._model = model
        self._timeout = timeout
    
    async def parse(self, task_description: str) -> ParsedQuestion:
        """QP-103: 解析题目，返回 ParsedQuestion
        
        Args:
            task_description: 原始题目文本
            
        Returns:
            ParsedQuestion: 解析结果，失败时返回安全默认值
        """
        t0 = time.monotonic()
        try:
            prompt = PARSER_PROMPT.format(task_description=task_description)
            
            # QP-106: 单次 LLM 调用
            response = await self._call_llm(prompt)
            
            # QP-104: 从 LLM 响应中提取 JSON
            parsed_json = self._extract_json(response)
            
            result = ParsedQuestion.from_dict(parsed_json)
            
            elapsed = time.monotonic() - t0
            logger.info(
                f"QuestionParser: type={result.question_type}, "
                f"entities={result.key_entities}, "
                f"difficulty={result.difficulty_hint}, "
                f"elapsed={elapsed:.2f}s"
            )
            return result
            
        except Exception as e:
            elapsed = time.monotonic() - t0
            logger.warning(
                f"QuestionParser failed ({elapsed:.2f}s), using defaults: {e}"
            )
            # QP-105: 安全降级
            return ParsedQuestion.default()
    
    async def _call_llm(self, prompt: str) -> str:
        """QP-106: 调用 LLM（可用小模型）"""
        # 具体实现取决于 ClientFactory 接口
        # 支持 model 覆盖，允许用 GPT-4o-mini 级别
        response = await self._client.chat_completion(
            messages=[{"role": "user", "content": prompt}],
            model=self._model or None,
            temperature=0.0,       # 确定性输出
            max_tokens=500,        # 结构化输出不需要多
        )
        return response
    
    @staticmethod
    def _extract_json(text: str) -> dict:
        """QP-104: 从 LLM 响应中提取 JSON
        
        处理：
        - 纯 JSON 文本
        - markdown ```json ... ``` 包裹
        - JSON 前后有多余文本
        """
        # 尝试 1: 直接解析
        text = text.strip()
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass
        
        # 尝试 2: 提取 markdown 代码块
        md_match = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", text, re.DOTALL)
        if md_match:
            try:
                return json.loads(md_match.group(1).strip())
            except json.JSONDecodeError:
                pass
        
        # 尝试 3: 提取第一个 { ... } 块
        brace_match = re.search(r"\{[^{}]*\}", text, re.DOTALL)
        if brace_match:
            try:
                return json.loads(brace_match.group(0))
            except json.JSONDecodeError:
                pass
        
        raise ValueError(f"Cannot extract JSON from LLM response: {text[:200]}")
```

### 4.3 StrategyDefinition (`src/core/strategy_definition.py`)

```python
from dataclasses import dataclass, field, asdict
from typing import Optional, Dict, Any, List
import copy


STRATEGY_DIMENSIONS = [
    "hypothesis_framing",
    "query_policy",
    "evidence_source",
    "retrieval_depth",
    "update_policy",
    "audit_policy",
    "termination_policy",
]


@dataclass
class StrategyDefinition:
    """8 维策略定义 — QP-010~014
    
    每个策略是一个 8 维元组，定义 Agent 的搜索行为方向。
    """
    
    # 身份
    id: str = ""
    name: str = ""
    island_id: str = ""
    
    # 8 维定义
    hypothesis_framing: str = "news_tracking"
    query_policy: str = "broad_diverse"
    evidence_source: str = "news_wire"
    retrieval_depth: str = "medium"
    update_policy: str = "moderate"
    audit_policy: str = "none"
    termination_policy: str = "confidence_threshold"
    max_turns: int = 100
    
    # 元数据
    parent_id: Optional[str] = None
    iteration_found: int = 0
    
    # 按题型拆分的胜率
    metrics: Dict[str, Any] = field(default_factory=lambda: {
        "overall": {"wins": 0, "total": 0, "rate": 0.0},
        "by_type": {},
    })
    
    def get_rate_for_type(
        self, question_type: str, min_samples: int = 3
    ) -> float:
        """QP-012: 获取指定题型的胜率
        
        样本数 < min_samples 时退回 overall rate。
        """
        by_type = self.metrics.get("by_type", {})
        type_stats = by_type.get(question_type, {})
        if type_stats.get("total", 0) >= min_samples:
            return type_stats.get("rate", 0.0)
        return self.metrics.get("overall", {}).get("rate", 0.0)
    
    def record_result(self, question_type: str, won: bool) -> None:
        """记录一次对战结果，更新胜率统计"""
        # 更新 overall
        overall = self.metrics["overall"]
        overall["total"] += 1
        if won:
            overall["wins"] += 1
        overall["rate"] = (
            overall["wins"] / overall["total"] if overall["total"] > 0 else 0.0
        )
        
        # 更新 by_type
        by_type = self.metrics.setdefault("by_type", {})
        if question_type not in by_type:
            by_type[question_type] = {"wins": 0, "total": 0, "rate": 0.0}
        ts = by_type[question_type]
        ts["total"] += 1
        if won:
            ts["wins"] += 1
        ts["rate"] = ts["wins"] / ts["total"] if ts["total"] > 0 else 0.0
    
    def get_dimensions(self) -> Dict[str, str]:
        """返回 7 个维度的当前值"""
        return {d: getattr(self, d) for d in STRATEGY_DIMENSIONS}
    
    def to_dict(self) -> Dict[str, Any]:
        """QP-013: 序列化"""
        return {
            "id": self.id,
            "name": self.name,
            "island_id": self.island_id,
            "hypothesis_framing": self.hypothesis_framing,
            "query_policy": self.query_policy,
            "evidence_source": self.evidence_source,
            "retrieval_depth": self.retrieval_depth,
            "update_policy": self.update_policy,
            "audit_policy": self.audit_policy,
            "termination_policy": self.termination_policy,
            "max_turns": self.max_turns,
            "parent_id": self.parent_id,
            "iteration_found": self.iteration_found,
            "metrics": copy.deepcopy(self.metrics),
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "StrategyDefinition":
        """QP-013: 反序列化"""
        return cls(
            id=data.get("id", ""),
            name=data.get("name", ""),
            island_id=data.get("island_id", ""),
            hypothesis_framing=data.get("hypothesis_framing", "news_tracking"),
            query_policy=data.get("query_policy", "broad_diverse"),
            evidence_source=data.get("evidence_source", "news_wire"),
            retrieval_depth=data.get("retrieval_depth", "medium"),
            update_policy=data.get("update_policy", "moderate"),
            audit_policy=data.get("audit_policy", "none"),
            termination_policy=data.get("termination_policy", "confidence_threshold"),
            max_turns=data.get("max_turns", 100),
            parent_id=data.get("parent_id"),
            iteration_found=data.get("iteration_found", 0),
            metrics=data.get("metrics", {
                "overall": {"wins": 0, "total": 0, "rate": 0.0},
                "by_type": {},
            }),
        )


def strategy_distance(a: StrategyDefinition, b: StrategyDefinition) -> float:
    """QP-210: 计算两个策略的维度距离
    
    维度差异数 / 总维度数（7 维），归一化到 [0, 1]。
    0 = 完全相同, 1 = 所有维度都不同。
    """
    diff = sum(
        1 for d in STRATEGY_DIMENSIONS
        if getattr(a, d) != getattr(b, d)
    )
    return diff / len(STRATEGY_DIMENSIONS)
```

### 4.4 StrategyCompiler (`src/core/strategy_compiler.py`)

```python
from typing import Dict, Any
from .strategy_definition import StrategyDefinition


# ──── QP-202: hypothesis_framing 维度模板 ────

FRAMING_TEMPLATES: Dict[str, str] = {
    "news_tracking": (
        "[视角: 信息追踪]\n"
        "你是一个信息追踪专家。关注最新的新闻事件进展、官方声明和权威媒体报道。"
        "追踪事件的时间线，识别关键转折点和最新动态。"
    ),
    "mechanism_analysis": (
        "[视角: 机制分析]\n"
        "你是一个结构性分析专家。关注驱动事件的底层机制、制度约束、利益格局和决策流程。"
        "分析因果链条，识别关键变量和约束条件。"
    ),
    "historical_analogy": (
        "[视角: 历史类比]\n"
        "你是一个历史类比专家。寻找历史上的类似案例和基准率。"
        "分析过去相似情境的结果分布，用历史数据修正直觉判断。"
    ),
    "market_signal": (
        "[视角: 市场信号]\n"
        "你是一个市场信号专家。关注预测市场赔率、金融指标、博彩盘口等市场定价信息。"
        "市场价格反映了大量参与者的集体判断，是强信号来源。"
    ),
    "counterfactual": (
        "[视角: 对抗验证]\n"
        "你是一个对抗验证专家。专门挑战主流观点和表面证据。"
        "主动寻找反面证据，构建反事实场景，检验主流判断的脆弱点。"
    ),
}


# ──── QP-203: query_policy 维度模板 ────

QUERY_TEMPLATES: Dict[str, str] = {
    "broad_diverse": (
        "[搜索策略: 广泛多样]\n"
        "使用多种不同的搜索词和角度进行搜索，最大化信息覆盖面。"
        "同一个问题至少用 3 种不同表述搜索。"
    ),
    "targeted_authoritative": (
        "[搜索策略: 精准权威]\n"
        "直接搜索最权威的一手信息来源。优先查找官方网站、数据库和权威机构发布。"
        "宁可少搜但要搜到最可靠的。"
    ),
    "trend_based": (
        "[搜索策略: 趋势追踪]\n"
        "按时间线搜索事件发展趋势。从早期到最近，追踪关键指标的变化方向。"
        "注意趋势的加速、减速和拐点。"
    ),
    "contrarian": (
        "[搜索策略: 逆向搜索]\n"
        "主动搜索与主流观点相反的信息。使用 'why X won't happen'、'against'、"
        "'criticism' 等关键词。寻找被忽视的反面证据。"
    ),
    "temporal_sequence": (
        "[搜索策略: 时序递进]\n"
        "按时间顺序搜索，从最早的相关事件开始，逐步推进到最新状态。"
        "构建完整的事件时间线，不遗漏关键节点。"
    ),
}


# ──── QP-204: evidence_source 维度模板 ────

EVIDENCE_TEMPLATES: Dict[str, str] = {
    "news_wire": (
        "[证据来源: 新闻通讯社]\n"
        "优先信任 Reuters、AP、AFP 等通讯社报道。"
        "主流媒体 (NYT, BBC, 新华社) 作为补充。谨慎对待自媒体和社交平台。"
    ),
    "official_data": (
        "[证据来源: 官方数据]\n"
        "优先查找政府公报、央行数据、统计局发布、上市公司公告等一手官方数据。"
        "新闻报道作为索引找到原始数据源。"
    ),
    "academic": (
        "[证据来源: 学术研究]\n"
        "优先查找学术论文、研究报告、专家分析和智库报告。"
        "注意方法论质量和样本量。"
    ),
    "market_data": (
        "[证据来源: 市场数据]\n"
        "优先查找预测市场 (Polymarket, Metaculus)、金融市场数据、博彩赔率。"
        "市场价格是高密度信息信号。"
    ),
    "social_signal": (
        "[证据来源: 社会信号]\n"
        "关注社交媒体趋势、公众舆论、民调数据和情绪指标。"
        "注意区分噪音和真实信号。"
    ),
}


# ──── QP-205: retrieval_depth 维度模板 ────

RETRIEVAL_TEMPLATES: Dict[str, str] = {
    "shallow": (
        "[搜索深度: 浅层]\n"
        "快速扫描多个来源的标题和摘要，获取全局图景。"
        "不深入阅读长文，效率优先。"
    ),
    "medium": (
        "[搜索深度: 中等]\n"
        "对关键来源深入阅读，次要来源快速浏览。"
        "在效率和深度之间平衡。"
    ),
    "deep": (
        "[搜索深度: 深层]\n"
        "对每个关键来源进行深入阅读和分析。"
        "追溯引用链，检查原始数据。宁可慢但要彻底。"
    ),
}


# ──── QP-206: update_policy 维度模板 ────

UPDATE_TEMPLATES: Dict[str, str] = {
    "fast": (
        "[更新策略: 快速更新]\n"
        "每获得一条新证据就立即更新判断。对新信息敏感，快速调整。"
    ),
    "moderate": (
        "[更新策略: 适度更新]\n"
        "积累 2-3 条一致证据后更新判断。避免被单条信息过度影响。"
    ),
    "conservative": (
        "[更新策略: 保守更新]\n"
        "保持初始判断的锚定效应，只有强力反面证据才修正。"
        "避免频繁摇摆。"
    ),
}


# ──── QP-207: audit_policy 维度模板 ────

AUDIT_TEMPLATES: Dict[str, str] = {
    "devil_advocate": (
        "[自审策略: 魔鬼代言人]\n"
        "在给出判断前，主动为相反结论辩护。"
        "如果反面论证足够有力，降低置信度。"
    ),
    "source_triangulation": (
        "[自审策略: 来源三角验证]\n"
        "关键事实必须由至少 2 个独立来源确认。"
        "单一来源的信息标记为未验证。"
    ),
    "base_rate_check": (
        "[自审策略: 基准率检查]\n"
        "检查类似事件的历史基准率。"
        "如果你的判断与基准率偏差很大，需要额外强力证据支撑。"
    ),
    "assumption_audit": (
        "[自审策略: 假设审计]\n"
        "列出你推理中的所有隐含假设，逐一检验。"
        "如果某个假设不成立，结论是否会改变？"
    ),
    "none": (
        "[自审策略: 无]\n"
        "不做额外的自我审查，直接给出判断。"
    ),
}


# ──── QP-208: termination_policy 维度模板 ────

TERMINATION_TEMPLATES: Dict[str, str] = {
    "confidence_threshold": (
        "[停止条件: 置信度阈值]\n"
        "当你对答案的置信度达到 high 时停止搜索。"
        "如果长时间无法达到高置信度，在中等置信度时也可以停止。"
    ),
    "evidence_saturation": (
        "[停止条件: 证据饱和]\n"
        "当新搜索不再带来新信息时停止。"
        "连续 2-3 次搜索结果重复则视为饱和。"
    ),
    "time_budget": (
        "[停止条件: 时间预算]\n"
        "在分配的轮次内尽可能多搜索，时间到就给出当前最佳判断。"
        "不追求完美，追求时间内最优。"
    ),
    "adversarial_stable": (
        "[停止条件: 对抗稳定]\n"
        "当你尝试了反面搜索仍无法推翻当前判断时停止。"
        "判断经过了对抗验证才算稳定。"
    ),
}


class StrategyCompiler:
    """策略编译器 — QP-209/211
    
    将 8 维 StrategyDefinition 编译为 multi_path 可用的 dict 格式。
    """
    
    def __init__(
        self,
        framing_templates: Dict[str, str] = None,
        query_templates: Dict[str, str] = None,
        evidence_templates: Dict[str, str] = None,
        retrieval_templates: Dict[str, str] = None,
        update_templates: Dict[str, str] = None,
        audit_templates: Dict[str, str] = None,
        termination_templates: Dict[str, str] = None,
    ):
        """QP-211: 支持自定义模板覆盖"""
        self._templates = {
            "hypothesis_framing": framing_templates or FRAMING_TEMPLATES,
            "query_policy": query_templates or QUERY_TEMPLATES,
            "evidence_source": evidence_templates or EVIDENCE_TEMPLATES,
            "retrieval_depth": retrieval_templates or RETRIEVAL_TEMPLATES,
            "update_policy": update_templates or UPDATE_TEMPLATES,
            "audit_policy": audit_templates or AUDIT_TEMPLATES,
            "termination_policy": termination_templates or TERMINATION_TEMPLATES,
        }
    
    def compile(self, strategy: StrategyDefinition) -> Dict[str, Any]:
        """QP-209: 8 维 → prompt_suffix
        
        Returns:
            兼容 STRATEGY_VARIANTS 格式的 dict:
            {
                "name": str,
                "description": str,
                "max_turns": int,
                "prompt_suffix": str,
                "_strategy_def": StrategyDefinition,
            }
        """
        prompt_parts = []
        
        # 按维度顺序拼接模板
        dim_template_map = [
            ("hypothesis_framing", strategy.hypothesis_framing),
            ("query_policy", strategy.query_policy),
            ("evidence_source", strategy.evidence_source),
            ("retrieval_depth", strategy.retrieval_depth),
            ("update_policy", strategy.update_policy),
            ("audit_policy", strategy.audit_policy),
            ("termination_policy", strategy.termination_policy),
        ]
        
        for dim_name, dim_value in dim_template_map:
            templates = self._templates[dim_name]
            if dim_value in templates:
                prompt_parts.append(templates[dim_value])
            else:
                # 未知维度值，跳过并警告
                prompt_parts.append(f"[{dim_name}: {dim_value}]")
        
        prompt_suffix = (
            f"\n\n[Strategy: {strategy.name}]\n\n"
            + "\n\n".join(prompt_parts)
        )
        
        return {
            "name": strategy.id,
            "description": strategy.name,
            "max_turns": strategy.max_turns,
            "prompt_suffix": prompt_suffix,
            "_strategy_def": strategy,
        }


# ──── 模块级便捷函数 ────

_default_compiler = StrategyCompiler()


def compile_strategy(strategy: StrategyDefinition) -> Dict[str, Any]:
    """QP-209: 模块级便捷函数"""
    return _default_compiler.compile(strategy)
```

### 4.5 种子策略定义 (`src/core/seed_strategies.py`)

```python
from .strategy_definition import StrategyDefinition


# ──── QP-014: 5 个初始种子策略 ────

SEED_NEWS_EXPERT = StrategyDefinition(
    id="news_expert_v1",
    name="信息追踪专家",
    island_id="island_0_news",
    hypothesis_framing="news_tracking",
    query_policy="broad_diverse",
    evidence_source="news_wire",
    retrieval_depth="shallow",
    update_policy="fast",
    audit_policy="source_triangulation",
    termination_policy="evidence_saturation",
    max_turns=100,
)

SEED_MECHANISM_EXPERT = StrategyDefinition(
    id="mechanism_expert_v1",
    name="机制分析专家",
    island_id="island_1_mechanism",
    hypothesis_framing="mechanism_analysis",
    query_policy="targeted_authoritative",
    evidence_source="official_data",
    retrieval_depth="deep",
    update_policy="conservative",
    audit_policy="assumption_audit",
    termination_policy="confidence_threshold",
    max_turns=200,
)

SEED_HISTORICAL_EXPERT = StrategyDefinition(
    id="historical_expert_v1",
    name="历史类比专家",
    island_id="island_2_historical",
    hypothesis_framing="historical_analogy",
    query_policy="temporal_sequence",
    evidence_source="academic",
    retrieval_depth="deep",
    update_policy="conservative",
    audit_policy="base_rate_check",
    termination_policy="confidence_threshold",
    max_turns=200,
)

SEED_MARKET_EXPERT = StrategyDefinition(
    id="market_expert_v1",
    name="市场信号专家",
    island_id="island_3_market",
    hypothesis_framing="market_signal",
    query_policy="trend_based",
    evidence_source="market_data",
    retrieval_depth="medium",
    update_policy="fast",
    audit_policy="source_triangulation",
    termination_policy="evidence_saturation",
    max_turns=150,
)

SEED_COUNTERFACTUAL_EXPERT = StrategyDefinition(
    id="counterfactual_expert_v1",
    name="对抗验证专家",
    island_id="island_4_counterfactual",
    hypothesis_framing="counterfactual",
    query_policy="contrarian",
    evidence_source="news_wire",
    retrieval_depth="medium",
    update_policy="moderate",
    audit_policy="devil_advocate",
    termination_policy="adversarial_stable",
    max_turns=150,
)


# 种子策略列表
SEED_STRATEGIES = [
    SEED_NEWS_EXPERT,
    SEED_MECHANISM_EXPERT,
    SEED_HISTORICAL_EXPERT,
    SEED_MARKET_EXPERT,
    SEED_COUNTERFACTUAL_EXPERT,
]
```

---

## 5. 数据流完整图

```
┌─────────────────────────────────────────────────────────────────────────┐
│                    execute_multi_path_pipeline()                         │
│                                                                          │
│  ① 原始题目文本                                                          │
│     │                                                                    │
│     ▼                                                                    │
│  ┌──────────────────────────────────────┐                                │
│  │ [QP-307] 检查 feature flag            │                               │
│  │ question_parser.enabled = true?       │                               │
│  └──────────┬───────────────┬───────────┘                                │
│        enabled          disabled                                         │
│             │               │                                            │
│             ▼               ▼                                            │
│  ┌──────────────────┐   ┌────────────────────┐                           │
│  │ QuestionParser    │   │ 走原有逻辑           │                          │
│  │ .parse()          │   │ STRATEGY_VARIANTS    │                         │
│  │ [QP-103]          │   │ [:num_paths]         │                         │
│  │                   │   └────────┬─────────────┘                        │
│  │ LLM 调用 (1次)    │            │                                       │
│  │ GPT-4o-mini 级别  │            │                                       │
│  └────────┬─────────┘            │                                       │
│           │                       │                                       │
│           ▼                       │                                       │
│  ┌──────────────────┐            │                                       │
│  │ ParsedQuestion    │            │                                       │
│  │ [QP-001]          │            │                                       │
│  └────────┬─────────┘            │                                       │
│           │                       │                                       │
│           ▼                       │                                       │
│  ┌──────────────────────────┐    │                                       │
│  │ _select_strategies()      │    │                                       │
│  │ [QP-302]                  │    │                                       │
│  │                           │    │                                       │
│  │ 接收 ParsedQuestion       │    │                                       │
│  │ 选出 N 个 StrategyDef     │    │                                       │
│  │ (当前阶段: 5 种子策略选 N) │    │                                       │
│  └────────┬─────────────────┘    │                                       │
│           │                       │                                       │
│           ▼                       │                                       │
│  ┌──────────────────────────┐    │                                       │
│  │ StrategyCompiler.compile()│    │                                       │
│  │ [QP-209]                  │    │                                       │
│  │                           │    │                                       │
│  │ 8维 → TEMPLATES → 拼接    │    │                                       │
│  │ → prompt_suffix           │    │                                       │
│  └────────┬─────────────────┘    │                                       │
│           │                       │                                       │
│           ▼                       ▼                                       │
│  ┌──────────────────────────────────────┐                                │
│  │ 策略 dict 列表（兼容现有格式）         │                                │
│  │ [QP-303]                              │                                │
│  │                                       │                                │
│  │ [{name, description, max_turns,       │                                │
│  │   prompt_suffix, _strategy_def}, ...] │                                │
│  └──────────────────┬───────────────────┘                                │
│                     │                                                     │
│                     ▼                                                     │
│           N 条路径并行执行 (现有 EA-001~012 逻辑不变)                       │
│                     │                                                     │
│                     ▼                                                     │
│                投票 / Judge                                                │
│                     │                                                     │
│                     ▼                                                     │
│              最终答案 + ParsedQuestion 附加到结果日志                       │
│              [QP-306]                                                     │
└──────────────────────────────────────────────────────────────────────────┘
```

---

## 6. 文件结构

### 6.1 新增文件

| 文件路径 | 职责 | 对应编号 |
|---------|------|---------|
| `src/core/question_parser.py` | ParsedQuestion + QuestionParser + PARSER_PROMPT | QP-001~107 |
| `src/core/strategy_definition.py` | StrategyDefinition + strategy_distance() | QP-010~013, QP-210 |
| `src/core/strategy_compiler.py` | StrategyCompiler + 8 维 TEMPLATES + compile_strategy() | QP-201~211 |
| `src/core/seed_strategies.py` | 5 个初始种子策略常量 | QP-014 |
| `src/tests/test_question_parser.py` | ParsedQuestion + QuestionParser 单元测试 | QP-401~404 |
| `src/tests/test_strategy_definition.py` | StrategyDefinition + strategy_distance 单元测试 | QP-405~406, QP-408, QP-410 |
| `src/tests/test_strategy_compiler.py` | StrategyCompiler 编译输出 + 种子策略测试 | QP-407, QP-409 |

### 6.2 修改文件

| 文件路径 | 修改内容 | 对应编号 |
|---------|---------|---------|
| `src/core/multi_path.py` | 1. 顶部 import QuestionParser, StrategyCompiler, SEED_STRATEGIES<br>2. execute_multi_path_pipeline() 最前面加 parse() 调用<br>3. _select_strategies() 签名加 parsed_question 参数<br>4. feature flag 检查逻辑 | QP-301~307 |
| `conf/evoagent/default.yaml` (如存在) | 新增 `question_parser.enabled` 配置项 | QP-307 |

### 6.3 不修改文件

| 文件路径 | 说明 |
|---------|------|
| `src/core/orchestrator.py` | 单路径 ReAct 不变 |
| `src/core/pipeline.py` | 管道入口不变，multi_path 内部改造 |
| `src/llm/` | LLM 调用层不变 |
| `libs/miroflow-tools/` | 工具层不变 |
| `src/core/openviking_context.py` | 本阶段不改存储层 |
| `src/core/streaming.py` | 流式输出不变 |
| `src/core/cost_tracker.py` | 成本追踪不变 |
| `src/tests/test_multi_path.py` | 现有测试不改（QP-413 回归验证） |
| `src/tests/test_early_stopping.py` | 现有测试不改 |
| 其他现有 37 个测试文件 | 全部不改 |

---

## 7. 开发路线图

### Phase 1: 数据结构层 (Day 1 上午, ~3h)

**目标**: 建立核心数据模型

| 步骤 | 工作内容 | 交付 |
|------|---------|------|
| 1.1 | 实现 ParsedQuestion dataclass (QP-001~003) | `question_parser.py` 中 ParsedQuestion 类 |
| 1.2 | 实现 StrategyDefinition dataclass (QP-010~013) | `strategy_definition.py` |
| 1.3 | 实现 strategy_distance() (QP-210) | `strategy_definition.py` 中函数 |
| 1.4 | 编写数据结构层单元测试 (QP-401, 402, 405, 406, 408) | `test_question_parser.py`, `test_strategy_definition.py` |

**验收标准**:
- [ ] ParsedQuestion 可正确创建、序列化/反序列化、非法值自动修正
- [ ] StrategyDefinition 可正确创建、记录结果、按题型查胜率
- [ ] strategy_distance() 对相同策略返回 0，完全不同返回 1
- [ ] 全部新增单元测试通过

### Phase 2: 编译层 + 种子策略 (Day 1 下午, ~3h)

**目标**: 建立策略编译能力和初始策略池

| 步骤 | 工作内容 | 交付 |
|------|---------|------|
| 2.1 | 实现 8 维 TEMPLATES 字典 (QP-202~208) | `strategy_compiler.py` 中 7 个 TEMPLATES |
| 2.2 | 实现 StrategyCompiler 和 compile_strategy() (QP-209, 211) | `strategy_compiler.py` |
| 2.3 | 定义 5 个种子策略 (QP-014) | `seed_strategies.py` |
| 2.4 | 编写编译层 + 种子策略单元测试 (QP-407, 409, 410) | `test_strategy_compiler.py` |

**验收标准**:
- [ ] compile_strategy() 输出格式与现有 STRATEGY_VARIANTS dict 兼容
- [ ] 5 个种子策略都能成功编译，prompt_suffix 包含 7 个维度的内容
- [ ] 5 个种子策略两两距离 > 0.3
- [ ] 全部新增单元测试通过

### Phase 3: 解析层 (Day 2 上午, ~3h)

**目标**: 实现 QuestionParser LLM 调用

| 步骤 | 工作内容 | 交付 |
|------|---------|------|
| 3.1 | 设计 PARSER_PROMPT (QP-102) | `question_parser.py` 中 prompt 常量 |
| 3.2 | 实现 QuestionParser 类 (QP-101, 103~107) | `question_parser.py` |
| 3.3 | 实现 _extract_json() 鲁棒解析 (QP-104) | `question_parser.py` 中静态方法 |
| 3.4 | 编写解析层单元测试 (QP-403, 404) | `test_question_parser.py` |

**验收标准**:
- [ ] _extract_json() 能处理纯 JSON、markdown 包裹、含噪音文本
- [ ] parse() 失败时返回安全默认 ParsedQuestion
- [ ] 日志正确记录解析结果和耗时
- [ ] 全部新增单元测试通过

### Phase 4: 集成层 + 回归 (Day 2 下午, ~3h)

**目标**: 接入 multi_path.py，确保向后兼容

| 步骤 | 工作内容 | 交付 |
|------|---------|------|
| 4.1 | 修改 multi_path.py 前置 parse 调用 (QP-301) | multi_path.py 修改 |
| 4.2 | 改造 _select_strategies() (QP-302, 303) | multi_path.py 修改 |
| 4.3 | 实现 feature flag (QP-307) | multi_path.py + 配置文件 |
| 4.4 | 回归测试 (QP-413, 414) | 全部 37 个现有测试通过 |
| 4.5 | 集成测试 (QP-411, 412) — 如有 LLM 访问 | 可选 |

**验收标准**:
- [ ] feature flag 禁用时，行为与改造前完全一致
- [ ] feature flag 启用时，parse 正确执行，策略通过编译器产生
- [ ] 现有 37 个单元测试全部通过（零回归）
- [ ] 新增单元测试全部通过

---

## 8. 设计决策记录

| 编号 | 决策 | 考虑的替代方案 | 选择理由 |
|------|------|--------------|---------|
| **QP-DD-01** | QuestionParser 作为代码层模块，不进入 ReAct 循环 | 在 Agent system prompt 中要求自行分类 | 代码层可控、成本低（1 次小模型调用 vs 占用 Agent 轮次）、结果结构化可靠 |
| **QP-DD-02** | 使用 GPT-4o-mini 级别小模型做解析 | 用主路径同款大模型 | 解析任务简单，小模型足够且成本低 ~0.001$/次；大模型浪费 |
| **QP-DD-03** | 8 维策略用 str 枚举值而非 Enum 类 | Python Enum | str 便于 JSON 序列化、LLM 输出解析、模板匹配；Enum 增加序列化复杂度 |
| **QP-DD-04** | compile_strategy() 输出兼容现有 STRATEGY_VARIANTS dict 格式 | 设计全新格式 | 最小侵入性，下游 _run_single_path() 不需改动；_strategy_def 字段携带原始定义供后续模块使用 |
| **QP-DD-05** | 种子策略两两距离 > 0.3 作为多样性保证 | 不设距离约束 | 7 维中至少 3 维不同 → distance ≥ 3/7 ≈ 0.43，确保搜索行为实质不同 |
| **QP-DD-06** | Feature flag 控制 parser 启用 | 始终启用 | 降低集成风险，可随时回退；新功能不应阻塞现有流程 |
| **QP-DD-07** | _extract_json() 多级 fallback 解析 | 只用 json.loads() | LLM 输出不可控，需处理 markdown 包裹、前后缀文本等常见模式 |
| **QP-DD-08** | strategy_distance 只考虑 7 个语义维度，不含 max_turns | 把 max_turns 也算入距离 | max_turns 是连续值，与离散维度性质不同；语义方向相同但轮次不同的策略应视为近似 |
| **QP-DD-09** | ParsedQuestion 的 question_type 限定 7 种 | 开放文本 | 有限枚举便于按题型统计胜率、匹配策略；"other" 兜底未知类型 |
| **QP-DD-10** | 本阶段不迁移旧 STRATEGY_VARIANTS | 立即删除旧格式 | QP-304 列为 P1 而非 P0，先共存，验证新系统稳定后再迁移 |

---

## 9. 风险与缓解

| 风险 | 影响 | 概率 | 缓解措施 |
|------|------|------|---------|
| Parser LLM 调用增加延迟 | 低：~0.5-1s/次 | 高 | 小模型响应快；parse 与路径执行是串行必要步骤，非额外开销 |
| Parser 输出 question_type 不准确 | 中：策略选择偏差 | 中 | QP-105 降级机制；初始阶段不强依赖题型（5 种子策略全上）；后续靠数据积累修正 |
| JSON 解析失败率过高 | 中：频繁降级 | 低 | QP-104 多级 fallback；temperature=0 确定性输出；小模型对简单 JSON 任务可靠度高 |
| 8 维模板 prompt 过长，挤压 Agent 上下文 | 中：Agent 表现下降 | 低 | 7 个模板 × ~50 字/模板 ≈ 350 字 ≈ 500 token，远小于 context window 余量 |
| 种子策略设计不合理，初始表现差 | 中：冷启动期表现下降 | 中 | 5 个种子基于 STRATEGY_EVOLVE_ARCHITECTURE.md 精心设计；feature flag 可随时回退到旧策略 |
| _select_strategies() 改造引入回归 bug | 高：影响核心流程 | 低 | QP-307 feature flag 默认禁用；QP-413 回归测试全量验证；QP-303 格式兼容层 |
| 旧策略与新策略共存导致混乱 | 低：维护成本增加 | 中 | 过渡期明确分离：新系统通过 feature flag 启用，旧系统作为 fallback；Phase 后续统一迁移 |

---

## 10. 术语表

| 术语 | 定义 |
|------|------|
| **ParsedQuestion** | 题目解析结果数据结构，包含 question_type、key_entities、time_window、resolution_criteria、difficulty_hint |
| **StrategyDefinition** | 8 维策略定义数据结构，描述 Agent 的搜索行为方向 |
| **StrategyCompiler** | 策略编译器，将 8 维定义编译为 Agent 可用的 prompt_suffix |
| **TEMPLATES** | 每个维度的模板字典，key=维度值，value=prompt 文本片段 |
| **strategy_distance** | 两个策略之间的归一化距离（0=相同, 1=完全不同），计算方式为维度差异数/总维度数 |
| **compile_strategy()** | 编译函数，StrategyDefinition → {name, prompt_suffix, max_turns, _strategy_def} |
| **种子策略 (Seed Strategy)** | 5 个初始策略，开局即可用，代表 5 种不同的专家视角 |
| **Feature Flag** | `question_parser.enabled` 配置开关，控制是否启用新的 QuestionParser 流程 |
| **8 维 (8 Dimensions)** | hypothesis_framing / query_policy / evidence_source / retrieval_depth / update_policy / audit_policy / termination_policy / max_turns |
| **降级 (Fallback)** | Parser 失败时返回安全默认值，确保流程不中断 |
| **prompt_suffix** | 注入到 Agent system prompt 末尾的策略指令文本 |
| **question_type** | 题目类型：politics / entertainment / sports / finance / tech / science / other |
| **difficulty_hint** | 难度提示：easy（事实查询）/ medium（需要推理）/ hard（多因素预测） |
| **by_type metrics** | 按题型拆分的胜率统计，支持条件化策略选择 |
