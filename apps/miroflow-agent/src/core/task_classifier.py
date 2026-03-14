# Copyright (c) 2025 MiroMind
# EA-103: Task Type Classifier
#
# Automatically classifies tasks into categories so that EA-104 can
# select the best strategy for each task type.
#
# Categories: search, compute, creative, verify, multi-hop
#
# Two modes:
# - Rule-based (default): fast, zero-cost keyword/pattern matching
# - LLM-based (optional): higher accuracy, costs one API call
#
# Design ref: EVOAGENT_DESIGN.md §5 (self-iteration Step 2)

import logging
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


class TaskType(str, Enum):
    """Task type categories."""
    SEARCH = "search"             # Find specific facts, entities, dates
    COMPUTE = "compute"           # Calculate, derive, solve numerically
    CREATIVE = "creative"         # Generate ideas, write, brainstorm
    VERIFY = "verify"             # Fact-check, validate claims
    MULTI_HOP = "multi-hop"       # Multi-step reasoning across sources
    UNKNOWN = "unknown"


# ─── Keyword patterns for rule-based classification ─────────────────────────

_PATTERNS: Dict[TaskType, List[str]] = {
    TaskType.COMPUTE: [
        # Math/calculation indicators
        r"calculat[ei]", r"comput[ei]", r"how (?:much|many)",
        r"what is the (?:sum|total|average|mean|median|percentage|ratio|rate|value|price|cost)",
        r"(?:add|subtract|multiply|divide|sum|total)",
        r"(?:formula|equation|solve|derivat)",
        r"(?:\d+\s*[\+\-\*\/\%]\s*\d+)",
        r"(?:GDP|ROI|IRR|NPV|P/E|EPS|market cap|revenue|profit|margin)",
        r"(?:统计|计算|求|多少|总计|平均|比率|百分比|增长率|市值)",
        r"(?:convert|conversion)\s+\d+",
    ],
    TaskType.VERIFY: [
        # Verification indicators
        r"(?:is it true|is this (?:true|correct|accurate|right))",
        r"(?:verify|validate|fact.?check|confirm|debunk)",
        r"(?:true or false|correct or not)",
        r"(?:是否|是不是|对不对|正确吗|真的吗|验证|核实|事实)",
    ],
    TaskType.CREATIVE: [
        # Creative/generative indicators
        r"(?:write|draft|compose|create|generate|design|brainstorm)",
        r"(?:suggest|recommend|propose|imagine|invent)",
        r"(?:story|essay|poem|article|blog|email|letter|speech|slogan)",
        r"(?:写|创作|生成|设计|建议|推荐|想象|头脑风暴|文案|文章)",
        r"(?:what (?:if|would|could|should))",
        r"(?:come up with|think of|ideas? for)",
    ],
    TaskType.MULTI_HOP: [
        # Multi-hop reasoning indicators
        r"(?:compare|contrast|relationship|connection|between|differ)",
        r"(?:step.?by.?step|first.*then|cause.*effect|because.*therefore)",
        r"(?:how does .+ relate to|what is the .+ between)",
        r"(?:explain (?:why|how)|analyze|evaluate|assess)",
        r"(?:比较|对比|关系|区别|联系|因果|分析|评估)",
        r"(?:pros? and cons?|advantages? and disadvantages?|trade.?offs?)",
        r"(?:timeline|chronolog|sequence of events|history of)",
    ],
    TaskType.SEARCH: [
        # Search/lookup indicators (broadest, checked last)
        r"(?:who (?:is|was|are|were)|what (?:is|was|are|were))",
        r"(?:when (?:did|was|is|will)|where (?:is|was|are|did))",
        r"(?:find|search|look up|locate|identify|list|name)",
        r"(?:which|whose|whom)",
        r"(?:谁|什么|哪个|哪里|何时|找|搜索|查找|列出)",
        r"(?:definition|meaning|what does .+ mean)",
        r"(?:latest|recent|current|today|now|updated)",
    ],
}

# Priority order for classification (more specific types first)
_TYPE_PRIORITY = [
    TaskType.COMPUTE,
    TaskType.VERIFY,
    TaskType.CREATIVE,
    TaskType.MULTI_HOP,
    TaskType.SEARCH,
]


@dataclass
class ClassificationResult:
    """Result of task classification."""
    task_type: TaskType
    confidence: float               # 0.0 to 1.0
    scores: Dict[str, float] = field(default_factory=dict)  # All type scores
    method: str = "rule"            # "rule" or "llm"
    matched_patterns: List[str] = field(default_factory=list)
    
    def to_dict(self) -> Dict:
        return {
            "task_type": self.task_type.value,
            "confidence": round(self.confidence, 3),
            "scores": {k: round(v, 3) for k, v in self.scores.items()},
            "method": self.method,
            "matched_patterns": self.matched_patterns,
        }


