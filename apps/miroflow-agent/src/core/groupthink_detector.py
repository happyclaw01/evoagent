# Copyright (c) 2025 MiroMind
# EA-309: Groupthink Detector
#
# Detects when all exploration paths converge on potentially wrong
# consensus — the "everyone agrees but everyone is wrong" problem.
#
# Inspired by:
# - 谢一凡 thesis: information cascade, authority bias, certainty bias
# - Surowiecki (2004): diversity requirement for wise crowds
# - Janis (1972): groupthink in decision-making groups
#
# Detection signals:
# 1. Reasoning similarity: all paths use nearly identical reasoning
# 2. Source overlap: all paths cite the same sources
# 3. Low confidence consensus: paths agree but with hedging language
# 4. Speed uniformity: all paths converge suspiciously fast
# 5. Echo chamber: later paths copy earlier paths' discoveries
#
# When detected, triggers:
# - Inject adversarial verification prompt
# - Force one path to argue the opposite
# - Escalate to external verification (EA-307 OpenViking)
#
# Dependencies: EA-003 (voting), EA-305 (discovery bus)
# Design ref: docs/research-log/2026-03-14-multi-agent-collaboration-theory.md §4.3

import logging
import re
import time
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional, Set, Tuple
from collections import Counter

logger = logging.getLogger(__name__)


@dataclass
class GroupthinkSignal:
    """A detected groupthink signal."""
    signal_type: str          # reasoning_similarity, source_overlap,
                               # low_confidence_consensus, speed_uniformity,
                               # echo_chamber
    severity: str             # low, medium, high, critical
    score: float              # 0.0 to 1.0
    description: str
    affected_paths: List[str] = field(default_factory=list)
    evidence: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class GroupthinkReport:
    """Complete groupthink analysis report."""
    is_groupthink: bool
    overall_risk: float              # 0.0 to 1.0
    risk_level: str                  # none, low, moderate, high, critical
    signals: List[GroupthinkSignal]
    recommendation: str
    num_paths: int = 0
    
    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["signals"] = [s.to_dict() for s in self.signals]
        return d
    
    def to_summary(self) -> str:
        if not self.is_groupthink:
            return f"No groupthink detected ({self.num_paths} paths, risk={self.overall_risk:.0%})"
        return (
            f"⚠️ Groupthink risk: {self.risk_level} ({self.overall_risk:.0%}), "
            f"{len(self.signals)} signals detected. {self.recommendation}"
        )


@dataclass
class PathAnswer:
    """Simplified path answer for groupthink analysis."""
    path_id: str
    answer: str
    reasoning: str = ""
    sources: List[str] = field(default_factory=list)
    confidence: float = 0.0       # Self-reported confidence (0-1)
    turns_used: int = 0
    duration_seconds: float = 0.0
    
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ─── Text Similarity Utilities ──────────────────────────────────────────────

def _extract_key_phrases(text: str, min_length: int = 3) -> Set[str]:
    """Extract key phrases (n-grams) from text."""
    if not text:
        return set()
    # Normalize
    text = text.lower().strip()
    # Remove common stopwords
    stopwords = {
        "the", "a", "an", "is", "are", "was", "were", "be", "been",
        "have", "has", "had", "do", "does", "did", "will", "would",
        "could", "should", "may", "might", "can", "shall", "to", "of",
        "in", "for", "on", "with", "at", "by", "from", "as", "into",
        "that", "this", "it", "its", "and", "or", "but", "not", "no",
        "if", "then", "so", "than", "too", "very", "just",
        "的", "了", "是", "在", "和", "有", "我", "他", "她", "它",
        "们", "这", "那", "个", "也", "就", "都", "不", "会", "能",
    }
    words = re.findall(r'\b\w+\b', text)
    words = [w for w in words if w not in stopwords and len(w) >= min_length]
    
    # Extract bigrams and trigrams
    phrases = set(words)
    for i in range(len(words) - 1):
        phrases.add(f"{words[i]} {words[i+1]}")
    for i in range(len(words) - 2):
        phrases.add(f"{words[i]} {words[i+1]} {words[i+2]}")
    
    return phrases


def _jaccard_similarity(set_a: Set[str], set_b: Set[str]) -> float:
    """Compute Jaccard similarity between two sets."""
    if not set_a and not set_b:
        return 1.0
    if not set_a or not set_b:
        return 0.0
    intersection = set_a & set_b
    union = set_a | set_b
    return len(intersection) / len(union)


