# Copyright 2026 EvoAgent Contributors
# SPDX-License-Identifier: MIT
"""
ParsedQuestion 单元测试 — QP-401, QP-402, QP-403, QP-404。

测试 ParsedQuestion dataclass 的创建、验证、序列化和默认值，
以及 QuestionParser 的 JSON 提取和失败降级。
"""

import pytest
from unittest.mock import AsyncMock, MagicMock
from src.core.question_parser import (
    ParsedQuestion,
    QuestionParser,
    PARSER_PROMPT,
    VALID_QUESTION_TYPES,
    VALID_DIFFICULTY_HINTS,
)


class TestParsedQuestionCreation:
    """QP-401: 测试 ParsedQuestion 正确创建和字段默认值"""

    def test_default_creation(self):
        """默认创建应使用安全默认值"""
        pq = ParsedQuestion()
        assert pq.question_type == "other"
        assert pq.key_entities == []
        assert pq.time_window == ""
        assert pq.resolution_criteria == ""
        assert pq.difficulty_hint == "medium"

    def test_creation_with_values(self):
        """传入具体值应正确设置"""
        pq = ParsedQuestion(
            question_type="politics",
            key_entities=["Trump", "2024 election"],
            time_window="2024年11月前",
            resolution_criteria="以官方选举结果为准",
            difficulty_hint="hard",
        )
        assert pq.question_type == "politics"
        assert pq.key_entities == ["Trump", "2024 election"]
        assert pq.time_window == "2024年11月前"
        assert pq.resolution_criteria == "以官方选举结果为准"
        assert pq.difficulty_hint == "hard"

    def test_invalid_question_type_corrected(self):
        """非法 question_type 应自动修正为 'other'"""
        pq = ParsedQuestion(question_type="invalid_type")
        assert pq.question_type == "other"

    def test_invalid_difficulty_hint_corrected(self):
        """非法 difficulty_hint 应自动修正为 'medium'"""
        pq = ParsedQuestion(difficulty_hint="extreme")
        assert pq.difficulty_hint == "medium"

    def test_all_valid_question_types(self):
        """所有合法 question_type 都应被接受"""
        for qt in VALID_QUESTION_TYPES:
            pq = ParsedQuestion(question_type=qt)
            assert pq.question_type == qt

    def test_all_valid_difficulty_hints(self):
        """所有合法 difficulty_hint 都应被接受"""
        for dh in VALID_DIFFICULTY_HINTS:
            pq = ParsedQuestion(difficulty_hint=dh)
            assert pq.difficulty_hint == dh

    def test_default_class_method(self):
        """default() 类方法应返回安全默认值"""
        pq = ParsedQuestion.default()
        assert pq.question_type == "other"
        assert pq.key_entities == []
        assert pq.difficulty_hint == "medium"

    def test_key_entities_mutable_default(self):
        """不同实例的 key_entities 不应共享引用"""
        pq1 = ParsedQuestion()
        pq2 = ParsedQuestion()
        pq1.key_entities.append("test")
        assert pq2.key_entities == []


