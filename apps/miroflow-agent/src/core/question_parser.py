# Copyright 2026 EvoAgent Contributors
# SPDX-License-Identifier: MIT
"""
Question Parser — 题目解析结果数据结构与解析器。

实现 ParsedQuestion dataclass (QP-001~003) 和 QuestionParser 类 (QP-101~107)。
ParsedQuestion 用于承载题目解析结果，QuestionParser 封装 LLM 调用逻辑。
"""

from dataclasses import dataclass, field, asdict
from typing import List, Optional, Dict, Any
import json
import logging
import time
import re

logger = logging.getLogger(__name__)


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