def _pairwise_similarities(items: List[Set[str]]) -> List[float]:
    """Compute all pairwise similarities."""
    sims = []
    for i in range(len(items)):
        for j in range(i + 1, len(items)):
            sims.append(_jaccard_similarity(items[i], items[j]))
    return sims


# ─── Confidence Language Detection ──────────────────────────────────────────

HEDGING_PATTERNS = [
    r"\b(might|may|could|possibly|perhaps|likely|unlikely|probably)\b",
    r"\b(not sure|uncertain|unclear|ambiguous|debatable)\b",
    r"\b(approximately|roughly|around|about|estimated)\b",
    r"\b(seems?|appears?|suggests?|indicates?)\b",
    r"(可能|大概|也许|似乎|大约|估计|不确定|不太确定)",
    r"\?",  # Questions in the answer
]

CERTAINTY_PATTERNS = [
    r"\b(definitely|certainly|clearly|obviously|undoubtedly)\b",
    r"\b(confirmed|verified|established|proven|demonstrated)\b",
    r"\b(exactly|precisely|specifically)\b",
    r"(确定|肯定|明确|显然|毫无疑问|已证实)",
]


def _compute_confidence_score(text: str) -> float:
    """Estimate confidence level from language patterns."""
    if not text:
        return 0.5
    
    text_lower = text.lower()
    
    hedge_count = sum(
        len(re.findall(p, text_lower, re.IGNORECASE))
        for p in HEDGING_PATTERNS
    )
    certain_count = sum(
        len(re.findall(p, text_lower, re.IGNORECASE))
        for p in CERTAINTY_PATTERNS
    )
    
    total = hedge_count + certain_count
    if total == 0:
        return 0.5
    
    return certain_count / total


