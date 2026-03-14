# Copyright (c) 2025 MiroMind
# EA-106: Failure Pattern Analysis
#
# Analyzes failure patterns across strategy executions to detect
# systematic issues and feed into strategy lifecycle decisions.
#
# Patterns detected:
# - Repeated failure reasons per strategy
# - Task-type-specific failure rates
# - Temporal failure clustering (sudden degradation)
# - Cost waste from failures
#
# Dependencies: EA-101 (StrategyRecordKeeper)
# Design ref: EVOAGENT_DESIGN.md §5

import logging
import time
from collections import Counter, defaultdict
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional, Tuple

from .strategy_tracker import StrategyRecordKeeper, StrategyResult

logger = logging.getLogger(__name__)


@dataclass
class FailurePattern:
    """A detected failure pattern."""
    pattern_type: str             # "repeated_reason", "task_type_weakness", "temporal_cluster", "cost_waste"
    strategy_name: str
    severity: str                 # "low", "medium", "high", "critical"
    description: str
    occurrences: int = 0
    affected_task_types: List[str] = field(default_factory=list)
    failure_reasons: List[str] = field(default_factory=list)
    recommendation: str = ""
    first_seen: float = 0.0
    last_seen: float = 0.0
    
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class FailureReport:
    """Complete failure analysis report for a strategy."""
    strategy_name: str
    total_runs: int
    total_failures: int
    failure_rate: float
    patterns: List[FailurePattern]
    wasted_cost_usd: float        # Cost spent on failed runs
    wasted_tokens: int
    top_failure_reasons: List[Tuple[str, int]]  # (reason, count)
    
    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["patterns"] = [p.to_dict() for p in self.patterns]
        return d
    
    def has_critical_patterns(self) -> bool:
        return any(p.severity == "critical" for p in self.patterns)
    
    def to_summary(self) -> str:
        """One-line summary."""
        if self.total_failures == 0:
            return f"{self.strategy_name}: no failures ({self.total_runs} runs)"
        return (
            f"{self.strategy_name}: {self.failure_rate:.0%} failure rate "
            f"({self.total_failures}/{self.total_runs}), "
            f"${self.wasted_cost_usd:.4f} wasted, "
            f"{len(self.patterns)} patterns detected"
        )