class TestParsedQuestionSerialization:
    """QP-402: 测试 ParsedQuestion 序列化往返一致性"""

    def test_to_dict(self):
        """to_dict() 应返回正确的 dict"""
        pq = ParsedQuestion(
            question_type="finance",
            key_entities=["Apple", "AAPL"],
            time_window="2024Q4",
            resolution_criteria="股价收盘价",
            difficulty_hint="hard",
        )
        d = pq.to_dict()
        assert d["question_type"] == "finance"
        assert d["key_entities"] == ["Apple", "AAPL"]
        assert d["time_window"] == "2024Q4"
        assert d["resolution_criteria"] == "股价收盘价"
        assert d["difficulty_hint"] == "hard"

    def test_from_dict(self):
        """from_dict() 应正确反序列化"""
        data = {
            "question_type": "sports",
            "key_entities": ["FIFA", "World Cup"],
            "time_window": "2026",
            "resolution_criteria": "官方赛果",
            "difficulty_hint": "medium",
        }
        pq = ParsedQuestion.from_dict(data)
        assert pq.question_type == "sports"
        assert pq.key_entities == ["FIFA", "World Cup"]
        assert pq.time_window == "2026"

    def test_roundtrip(self):
        """to_dict() → from_dict() 应保持一致"""
        original = ParsedQuestion(
            question_type="tech",
            key_entities=["GPT-5", "OpenAI"],
            time_window="2025",
            resolution_criteria="官方发布",
            difficulty_hint="easy",
        )
        restored = ParsedQuestion.from_dict(original.to_dict())
        assert original.to_dict() == restored.to_dict()

    def test_from_dict_with_missing_fields(self):
        """from_dict() 缺少字段时应使用默认值"""
        pq = ParsedQuestion.from_dict({})
        assert pq.question_type == "other"
        assert pq.key_entities == []
        assert pq.difficulty_hint == "medium"

    def test_from_dict_with_invalid_values(self):
        """from_dict() 传入非法值应被 __post_init__ 修正"""
        pq = ParsedQuestion.from_dict({
            "question_type": "unknown",
            "difficulty_hint": "impossible",
        })
        assert pq.question_type == "other"
        assert pq.difficulty_hint == "medium"


class TestParserJsonExtraction:
    """QP-403: 测试 Parser JSON 提取能力"""

    def test_extract_standard_json(self):
        """标准 JSON 文本应正确解析"""
        text = '{"question_type": "politics", "key_entities": ["Trump"], "time_window": "", "resolution_criteria": "", "difficulty_hint": "hard"}'
        result = QuestionParser._extract_json(text)
        assert result["question_type"] == "politics"
        assert result["key_entities"] == ["Trump"]
        assert result["difficulty_hint"] == "hard"

    def test_extract_markdown_code_block(self):
        """markdown ```json ... ``` 包裹应正确解析"""
        text = '```json\n{"question_type": "finance", "key_entities": ["Apple"], "time_window": "2024", "resolution_criteria": "", "difficulty_hint": "medium"}\n```'
        result = QuestionParser._extract_json(text)
        assert result["question_type"] == "finance"
        assert result["key_entities"] == ["Apple"]

    def test_extract_markdown_code_block_no_lang(self):
        """markdown ``` ... ``` 无语言标记也应正确解析"""
        text = '```\n{"question_type": "sports", "key_entities": ["FIFA"], "time_window": "", "resolution_criteria": "", "difficulty_hint": "easy"}\n```'
        result = QuestionParser._extract_json(text)
        assert result["question_type"] == "sports"

    def test_extract_from_noisy_text(self):
        """含前后噪音文本应能提取 JSON"""
        text = 'Here is the analysis result:\n{"question_type": "tech", "key_entities": ["GPT-5"], "time_window": "2025", "resolution_criteria": "", "difficulty_hint": "hard"}\nHope this helps!'
        result = QuestionParser._extract_json(text)
        assert result["question_type"] == "tech"
        assert result["key_entities"] == ["GPT-5"]

    def test_extract_raises_on_invalid(self):
        """完全无效的文本应抛出 ValueError"""
        with pytest.raises(ValueError):
            QuestionParser._extract_json("no json here at all")

    def test_extract_json_with_whitespace(self):
        """JSON 前后有空白应正确解析"""
        text = '  \n  {"question_type": "science", "key_entities": [], "time_window": "", "resolution_criteria": "", "difficulty_hint": "medium"}  \n  '
        result = QuestionParser._extract_json(text)
        assert result["question_type"] == "science"