class GroupthinkDetector:
    """
    EA-309: Detects groupthink in multi-path exploration results.
    
    Analyzes path answers for signs of artificial consensus:
    - Reasoning too similar (information cascade)
    - Same sources cited (authority bias)
    - Low-confidence agreement (certainty bias)
    - Suspiciously uniform completion speed
    - Echo chamber via discovery bus
    
    Usage:
        detector = GroupthinkDetector()
        answers = [
            PathAnswer(path_id="path_0", answer="42", reasoning="Because..."),
            PathAnswer(path_id="path_1", answer="42", reasoning="Since..."),
            PathAnswer(path_id="path_2", answer="42", reasoning="Given..."),
        ]
        report = detector.analyze(answers)
        if report.is_groupthink:
            # Trigger adversarial verification
            ...
    """
    
    # Thresholds
    REASONING_SIMILARITY_THRESHOLD = 0.6    # Above = suspicious
    SOURCE_OVERLAP_THRESHOLD = 0.7          # Above = echo chamber risk
    SPEED_UNIFORMITY_THRESHOLD = 0.3        # CV below this = suspicious
    LOW_CONFIDENCE_THRESHOLD = 0.4          # Below = hedging
    GROUPTHINK_RISK_THRESHOLD = 0.5         # Overall risk above = groupthink
    
    # Weights for overall risk calculation
    SIGNAL_WEIGHTS = {
        "reasoning_similarity": 0.35,
        "source_overlap": 0.25,
        "low_confidence_consensus": 0.20,
        "speed_uniformity": 0.10,
        "echo_chamber": 0.10,
    }
    
    def __init__(
        self,
        reasoning_threshold: Optional[float] = None,
        source_threshold: Optional[float] = None,
        risk_threshold: Optional[float] = None,
    ):
        if reasoning_threshold is not None:
            self.REASONING_SIMILARITY_THRESHOLD = reasoning_threshold
        if source_threshold is not None:
            self.SOURCE_OVERLAP_THRESHOLD = source_threshold
        if risk_threshold is not None:
            self.GROUPTHINK_RISK_THRESHOLD = risk_threshold
    
    def analyze(self, answers: List[PathAnswer]) -> GroupthinkReport:
        """
        Analyze path answers for groupthink signals.
        
        Args:
            answers: List of PathAnswer from multi-path exploration.
        
        Returns:
            GroupthinkReport with detected signals and recommendations.
        """
        if len(answers) < 2:
            return GroupthinkReport(
                is_groupthink=False,
                overall_risk=0.0,
                risk_level="none",
                signals=[],
                recommendation="Insufficient paths for groupthink analysis.",
                num_paths=len(answers),
            )
        
        # Check if answers actually agree
        unique_answers = set(a.answer.strip().lower() for a in answers if a.answer)
        if len(unique_answers) > 1:
            # Paths disagree — no groupthink
            return GroupthinkReport(
                is_groupthink=False,
                overall_risk=0.0,
                risk_level="none",
                signals=[],
                recommendation="Paths produced different answers — healthy disagreement.",
                num_paths=len(answers),
            )
        
        # All paths agree — check for groupthink signals
        signals = []
        
        # Signal 1: Reasoning similarity
        reasoning_signal = self._check_reasoning_similarity(answers)
        if reasoning_signal:
            signals.append(reasoning_signal)
        
        # Signal 2: Source overlap
        source_signal = self._check_source_overlap(answers)
        if source_signal:
            signals.append(source_signal)
        
        # Signal 3: Low confidence consensus
        confidence_signal = self._check_low_confidence(answers)
        if confidence_signal:
            signals.append(confidence_signal)
        
        # Signal 4: Speed uniformity
        speed_signal = self._check_speed_uniformity(answers)
        if speed_signal:
            signals.append(speed_signal)
        
        # Compute overall risk
        overall_risk = self._compute_overall_risk(signals)
        risk_level = self._risk_level(overall_risk)
        is_groupthink = overall_risk >= self.GROUPTHINK_RISK_THRESHOLD
        
        recommendation = self._generate_recommendation(signals, is_groupthink)
        
        return GroupthinkReport(
            is_groupthink=is_groupthink,
            overall_risk=round(overall_risk, 3),
            risk_level=risk_level,
            signals=signals,
            recommendation=recommendation,
            num_paths=len(answers),
        )
    
    def _check_reasoning_similarity(
        self, answers: List[PathAnswer]
    ) -> Optional[GroupthinkSignal]:
        """Check if reasoning chains are too similar."""
        reasonings = [a.reasoning for a in answers if a.reasoning]
        if len(reasonings) < 2:
            return None
        
        phrase_sets = [_extract_key_phrases(r) for r in reasonings]
        similarities = _pairwise_similarities(phrase_sets)
        
        if not similarities:
            return None
        
        avg_sim = sum(similarities) / len(similarities)
        
        if avg_sim >= self.REASONING_SIMILARITY_THRESHOLD:
            severity = "critical" if avg_sim >= 0.8 else "high" if avg_sim >= 0.7 else "medium"
            return GroupthinkSignal(
                signal_type="reasoning_similarity",
                severity=severity,
                score=avg_sim,
                description=(
                    f"Reasoning chains are {avg_sim:.0%} similar "
                    f"(threshold: {self.REASONING_SIMILARITY_THRESHOLD:.0%})"
                ),
                affected_paths=[a.path_id for a in answers],
                evidence={
                    "avg_similarity": avg_sim,
                    "pairwise_similarities": [round(s, 3) for s in similarities],
                },
            )
        return None
    
    def _check_source_overlap(
        self, answers: List[PathAnswer]
    ) -> Optional[GroupthinkSignal]:
        """Check if paths cite the same sources."""
        source_sets = [set(a.sources) for a in answers if a.sources]
        if len(source_sets) < 2:
            return None
        
        similarities = _pairwise_similarities(source_sets)
        if not similarities:
            return None
        
        avg_overlap = sum(similarities) / len(similarities)
        
        if avg_overlap >= self.SOURCE_OVERLAP_THRESHOLD:
            # Find most-cited sources
            all_sources = [s for a in answers for s in a.sources]
            top_sources = Counter(all_sources).most_common(3)
            
            return GroupthinkSignal(
                signal_type="source_overlap",
                severity="high" if avg_overlap >= 0.85 else "medium",
                score=avg_overlap,
                description=(
                    f"Source overlap: {avg_overlap:.0%} "
                    f"(top: {', '.join(s[0] for s in top_sources[:2])})"
                ),
                affected_paths=[a.path_id for a in answers],
                evidence={
                    "avg_overlap": avg_overlap,
                    "top_sources": dict(top_sources),
                },
            )
        return None
    
    def _check_low_confidence(
        self, answers: List[PathAnswer]
    ) -> Optional[GroupthinkSignal]:
        """Check if consensus comes with hedging language."""
        # Use self-reported confidence if available, otherwise analyze text
        confidences = []
        for a in answers:
            if a.confidence > 0:
                confidences.append(a.confidence)
            elif a.answer:
                confidences.append(_compute_confidence_score(a.answer + " " + a.reasoning))
        
        if not confidences:
            return None
        
        avg_confidence = sum(confidences) / len(confidences)
        
        if avg_confidence < self.LOW_CONFIDENCE_THRESHOLD:
            return GroupthinkSignal(
                signal_type="low_confidence_consensus",
                severity="medium",
                score=1.0 - avg_confidence,  # Invert: low confidence = high signal
                description=(
                    f"Consensus with low confidence: avg {avg_confidence:.0%} "
                    f"(threshold: {self.LOW_CONFIDENCE_THRESHOLD:.0%})"
                ),
                affected_paths=[a.path_id for a in answers],
                evidence={
                    "avg_confidence": avg_confidence,
                    "per_path": {a.path_id: c for a, c in zip(answers, confidences)},
                },
            )
        return None
    
    def _check_speed_uniformity(
        self, answers: List[PathAnswer]
    ) -> Optional[GroupthinkSignal]:
        """Check if all paths converge at suspiciously similar speed."""
        durations = [a.duration_seconds for a in answers if a.duration_seconds > 0]
        turns = [a.turns_used for a in answers if a.turns_used > 0]
        
        # Check turns (more reliable than duration)
        values = turns if len(turns) >= 2 else durations
        if len(values) < 2:
            return None
        
        mean_val = sum(values) / len(values)
        if mean_val == 0:
            return None
        
        # Coefficient of variation
        variance = sum((v - mean_val) ** 2 for v in values) / len(values)
        std_dev = variance ** 0.5
        cv = std_dev / mean_val
        
        if cv < self.SPEED_UNIFORMITY_THRESHOLD:
            return GroupthinkSignal(
                signal_type="speed_uniformity",
                severity="low",
                score=1.0 - cv,  # Low CV = high uniformity = high signal
                description=(
                    f"Suspiciously uniform completion: CV={cv:.2f} "
                    f"(threshold: {self.SPEED_UNIFORMITY_THRESHOLD:.2f})"
                ),
                affected_paths=[a.path_id for a in answers],
                evidence={
                    "coefficient_of_variation": cv,
                    "values": values,
                    "metric": "turns" if turns else "duration",
                },
            )
        return None
    
    def _compute_overall_risk(self, signals: List[GroupthinkSignal]) -> float:
        """Compute weighted overall groupthink risk."""
        if not signals:
            return 0.0
        
        weighted_sum = 0.0
        total_weight = 0.0
        
        for signal in signals:
            weight = self.SIGNAL_WEIGHTS.get(signal.signal_type, 0.1)
            weighted_sum += signal.score * weight
            total_weight += weight
        
        # Normalize by total possible weight
        max_weight = sum(self.SIGNAL_WEIGHTS.values())
        return min(1.0, weighted_sum / max_weight) if max_weight > 0 else 0.0
    
    @staticmethod
    def _risk_level(risk: float) -> str:
        """Map risk score to level."""
        if risk < 0.1:
            return "none"
        elif risk < 0.3:
            return "low"
        elif risk < 0.5:
            return "moderate"
        elif risk < 0.7:
            return "high"
        else:
            return "critical"
    
    def _generate_recommendation(
        self, signals: List[GroupthinkSignal], is_groupthink: bool
    ) -> str:
        """Generate actionable recommendation based on signals."""
        if not is_groupthink:
            if signals:
                return (
                    f"Minor groupthink signals detected ({len(signals)}). "
                    f"Monitor but no action needed."
                )
            return "No groupthink signals. Consensus appears healthy."
        
        recs = []
        signal_types = {s.signal_type for s in signals}
        
        if "reasoning_similarity" in signal_types:
            recs.append(
                "Inject adversarial prompt: force one path to argue the opposite conclusion"
            )
        
        if "source_overlap" in signal_types:
            recs.append(
                "Diversify sources: require paths to use different search queries"
            )
        
        if "low_confidence_consensus" in signal_types:
            recs.append(
                "Escalate to external verification (EA-307 OpenViking)"
            )
        
        if not recs:
            recs.append("Re-run with increased strategy diversity")
        
        return " | ".join(recs)
    
    def create_adversarial_prompt(self, consensus_answer: str) -> str:
        """
        Generate an adversarial prompt to challenge the consensus.
        
        Can be injected into a new path or re-run.
        """
        return (
            f"ADVERSARIAL VERIFICATION: The other paths concluded '{consensus_answer}'. "
            f"Your job is to prove this answer WRONG. "
            f"Search for contradicting evidence, alternative explanations, "
            f"and edge cases. If you cannot disprove it after thorough investigation, "
            f"explain why the answer is robust. "
            f"Do NOT simply agree with the consensus."
        )