class FailureAnalyzer:
    """
    EA-106: Analyzes failure patterns in strategy execution history.
    
    Usage:
        analyzer = FailureAnalyzer(record_keeper)
        report = analyzer.analyze("breadth_first")
        if report.has_critical_patterns():
            # Consider retiring this strategy
            ...
        
        # Cross-strategy analysis
        overview = analyzer.analyze_all()
    """
    
    # A reason appearing >= this many times is a "repeated" pattern
    REPEATED_REASON_THRESHOLD = 3
    # Failure rate above this for a task type is a "weakness"
    TASK_TYPE_WEAKNESS_THRESHOLD = 0.5
    # Min samples per task type to detect weakness
    MIN_TASK_TYPE_SAMPLES = 3
    # Temporal window for cluster detection (seconds)
    TEMPORAL_WINDOW = 3600  # 1 hour
    # Min failures in window to be a cluster
    TEMPORAL_CLUSTER_MIN = 3
    # Overall failure rate thresholds for severity
    FAILURE_RATE_HIGH = 0.4
    FAILURE_RATE_CRITICAL = 0.6
    
    def __init__(self, record_keeper: StrategyRecordKeeper):
        self._keeper = record_keeper
    
    def analyze(self, strategy_name: str) -> FailureReport:
        """
        Analyze failure patterns for a specific strategy.
        
        Returns a FailureReport with detected patterns.
        """
        records = self._keeper.get_records_for_strategy(strategy_name)
        
        if not records:
            return FailureReport(
                strategy_name=strategy_name,
                total_runs=0,
                total_failures=0,
                failure_rate=0.0,
                patterns=[],
                wasted_cost_usd=0.0,
                wasted_tokens=0,
                top_failure_reasons=[],
            )
        
        failures = [r for r in records if r.status == "failed"]
        total = len(records)
        failure_rate = len(failures) / total if total > 0 else 0.0
        
        # Aggregate waste
        wasted_cost = sum(r.cost_usd for r in failures)
        wasted_tokens = sum(r.input_tokens + r.output_tokens for r in failures)
        
        # Top failure reasons
        reason_counts = Counter(
            r.failure_reason for r in failures if r.failure_reason
        )
        top_reasons = reason_counts.most_common(5)
        
        # Detect patterns
        patterns = []
        
        patterns.extend(self._detect_repeated_reasons(strategy_name, failures))
        patterns.extend(self._detect_task_type_weaknesses(strategy_name, records))
        patterns.extend(self._detect_temporal_clusters(strategy_name, failures))
        patterns.extend(self._detect_cost_waste(strategy_name, failures, records))
        
        return FailureReport(
            strategy_name=strategy_name,
            total_runs=total,
            total_failures=len(failures),
            failure_rate=failure_rate,
            patterns=patterns,
            wasted_cost_usd=wasted_cost,
            wasted_tokens=wasted_tokens,
            top_failure_reasons=top_reasons,
        )
    
    def _detect_repeated_reasons(
        self, strategy_name: str, failures: List[StrategyResult]
    ) -> List[FailurePattern]:
        """Detect failure reasons that repeat frequently."""
        patterns = []
        reason_counts = Counter(
            r.failure_reason for r in failures if r.failure_reason
        )
        
        for reason, count in reason_counts.items():
            if count >= self.REPEATED_REASON_THRESHOLD:
                timestamps = [
                    r.timestamp for r in failures if r.failure_reason == reason
                ]
                severity = "high" if count >= self.REPEATED_REASON_THRESHOLD * 2 else "medium"
                
                patterns.append(FailurePattern(
                    pattern_type="repeated_reason",
                    strategy_name=strategy_name,
                    severity=severity,
                    description=f"Reason '{reason}' occurred {count} times",
                    occurrences=count,
                    failure_reasons=[reason],
                    recommendation=f"Investigate and address '{reason}' — it's a recurring issue",
                    first_seen=min(timestamps) if timestamps else 0.0,
                    last_seen=max(timestamps) if timestamps else 0.0,
                ))
        
        return patterns
    
    def _detect_task_type_weaknesses(
        self, strategy_name: str, records: List[StrategyResult]
    ) -> List[FailurePattern]:
        """Detect task types where the strategy fails disproportionately."""
        patterns = []
        
        by_type: Dict[str, List[StrategyResult]] = defaultdict(list)
        for r in records:
            if r.task_type and r.task_type != "unknown":
                by_type[r.task_type].append(r)
        
        for task_type, type_records in by_type.items():
            if len(type_records) < self.MIN_TASK_TYPE_SAMPLES:
                continue
            
            type_failures = sum(1 for r in type_records if r.status == "failed")
            type_failure_rate = type_failures / len(type_records)
            
            if type_failure_rate >= self.TASK_TYPE_WEAKNESS_THRESHOLD:
                severity = "critical" if type_failure_rate >= self.FAILURE_RATE_CRITICAL else "high"
                
                patterns.append(FailurePattern(
                    pattern_type="task_type_weakness",
                    strategy_name=strategy_name,
                    severity=severity,
                    description=(
                        f"{type_failure_rate:.0%} failure rate on '{task_type}' tasks "
                        f"({type_failures}/{len(type_records)})"
                    ),
                    occurrences=type_failures,
                    affected_task_types=[task_type],
                    recommendation=f"Consider excluding {strategy_name} from '{task_type}' tasks",
                ))
        
        return patterns
    
    def _detect_temporal_clusters(
        self, strategy_name: str, failures: List[StrategyResult]
    ) -> List[FailurePattern]:
        """Detect clusters of failures in short time windows."""
        if len(failures) < self.TEMPORAL_CLUSTER_MIN:
            return []
        
        patterns = []
        sorted_failures = sorted(failures, key=lambda r: r.timestamp)
        
        # Sliding window
        i = 0
        detected_windows = set()
        
        while i < len(sorted_failures):
            window_start = sorted_failures[i].timestamp
            window_end = window_start + self.TEMPORAL_WINDOW
            
            window_failures = [
                f for f in sorted_failures
                if window_start <= f.timestamp <= window_end
            ]
            
            if len(window_failures) >= self.TEMPORAL_CLUSTER_MIN:
                # Avoid duplicate detections for overlapping windows
                window_key = int(window_start / self.TEMPORAL_WINDOW)
                if window_key not in detected_windows:
                    detected_windows.add(window_key)
                    
                    reasons = list(set(
                        f.failure_reason for f in window_failures if f.failure_reason
                    ))
                    
                    patterns.append(FailurePattern(
                        pattern_type="temporal_cluster",
                        strategy_name=strategy_name,
                        severity="high",
                        description=(
                            f"{len(window_failures)} failures within "
                            f"{self.TEMPORAL_WINDOW}s window"
                        ),
                        occurrences=len(window_failures),
                        failure_reasons=reasons,
                        recommendation="Check for transient infrastructure issues during this period",
                        first_seen=window_start,
                        last_seen=window_failures[-1].timestamp,
                    ))
            
            i += 1
        
        return patterns
    
    def _detect_cost_waste(
        self,
        strategy_name: str,
        failures: List[StrategyResult],
        all_records: List[StrategyResult],
    ) -> List[FailurePattern]:
        """Detect excessive cost waste from failures."""
        if not failures:
            return []
        
        total_cost = sum(r.cost_usd for r in all_records)
        wasted_cost = sum(r.cost_usd for r in failures)
        
        if total_cost == 0:
            return []
        
        waste_ratio = wasted_cost / total_cost
        
        if waste_ratio > 0.3:  # More than 30% of cost wasted on failures
            severity = "critical" if waste_ratio > 0.5 else "high"
            return [FailurePattern(
                pattern_type="cost_waste",
                strategy_name=strategy_name,
                severity=severity,
                description=(
                    f"{waste_ratio:.0%} of total cost (${wasted_cost:.4f}/"
                    f"${total_cost:.4f}) wasted on failed runs"
                ),
                occurrences=len(failures),
                recommendation=(
                    "Reduce max_turns for this strategy or add earlier "
                    "failure detection to cut losses"
                ),
            )]
        
        return []
    
    def analyze_all(self) -> Dict[str, FailureReport]:
        """Analyze failure patterns for all strategies."""
        strategy_names = self._keeper.get_strategy_names()
        return {name: self.analyze(name) for name in strategy_names}
    
    def get_strategies_needing_attention(
        self,
        max_failure_rate: float = 0.4,
    ) -> List[str]:
        """Get strategies with failure rate above threshold."""
        reports = self.analyze_all()
        return [
            name for name, report in reports.items()
            if report.failure_rate > max_failure_rate and report.total_runs >= 5
        ]
    
    def get_failure_summary(self) -> str:
        """One-line-per-strategy failure overview."""
        reports = self.analyze_all()
        if not reports:
            return "No failure data yet."
        
        lines = []
        for name in sorted(reports):
            lines.append(reports[name].to_summary())
        return "\n".join(lines)