class TestParserFallback:
    """QP-404: 测试 Parser 失败时返回安全默认 ParsedQuestion"""

    @pytest.fixture
    def mock_client(self):
        """创建一个 mock LLM 客户端"""
        client = MagicMock()
        client.chat_completion = AsyncMock()
        return client

    @pytest.mark.asyncio
    async def test_fallback_on_invalid_json(self, mock_client):
        """LLM 返回无效 JSON 时应返回默认 ParsedQuestion"""
        mock_client.chat_completion.return_value = "This is not JSON at all"
        parser = QuestionParser(llm_client=mock_client)
        result = await parser.parse("some question")
        assert result.question_type == "other"
        assert result.difficulty_hint == "medium"
        assert result.key_entities == []

    @pytest.mark.asyncio
    async def test_fallback_on_llm_exception(self, mock_client):
        """LLM 调用抛异常时应返回默认 ParsedQuestion"""
        mock_client.chat_completion.side_effect = Exception("API error")
        parser = QuestionParser(llm_client=mock_client)
        result = await parser.parse("some question")
        assert result.question_type == "other"
        assert result.difficulty_hint == "medium"

    @pytest.mark.asyncio
    async def test_fallback_on_empty_response(self, mock_client):
        """LLM 返回空字符串时应返回默认 ParsedQuestion"""
        mock_client.chat_completion.return_value = ""
        parser = QuestionParser(llm_client=mock_client)
        result = await parser.parse("some question")
        assert result.question_type == "other"

    @pytest.mark.asyncio
    async def test_successful_parse(self, mock_client):
        """LLM 返回有效 JSON 时应正确解析"""
        mock_client.chat_completion.return_value = '{"question_type": "politics", "key_entities": ["Biden"], "time_window": "2024", "resolution_criteria": "election result", "difficulty_hint": "hard"}'
        parser = QuestionParser(llm_client=mock_client)
        result = await parser.parse("Will Biden win?")
        assert result.question_type == "politics"
        assert result.key_entities == ["Biden"]
        assert result.difficulty_hint == "hard"

    def test_parser_prompt_exists(self):
        """QP-102: PARSER_PROMPT 应存在且包含占位符"""
        assert PARSER_PROMPT is not None
        assert "{task_description}" in PARSER_PROMPT
        assert "question_type" in PARSER_PROMPT
        assert "key_entities" in PARSER_PROMPT


class TestFeatureFlagDisabled:
    """QP-414: 测试 feature flag 禁用时走原有逻辑"""

    def test_select_strategies_without_qp(self):
        """question_parser.enabled=false 时应使用原有 STRATEGY_VARIANTS"""
        from omegaconf import OmegaConf
        from src.core.multi_path import _select_strategies, STRATEGY_VARIANTS

        cfg = OmegaConf.create({
            "question_parser": {"enabled": False},
            "evolving": {"enabled": False},
        })
        result = _select_strategies(cfg, "test question", 3)
        # Should return first 3 from STRATEGY_VARIANTS (original behavior)
        assert len(result) == 3
        assert result[0]["name"] == STRATEGY_VARIANTS[0]["name"]
        assert result[1]["name"] == STRATEGY_VARIANTS[1]["name"]
        assert result[2]["name"] == STRATEGY_VARIANTS[2]["name"]

    def test_select_strategies_no_qp_config(self):
        """无 question_parser 配置时应使用原有逻辑"""
        from omegaconf import OmegaConf
        from src.core.multi_path import _select_strategies, STRATEGY_VARIANTS

        cfg = OmegaConf.create({
            "evolving": {"enabled": False},
        })
        result = _select_strategies(cfg, "test question", 2)
        assert len(result) == 2
        assert result[0]["name"] == STRATEGY_VARIANTS[0]["name"]

    def test_select_strategies_with_qp_enabled(self):
        """question_parser.enabled=true + ParsedQuestion 时应用种子策略"""
        from omegaconf import OmegaConf
        from src.core.multi_path import _select_strategies

        cfg = OmegaConf.create({
            "question_parser": {"enabled": True},
            "evolving": {"enabled": False},
        })
        pq = ParsedQuestion(question_type="politics")
        result = _select_strategies(cfg, "test question", 3, parsed_question=pq)
        assert len(result) == 3
        # Should be compiled seed strategies
        for s in result:
            assert "name" in s
            assert "prompt_suffix" in s
            assert "max_turns" in s
            assert "_strategy_def" in s
