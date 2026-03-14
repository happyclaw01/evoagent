# Copyright (c) 2025 MiroMind
# EA-108: Experience Extractor
#
# Extracts structured learnings from strategy execution history.
# Inspired by Self-Improving Agent's Learning Entry format.
#
# Generates learnings like:
# - "breadth_first excels at search tasks (85% win rate, 15 samples)"
# - "depth_first wastes budget on creative tasks (avg 280 turns, 20% win)"
# - "lateral_thinking shows improving trend (+15% recent win rate)"
#
# Dependencies: EA-101 (records), EA-102 (profiles), EA-106 (failures)
# Design ref: EVOAGENT_DESIGN.md §7

import json
import logging
import time
from dataclasses import dataclass, field, asdict
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional

from .strategy_tracker import StrategyRecordKeeper, StrategyProfileEngine, StrategyProfile
from .failure_analyzer import FailureAnalyzer

logger = logging.getLogger(__name__)


class LearningCategory(str, Enum):
    """Learning categories following Self-Improving Agent format."""
    STRATEGY_STRENGTH = "strategy_strength"
    STRATEGY_WEAKNESS = "strategy_weakness"
    COST_INSIGHT = "cost_insight"
    FAILURE_PATTERN = "failure_pattern"
    PERFORMANCE_TREND = "performance_trend"
    TASK_STRATEGY_FIT = "task_strategy_fit"