class TaskClassifier:
    """
    EA-103: Classifies tasks into categories for strategy selection.
    
    Usage:
        classifier = TaskClassifier()
        result = classifier.classify("What is the GDP growth rate of China in 2024?")
        # result.task_type = TaskType.COMPUTE
        # result.confidence = 0.8
    """
    
    # Bonus for tasks that match multiple patterns of the same type
    MULTI_MATCH_BONUS = 0.15
    # Base confidence when only one pattern matches
    BASE_CONFIDENCE = 0.6
    # Minimum confidence to return a non-UNKNOWN type
    MIN_CONFIDENCE = 0.3
    
    def classify(self, task_description: str) -> ClassificationResult:
        """
        Classify a task using rule-based pattern matching.
        
        Args:
            task_description: The task/question text.
        
        Returns:
            ClassificationResult with type, confidence, and scores.
        """
        if not task_description or not task_description.strip():
            return ClassificationResult(
                task_type=TaskType.UNKNOWN,
                confidence=0.0,
                method="rule",
            )
        
        text = task_description.lower().strip()
        scores: Dict[str, float] = {}
        all_matches: Dict[str, List[str]] = {}
        
        for task_type in _TYPE_PRIORITY:
            patterns = _PATTERNS[task_type]
            matches = []
            for pattern in patterns:
                if re.search(pattern, text, re.IGNORECASE):
                    matches.append(pattern)
            
            if matches:
                # Score: base + bonus for each additional match
                score = self.BASE_CONFIDENCE + (len(matches) - 1) * self.MULTI_MATCH_BONUS
                score = min(score, 1.0)
            else:
                score = 0.0
            
            scores[task_type.value] = score
            all_matches[task_type.value] = matches
        
        # Apply heuristics for ambiguous cases
        scores = self._apply_heuristics(text, scores)
        
        # Select best type
        if not any(s > 0 for s in scores.values()):
            return ClassificationResult(
                task_type=TaskType.UNKNOWN,
                confidence=0.0,
                scores=scores,
                method="rule",
            )
        
        best_type = max(scores, key=lambda k: scores[k])
        best_score = scores[best_type]
        
        if best_score < self.MIN_CONFIDENCE:
            return ClassificationResult(
                task_type=TaskType.UNKNOWN,
                confidence=best_score,
                scores=scores,
                method="rule",
            )
        
        # Adjust confidence based on margin over second-best
        sorted_scores = sorted(scores.values(), reverse=True)
        if len(sorted_scores) >= 2 and sorted_scores[1] > 0:
            margin = sorted_scores[0] - sorted_scores[1]
            # Higher margin → higher confidence
            confidence = min(best_score + margin * 0.2, 1.0)
        else:
            confidence = best_score
        
        return ClassificationResult(
            task_type=TaskType(best_type),
            confidence=round(confidence, 3),
            scores=scores,
            method="rule",
            matched_patterns=all_matches.get(best_type, []),
        )
    
    def _apply_heuristics(
        self, text: str, scores: Dict[str, float]
    ) -> Dict[str, float]:
        """Apply additional heuristics to refine scores."""
        
        # If task contains numbers + math operators → boost compute
        if re.search(r"\d+.*[\+\-\*\/\=].*\d+", text):
            scores["compute"] = max(scores.get("compute", 0), 0.75)
        
        # If task is very long (>200 chars) with multiple questions → multi-hop
        if len(text) > 200 and text.count("?") > 1:
            scores["multi-hop"] = max(scores.get("multi-hop", 0),
                                       scores.get("multi-hop", 0) + 0.2)
        
        # If task asks "compare X and Y" → multi-hop
        if re.search(r"compare .+ (?:and|with|to|vs) .+", text, re.IGNORECASE):
            scores["multi-hop"] = max(scores.get("multi-hop", 0), 0.75)
        
        # If task contains URL → likely search/verify
        if re.search(r"https?://", text):
            scores["search"] = max(scores.get("search", 0), 0.5)
            scores["verify"] = max(scores.get("verify", 0), 0.5)
        
        return scores
    
    def classify_batch(
        self, tasks: List[str]
    ) -> List[ClassificationResult]:
        """Classify multiple tasks."""
        return [self.classify(t) for t in tasks]
    
    def get_type_distribution(
        self, tasks: List[str]
    ) -> Dict[str, int]:
        """Get distribution of task types in a batch."""
        results = self.classify_batch(tasks)
        dist: Dict[str, int] = {}
        for r in results:
            t = r.task_type.value
            dist[t] = dist.get(t, 0) + 1
        return dist
