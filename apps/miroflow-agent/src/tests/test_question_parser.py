# Copyright 2026 EvoAgent Contributors
# SPDX-License-Identifier: MIT
"""
ParsedQuestion 单元测试 — QP-401, QP-402。

测试 ParsedQuestion dataclass 的创建、验证、序列化和默认值。
"""

import pytest
from src.core.question_parser import (
    ParsedQuestion,
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