class LearningPriority(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class LearningStatus(str, Enum):
    PENDING = "pending"
    RESOLVED = "resolved"
    PROMOTED = "promoted_to_rule"


@dataclass
class LearningEntry:
    """
    A structured learning extracted from execution history.
    Format inspired by Self-Improving Agent's Learning Entry.
    """
    entry_id: str                     # LRN-YYYYMMDD-XXX
    category: str
    priority: str = "medium"
    status: str = "pending"
    task_type: str = "all"
    strategy_name: str = ""
    summary: str = ""                  # One-line description
    detail: str = ""                   # Full explanation
    evidence: Dict[str, Any] = field(default_factory=dict)  # Supporting data
    see_also: List[str] = field(default_factory=list)        # Related entries
    timestamp: float = field(default_factory=time.time)
    recurrence_count: int = 1          # How many times this pattern observed
    
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "LearningEntry":
        valid = {f.name for f in cls.__dataclass_fields__.values()}
        return cls(**{k: v for k, v in data.items() if k in valid})
    
    def to_markdown(self) -> str:
        """Convert to markdown format for LEARNINGS.md."""
        lines = [
            f"## [{self.entry_id}] {self.category}",
            f"",
            f"**Priority**: {self.priority}",
            f"**Status**: {self.status}",
            f"**Strategy**: {self.strategy_name}",
            f"**Task Type**: {self.task_type}",
            f"",
            f"### Summary",
            f"{self.summary}",
            f"",
            f"### Detail",
            f"{self.detail}",
        ]
        
        if self.evidence:
            lines.append("")
            lines.append("### Evidence")
            for k, v in self.evidence.items():
                lines.append(f"- **{k}**: {v}")
        
        if self.see_also:
            lines.append("")
            lines.append(f"**See Also**: {', '.join(self.see_also)}")
        
        lines.append("")
        lines.append(f"**Recurrence**: {self.recurrence_count}")
        lines.append("")
        return "\n".join(lines)


class ExperienceExtractor:
    """
    EA-108: Extracts structured learnings from execution history.
    
    Scans profiles, failure reports, and execution records to generate
    LearningEntry objects that capture reusable insights.
    
    Usage:
        extractor = ExperienceExtractor(
            record_keeper, profile_engine, failure_analyzer
        )
        learnings = extractor.extract_all()
        extractor.save_learnings()
    """
    
    MIN_SAMPLES = 5
    
    def __init__(
        self,
        record_keeper: StrategyRecordKeeper,
        profile_engine: StrategyProfileEngine,
        failure_analyzer: FailureAnalyzer,
        learnings_dir: str = "data/learnings",
    ):
        self._keeper = record_keeper
        self._engine = profile_engine
        self._analyzer = failure_analyzer
        self._learnings_dir = Path(learnings_dir)
        self._learnings_dir.mkdir(parents=True, exist_ok=True)
        self._learnings: List[LearningEntry] = []
        self._counter = 0
    
    def _next_id(self) -> str:
        """Generate next learning entry ID."""
        self._counter += 1
        date_str = time.strftime("%Y%m%d")
        return f"LRN-{date_str}-{self._counter:03d}"
    
    def extract_all(self) -> List[LearningEntry]:
        """
        Extract all learnings from current data.
        
        Returns list of LearningEntry sorted by priority.
        """
        self._learnings = []
        self._counter = 0
        
        profiles = self._engine.get_all_profiles()
        
        for name, profile in profiles.items():
            if profile.total_runs < self.MIN_SAMPLES:
                continue
            
            self._extract_strengths(profile)
            self._extract_weaknesses(profile)
            self._extract_cost_insights(profile, profiles)
            self._extract_trends(profile)
            self._extract_task_fits(profile)
        
        # Extract from failure analysis
        self._extract_failure_learnings()
        
        # Sort by priority
        priority_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
        self._learnings.sort(key=lambda e: priority_order.get(e.priority, 4))
        
        return self._learnings
    
    def _extract_strengths(self, profile: StrategyProfile) -> None:
        """Extract strategy strength learnings."""
        if profile.win_rate >= 0.6:
            priority = "high" if profile.win_rate >= 0.8 else "medium"
            self._learnings.append(LearningEntry(
                entry_id=self._next_id(),
                category=LearningCategory.STRATEGY_STRENGTH.value,
                priority=priority,
                strategy_name=profile.strategy_name,
                summary=(
                    f"{profile.strategy_name} has {profile.win_rate:.0%} overall win rate "
                    f"({profile.wins}/{profile.total_runs})"
                ),
                detail=(
                    f"Strategy {profile.strategy_name} performs well overall with "
                    f"{profile.win_rate:.0%} win rate across {profile.total_runs} runs. "
                    f"Average cost: ${profile.avg_cost_usd:.4f}, "
                    f"avg turns: {profile.avg_turns:.0f}."
                ),
                evidence={
                    "win_rate": profile.win_rate,
                    "total_runs": profile.total_runs,
                    "avg_cost": profile.avg_cost_usd,
                    "avg_turns": profile.avg_turns,
                    "strengths": profile.strengths,
                },
            ))
        
        # Per-task-type strengths
        for task_type in profile.strengths:
            wr = profile.task_type_win_rates.get(task_type, 0)
            count = profile.task_type_counts.get(task_type, 0)
            self._learnings.append(LearningEntry(
                entry_id=self._next_id(),
                category=LearningCategory.TASK_STRATEGY_FIT.value,
                priority="high",
                strategy_name=profile.strategy_name,
                task_type=task_type,
                summary=(
                    f"{profile.strategy_name} excels at {task_type} tasks "
                    f"({wr:.0%} win rate, {count} samples)"
                ),
                detail=(
                    f"Strong fit between {profile.strategy_name} and {task_type} tasks. "
                    f"Recommend prioritizing this strategy for {task_type} tasks in EA-104."
                ),
                evidence={
                    "task_type_win_rate": wr,
                    "sample_count": count,
                },
            ))
    
    def _extract_weaknesses(self, profile: StrategyProfile) -> None:
        """Extract strategy weakness learnings."""
        if profile.win_rate < 0.3 and profile.total_runs >= self.MIN_SAMPLES:
            self._learnings.append(LearningEntry(
                entry_id=self._next_id(),
                category=LearningCategory.STRATEGY_WEAKNESS.value,
                priority="high",
                strategy_name=profile.strategy_name,
                summary=(
                    f"{profile.strategy_name} underperforming: {profile.win_rate:.0%} win rate "
                    f"({profile.total_runs} runs)"
                ),
                detail=(
                    f"Strategy {profile.strategy_name} shows consistently poor performance. "
                    f"Consider probation/retirement via EA-107. "
                    f"Weaknesses: {', '.join(profile.weaknesses) or 'general'}."
                ),
                evidence={
                    "win_rate": profile.win_rate,
                    "total_runs": profile.total_runs,
                    "weaknesses": profile.weaknesses,
                    "status": profile.status,
                },
            ))
        
        # Per-task-type weaknesses
        for task_type in profile.weaknesses:
            wr = profile.task_type_win_rates.get(task_type, 0)
            count = profile.task_type_counts.get(task_type, 0)
            self._learnings.append(LearningEntry(
                entry_id=self._next_id(),
                category=LearningCategory.TASK_STRATEGY_FIT.value,
                priority="medium",
                strategy_name=profile.strategy_name,
                task_type=task_type,
                summary=(
                    f"{profile.strategy_name} struggles with {task_type} tasks "
                    f"({wr:.0%} win rate, {count} samples)"
                ),
                detail=(
                    f"Poor fit between {profile.strategy_name} and {task_type} tasks. "
                    f"EA-104 should avoid selecting this strategy for {task_type}."
                ),
                evidence={
                    "task_type_win_rate": wr,
                    "sample_count": count,
                },
            ))
    
    def _extract_cost_insights(
        self, profile: StrategyProfile, all_profiles: Dict[str, StrategyProfile]
    ) -> None:
        """Extract cost-related learnings."""
        if profile.avg_cost_usd == 0:
            return
        
        avg_cost_all = sum(
            p.avg_cost_usd for p in all_profiles.values() if p.avg_cost_usd > 0
        ) / max(1, sum(1 for p in all_profiles.values() if p.avg_cost_usd > 0))
        
        if avg_cost_all == 0:
            return
        
        ratio = profile.avg_cost_usd / avg_cost_all
        
        if ratio > 2.0:
            self._learnings.append(LearningEntry(
                entry_id=self._next_id(),
                category=LearningCategory.COST_INSIGHT.value,
                priority="high" if ratio > 3.0 else "medium",
                strategy_name=profile.strategy_name,
                summary=(
                    f"{profile.strategy_name} costs {ratio:.1f}x average "
                    f"(${profile.avg_cost_usd:.4f} vs ${avg_cost_all:.4f})"
                ),
                detail=(
                    f"Strategy {profile.strategy_name} is significantly more expensive "
                    f"than average. Win rate: {profile.win_rate:.0%}. "
                    f"Consider reducing max_turns via EA-105."
                ),
                evidence={
                    "avg_cost": profile.avg_cost_usd,
                    "avg_cost_all": avg_cost_all,
                    "cost_ratio": ratio,
                    "win_rate": profile.win_rate,
                    "total_cost": profile.total_cost_usd,
                },
            ))
        elif ratio < 0.5 and profile.win_rate > 0.5:
            self._learnings.append(LearningEntry(
                entry_id=self._next_id(),
                category=LearningCategory.COST_INSIGHT.value,
                priority="low",
                strategy_name=profile.strategy_name,
                summary=(
                    f"{profile.strategy_name} is cost-efficient: {ratio:.1f}x average cost "
                    f"with {profile.win_rate:.0%} win rate"
                ),
                detail=(
                    f"Good cost/performance ratio. This strategy achieves above-average "
                    f"results at below-average cost."
                ),
                evidence={
                    "avg_cost": profile.avg_cost_usd,
                    "cost_ratio": ratio,
                    "win_rate": profile.win_rate,
                },
            ))
    
    def _extract_trends(self, profile: StrategyProfile) -> None:
        """Extract performance trend learnings."""
        if profile.trend == "stable":
            return
        
        priority = "high" if profile.trend == "declining" else "medium"
        
        self._learnings.append(LearningEntry(
            entry_id=self._next_id(),
            category=LearningCategory.PERFORMANCE_TREND.value,
            priority=priority,
            strategy_name=profile.strategy_name,
            summary=(
                f"{profile.strategy_name} is {profile.trend}: "
                f"recent win rate {profile.recent_win_rate:.0%} vs "
                f"overall {profile.win_rate:.0%}"
            ),
            detail=(
                f"{'Performance degradation detected — investigate root cause.' if profile.trend == 'declining' else 'Performance improving — strategy may be adapting well.'} "
                f"Recent win rate: {profile.recent_win_rate:.0%}, "
                f"overall: {profile.win_rate:.0%}."
            ),
            evidence={
                "trend": profile.trend,
                "recent_win_rate": profile.recent_win_rate,
                "overall_win_rate": profile.win_rate,
            },
        ))
    
    def _extract_task_fits(self, profile: StrategyProfile) -> None:
        """Extract task type fit insights (already partially covered in strengths/weaknesses)."""
        # Only add if there's a clear best task type
        if not profile.task_type_win_rates:
            return
        
        sorted_types = sorted(
            profile.task_type_win_rates.items(),
            key=lambda x: x[1],
            reverse=True,
        )
        
        if len(sorted_types) >= 2:
            best_type, best_rate = sorted_types[0]
            worst_type, worst_rate = sorted_types[-1]
            
            if best_rate - worst_rate > 0.3:
                best_count = profile.task_type_counts.get(best_type, 0)
                worst_count = profile.task_type_counts.get(worst_type, 0)
                if best_count >= 3 and worst_count >= 3:
                    self._learnings.append(LearningEntry(
                        entry_id=self._next_id(),
                        category=LearningCategory.TASK_STRATEGY_FIT.value,
                        priority="medium",
                        strategy_name=profile.strategy_name,
                        summary=(
                            f"{profile.strategy_name}: best at {best_type} ({best_rate:.0%}), "
                            f"worst at {worst_type} ({worst_rate:.0%})"
                        ),
                        detail=(
                            f"Clear task type specialization detected. "
                            f"Gap: {best_rate - worst_rate:.0%}. "
                            f"EA-104 should leverage this for strategy selection."
                        ),
                        evidence={
                            "best_type": best_type,
                            "best_rate": best_rate,
                            "worst_type": worst_type,
                            "worst_rate": worst_rate,
                            "all_rates": dict(sorted_types),
                        },
                    ))
    
    def _extract_failure_learnings(self) -> None:
        """Extract learnings from failure analysis."""
        reports = self._analyzer.analyze_all()
        
        for name, report in reports.items():
            if not report.patterns:
                continue
            
            for pattern in report.patterns:
                if pattern.severity in ("high", "critical"):
                    self._learnings.append(LearningEntry(
                        entry_id=self._next_id(),
                        category=LearningCategory.FAILURE_PATTERN.value,
                        priority=pattern.severity,
                        strategy_name=name,
                        summary=f"{name}: {pattern.description}",
                        detail=(
                            f"Pattern type: {pattern.pattern_type}. "
                            f"{pattern.recommendation}"
                        ),
                        evidence={
                            "pattern_type": pattern.pattern_type,
                            "occurrences": pattern.occurrences,
                            "severity": pattern.severity,
                        },
                    ))
    
    def save_learnings(self) -> str:
        """Save learnings as LEARNINGS.md and JSON."""
        if not self._learnings:
            self.extract_all()
        
        # Save as JSON
        json_path = self._learnings_dir / "learnings.json"
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(
                [e.to_dict() for e in self._learnings],
                f, indent=2, ensure_ascii=False,
            )
        
        # Save as Markdown
        md_path = self._learnings_dir / "LEARNINGS.md"
        lines = [
            "# EvoAgent Learnings",
            "",
            f"*Auto-generated by EA-108 Experience Extractor*",
            f"*{len(self._learnings)} learnings extracted*",
            "",
            "---",
            "",
        ]
        
        for entry in self._learnings:
            lines.append(entry.to_markdown())
            lines.append("---")
            lines.append("")
        
        with open(md_path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))
        
        logger.info(
            f"EA-108: Saved {len(self._learnings)} learnings to {self._learnings_dir}"
        )
        return str(md_path)
    
    def load_learnings(self) -> List[LearningEntry]:
        """Load learnings from JSON."""
        json_path = self._learnings_dir / "learnings.json"
        if not json_path.exists():
            return []
        
        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        
        self._learnings = [LearningEntry.from_dict(d) for d in data]
        return self._learnings
    
    def get_learnings_for_strategy(self, strategy_name: str) -> List[LearningEntry]:
        """Get learnings related to a specific strategy."""
        if not self._learnings:
            self.extract_all()
        return [e for e in self._learnings if e.strategy_name == strategy_name]
    
    def get_high_priority_learnings(self) -> List[LearningEntry]:
        """Get high and critical priority learnings."""
        if not self._learnings:
            self.extract_all()
        return [e for e in self._learnings if e.priority in ("high", "critical")]
    
    def get_summary(self) -> str:
        """Brief summary of all learnings."""
        if not self._learnings:
            self.extract_all()
        
        if not self._learnings:
            return "No learnings extracted yet."
        
        by_cat = {}
        for e in self._learnings:
            by_cat.setdefault(e.category, []).append(e)
        
        lines = [f"Total: {len(self._learnings)} learnings"]
        for cat in sorted(by_cat):
            lines.append(f"  {cat}: {len(by_cat[cat])}")
        
        high = [e for e in self._learnings if e.priority in ("high", "critical")]
        if high:
            lines.append(f"\nTop insights:")
            for e in high[:5]:
                lines.append(f"  [{e.priority.upper()}] {e.summary}")
        
        return "\n".join(lines)
