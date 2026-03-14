# Copyright (c) 2025 MiroMind
# EA-101: Strategy Record Keeper + EA-102: Strategy Profile Engine
#
# EA-101 records raw results after each multi-path task execution:
#   {strategy, task_type, is_winner, turns, cost, failure_reason, ...}
#
# EA-102 aggregates historical records into strategy profiles:
#   {win_rate, avg_cost, task_type_affinity, strengths, weaknesses, sample_count}
#
# Storage: JSON files in configurable directory (future: EA-307 OpenViking)
# Design ref: EVOAGENT_DESIGN.md §5 (self-iteration flow)

import json
import logging
import os
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from collections import Counter, defaultdict

logger = logging.getLogger(__name__)


# ─── EA-101: Strategy Record Keeper ─────────────────────────────────────────


@dataclass
class StrategyResult:
    """A single task execution result for a strategy."""
    task_id: str
    strategy_name: str
    task_type: str = "unknown"        # search / compute / creative / verify / multi-hop
    is_winner: bool = False           # Whether this strategy's answer was selected
    final_answer: str = ""
    turns_used: int = 0
    max_turns: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    duration_seconds: float = 0.0
    status: str = "success"           # success / failed / cancelled
    failure_reason: str = ""
    timestamp: float = field(default_factory=time.time)
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "StrategyResult":
        # Handle extra fields gracefully
        valid_fields = {f.name for f in cls.__dataclass_fields__.values()}
        filtered = {k: v for k, v in data.items() if k in valid_fields}
        return cls(**filtered)


class StrategyRecordKeeper:
    """
    EA-101: Records strategy execution results to persistent storage.
    
    Each task execution produces one StrategyResult per path. These are
    stored as JSON files for later aggregation by the Profile Engine (EA-102).
    
    Usage:
        keeper = StrategyRecordKeeper(data_dir="data/strategy_results")
        keeper.record(StrategyResult(
            task_id="task_001",
            strategy_name="breadth_first",
            is_winner=True,
            turns_used=15,
            cost_usd=0.012,
        ))
    """
    
    def __init__(self, data_dir: str = "data/strategy_results"):
        self._data_dir = Path(data_dir)
        self._data_dir.mkdir(parents=True, exist_ok=True)
        self._records: List[StrategyResult] = []
        self._loaded = False
    
    def record(self, result: StrategyResult) -> str:
        """
        Record a strategy execution result.
        
        Args:
            result: The strategy result to record.
        
        Returns:
            Path to the saved file.
        """
        self._records.append(result)
        
        # Save individual result file
        filename = f"{result.task_id}_{result.strategy_name}_{int(result.timestamp)}.json"
        filepath = self._data_dir / filename
        
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(result.to_dict(), f, indent=2, ensure_ascii=False)
        
        logger.debug(
            f"EA-101: Recorded {result.strategy_name} "
            f"({'WIN' if result.is_winner else 'LOSS'}) "
            f"for task {result.task_id}"
        )
        
        return str(filepath)
    
    def record_batch(self, results: List[StrategyResult]) -> List[str]:
        """Record multiple results from a single multi-path run."""
        return [self.record(r) for r in results]
    
    def load_all(self) -> List[StrategyResult]:
        """Load all historical records from disk."""
        if self._loaded and self._records:
            return self._records
        
        records = []
        for filepath in sorted(self._data_dir.glob("*.json")):
            try:
                with open(filepath, "r", encoding="utf-8") as f:
                    data = json.load(f)
                records.append(StrategyResult.from_dict(data))
            except (json.JSONDecodeError, KeyError) as e:
                logger.warning(f"EA-101: Skipping corrupt file {filepath}: {e}")
        
        self._records = records
        self._loaded = True
        return records
    
    def get_records_for_strategy(self, strategy_name: str) -> List[StrategyResult]:
        """Get all records for a specific strategy."""
        records = self.load_all()
        return [r for r in records if r.strategy_name == strategy_name]
    
    def get_records_for_task_type(self, task_type: str) -> List[StrategyResult]:
        """Get all records for a specific task type."""
        records = self.load_all()
        return [r for r in records if r.task_type == task_type]
    
    def get_recent_records(self, n: int = 20) -> List[StrategyResult]:
        """Get the N most recent records."""
        records = self.load_all()
        return sorted(records, key=lambda r: r.timestamp, reverse=True)[:n]
    
    @property
    def total_records(self) -> int:
        return len(self.load_all())
    
    def get_strategy_names(self) -> List[str]:
        """Get all unique strategy names in records."""
        records = self.load_all()
        return list(set(r.strategy_name for r in records))
    
    def clear(self) -> None:
        """Clear in-memory records (does NOT delete files)."""
        self._records.clear()
        self._loaded = False


# ─── EA-102: Strategy Profile Engine ────────────────────────────────────────


@dataclass
class StrategyProfile:
    """Aggregated profile for a single strategy."""
    strategy_name: str
    total_runs: int = 0
    wins: int = 0
    losses: int = 0
    failures: int = 0
    cancellations: int = 0
    win_rate: float = 0.0
    avg_cost_usd: float = 0.0
    avg_turns: float = 0.0
    avg_duration_seconds: float = 0.0
    total_cost_usd: float = 0.0
    total_tokens: int = 0
    # Task type affinity: {task_type: win_rate}
    task_type_win_rates: Dict[str, float] = field(default_factory=dict)
    task_type_counts: Dict[str, int] = field(default_factory=dict)
    # Strengths and weaknesses (top task types)
    strengths: List[str] = field(default_factory=list)   # task types with high win rate
    weaknesses: List[str] = field(default_factory=list)  # task types with low win rate
    # Lifecycle
    status: str = "active"            # active / probation / retired
    last_updated: float = field(default_factory=time.time)
    # Trend
    recent_win_rate: float = 0.0      # Win rate over last N runs
    trend: str = "stable"             # improving / declining / stable
    
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "StrategyProfile":
        valid_fields = {f.name for f in cls.__dataclass_fields__.values()}
        filtered = {k: v for k, v in data.items() if k in valid_fields}
        return cls(**filtered)
    
    def to_summary(self) -> str:
        """One-line summary for L0 context loading."""
        return (
            f"{self.strategy_name}: {self.win_rate:.0%} win rate "
            f"({self.wins}/{self.total_runs}), "
            f"avg ${self.avg_cost_usd:.4f}/run, "
            f"status={self.status}, trend={self.trend}"
        )


class StrategyProfileEngine:
    """
    EA-102: Aggregates historical records into strategy profiles.
    
    Reads from EA-101's StrategyRecordKeeper and produces/updates
    StrategyProfile objects with win rates, cost analysis, task type
    affinity, strengths/weaknesses, and trend detection.
    
    Usage:
        keeper = StrategyRecordKeeper(data_dir="data/strategy_results")
        engine = StrategyProfileEngine(
            record_keeper=keeper,
            profile_dir="data/strategy_profiles",
        )
        profiles = engine.build_profiles()
        engine.save_profiles()
        
        # Get best strategy for a task type
        best = engine.get_best_strategy_for("search")
    """
    
    MIN_SAMPLES_FOR_TREND = 5
    RECENT_WINDOW = 10            # Last N runs for trend detection
    STRENGTH_THRESHOLD = 0.65     # Win rate above this = strength
    WEAKNESS_THRESHOLD = 0.35     # Win rate below this = weakness
    MIN_TASK_TYPE_SAMPLES = 3     # Minimum runs to classify as strength/weakness
    PROBATION_THRESHOLD = 0.25    # Win rate below this = probation
    RETIREMENT_THRESHOLD = 0.15   # Win rate below this after N runs = retired
    RETIREMENT_MIN_SAMPLES = 20   # Minimum runs before retirement
    
    def __init__(
        self,
        record_keeper: StrategyRecordKeeper,
        profile_dir: str = "data/strategy_profiles",
    ):
        self._keeper = record_keeper
        self._profile_dir = Path(profile_dir)
        self._profile_dir.mkdir(parents=True, exist_ok=True)
        self._profiles: Dict[str, StrategyProfile] = {}
    
    def build_profiles(self) -> Dict[str, StrategyProfile]:
        """
        Build/rebuild all strategy profiles from historical records.
        
        Returns:
            Dict mapping strategy_name to StrategyProfile.
        """
        records = self._keeper.load_all()
        
        if not records:
            return {}
        
        # Group records by strategy
        by_strategy: Dict[str, List[StrategyResult]] = defaultdict(list)
        for r in records:
            by_strategy[r.strategy_name].append(r)
        
        profiles = {}
        for strategy_name, strategy_records in by_strategy.items():
            profile = self._build_single_profile(strategy_name, strategy_records)
            profiles[strategy_name] = profile
        
        self._profiles = profiles
        return profiles
    
    def _build_single_profile(
        self,
        strategy_name: str,
        records: List[StrategyResult],
    ) -> StrategyProfile:
        """Build a profile for a single strategy."""
        # Sort by timestamp
        records = sorted(records, key=lambda r: r.timestamp)
        
        total = len(records)
        wins = sum(1 for r in records if r.is_winner)
        failures = sum(1 for r in records if r.status == "failed")
        cancellations = sum(1 for r in records if r.status == "cancelled")
        completed = [r for r in records if r.status == "success"]
        losses = len(completed) - wins
        
        win_rate = wins / total if total > 0 else 0.0
        
        # Cost and turn averages (only from completed runs)
        costs = [r.cost_usd for r in completed if r.cost_usd > 0]
        turns = [r.turns_used for r in completed if r.turns_used > 0]
        durations = [r.duration_seconds for r in completed if r.duration_seconds > 0]
        
        avg_cost = sum(costs) / len(costs) if costs else 0.0
        avg_turns = sum(turns) / len(turns) if turns else 0.0
        avg_duration = sum(durations) / len(durations) if durations else 0.0
        total_cost = sum(r.cost_usd for r in records)
        total_tokens = sum(r.input_tokens + r.output_tokens for r in records)
        
        # Task type analysis
        task_type_win_rates, task_type_counts = self._compute_task_type_stats(records)
        
        # Strengths and weaknesses
        strengths = [
            tt for tt, wr in task_type_win_rates.items()
            if wr >= self.STRENGTH_THRESHOLD
            and task_type_counts.get(tt, 0) >= self.MIN_TASK_TYPE_SAMPLES
        ]
        weaknesses = [
            tt for tt, wr in task_type_win_rates.items()
            if wr <= self.WEAKNESS_THRESHOLD
            and task_type_counts.get(tt, 0) >= self.MIN_TASK_TYPE_SAMPLES
        ]
        
        # Trend detection
        recent_win_rate, trend = self._detect_trend(records)
        
        # Lifecycle status
        status = self._determine_status(win_rate, total, trend)
        
        return StrategyProfile(
            strategy_name=strategy_name,
            total_runs=total,
            wins=wins,
            losses=losses,
            failures=failures,
            cancellations=cancellations,
            win_rate=win_rate,
            avg_cost_usd=avg_cost,
            avg_turns=avg_turns,
            avg_duration_seconds=avg_duration,
            total_cost_usd=total_cost,
            total_tokens=total_tokens,
            task_type_win_rates=task_type_win_rates,
            task_type_counts=task_type_counts,
            strengths=strengths,
            weaknesses=weaknesses,
            status=status,
            recent_win_rate=recent_win_rate,
            trend=trend,
        )
    
    def _compute_task_type_stats(
        self, records: List[StrategyResult]
    ) -> Tuple[Dict[str, float], Dict[str, int]]:
        """Compute win rate per task type."""
        by_type: Dict[str, List[StrategyResult]] = defaultdict(list)
        for r in records:
            if r.task_type and r.task_type != "unknown":
                by_type[r.task_type].append(r)
        
        win_rates = {}
        counts = {}
        for task_type, type_records in by_type.items():
            total = len(type_records)
            wins = sum(1 for r in type_records if r.is_winner)
            win_rates[task_type] = wins / total if total > 0 else 0.0
            counts[task_type] = total
        
        return win_rates, counts
    
    def _detect_trend(
        self, records: List[StrategyResult]
    ) -> Tuple[float, str]:
        """Detect performance trend from recent records."""
        if len(records) < self.MIN_SAMPLES_FOR_TREND:
            return 0.0, "stable"
        
        recent = records[-self.RECENT_WINDOW:]
        older = records[:-self.RECENT_WINDOW] if len(records) > self.RECENT_WINDOW else []
        
        recent_wins = sum(1 for r in recent if r.is_winner)
        recent_rate = recent_wins / len(recent)
        
        if not older:
            return recent_rate, "stable"
        
        older_wins = sum(1 for r in older if r.is_winner)
        older_rate = older_wins / len(older)
        
        diff = recent_rate - older_rate
        if diff > 0.1:
            trend = "improving"
        elif diff < -0.1:
            trend = "declining"
        else:
            trend = "stable"
        
        return recent_rate, trend
    
    def _determine_status(
        self, win_rate: float, total_runs: int, trend: str
    ) -> str:
        """Determine strategy lifecycle status."""
        if total_runs < self.MIN_SAMPLES_FOR_TREND:
            return "active"  # Not enough data to judge
        
        if (win_rate < self.RETIREMENT_THRESHOLD
                and total_runs >= self.RETIREMENT_MIN_SAMPLES):
            return "retired"
        
        if win_rate < self.PROBATION_THRESHOLD:
            return "probation"
        
        return "active"
    
    def get_profile(self, strategy_name: str) -> Optional[StrategyProfile]:
        """Get profile for a specific strategy."""
        if not self._profiles:
            self.build_profiles()
        return self._profiles.get(strategy_name)
    
    def get_all_profiles(self) -> Dict[str, StrategyProfile]:
        """Get all profiles."""
        if not self._profiles:
            self.build_profiles()
        return dict(self._profiles)
    
    def get_active_profiles(self) -> Dict[str, StrategyProfile]:
        """Get only active (non-retired) profiles."""
        if not self._profiles:
            self.build_profiles()
        return {
            name: p for name, p in self._profiles.items()
            if p.status != "retired"
        }
    
    def get_best_strategy_for(self, task_type: str) -> Optional[str]:
        """
        Get the best strategy for a given task type.
        
        Returns the strategy with the highest win rate for this task type,
        considering only active strategies with sufficient samples.
        """
        if not self._profiles:
            self.build_profiles()
        
        candidates = []
        for name, profile in self._profiles.items():
            if profile.status == "retired":
                continue
            if task_type in profile.task_type_win_rates:
                count = profile.task_type_counts.get(task_type, 0)
                if count >= self.MIN_TASK_TYPE_SAMPLES:
                    candidates.append((
                        name,
                        profile.task_type_win_rates[task_type],
                        count,
                    ))
        
        if not candidates:
            return None
        
        # Sort by win rate descending, then by sample count
        candidates.sort(key=lambda x: (x[1], x[2]), reverse=True)
        return candidates[0][0]
    
    def get_rankings(self, task_type: Optional[str] = None) -> List[Tuple[str, float, int]]:
        """
        Get strategies ranked by win rate.
        
        Args:
            task_type: If specified, rank by task-type-specific win rate.
        
        Returns:
            List of (strategy_name, win_rate, sample_count) sorted by win rate desc.
        """
        if not self._profiles:
            self.build_profiles()
        
        rankings = []
        for name, profile in self._profiles.items():
            if profile.status == "retired":
                continue
            
            if task_type and task_type in profile.task_type_win_rates:
                wr = profile.task_type_win_rates[task_type]
                count = profile.task_type_counts.get(task_type, 0)
            else:
                wr = profile.win_rate
                count = profile.total_runs
            
            rankings.append((name, wr, count))
        
        rankings.sort(key=lambda x: (x[1], x[2]), reverse=True)
        return rankings
    
    def get_l0_summary(self) -> str:
        """Generate L0 summary (~100 tokens) for context loading."""
        if not self._profiles:
            self.build_profiles()
        
        if not self._profiles:
            return "No strategy data yet."
        
        total_runs = sum(p.total_runs for p in self._profiles.values())
        active = sum(1 for p in self._profiles.values() if p.status == "active")
        retired = sum(1 for p in self._profiles.values() if p.status == "retired")
        
        lines = [f"Strategies: {active} active, {retired} retired, {total_runs} total runs."]
        for name, profile in sorted(
            self._profiles.items(),
            key=lambda x: x[1].win_rate,
            reverse=True,
        ):
            lines.append(profile.to_summary())
        
        return "\n".join(lines)
    
    def save_profiles(self) -> List[str]:
        """Save all profiles to disk."""
        if not self._profiles:
            self.build_profiles()
        
        saved = []
        for name, profile in self._profiles.items():
            filepath = self._profile_dir / f"{name}.json"
            with open(filepath, "w", encoding="utf-8") as f:
                json.dump(profile.to_dict(), f, indent=2, ensure_ascii=False)
            saved.append(str(filepath))
        
        # Also save L0 summary
        summary_path = self._profile_dir / ".abstract"
        with open(summary_path, "w", encoding="utf-8") as f:
            f.write(self.get_l0_summary())
        saved.append(str(summary_path))
        
        logger.info(f"EA-102: Saved {len(self._profiles)} profiles to {self._profile_dir}")
        return saved
    
    def load_profiles(self) -> Dict[str, StrategyProfile]:
        """Load profiles from disk."""
        profiles = {}
        for filepath in self._profile_dir.glob("*.json"):
            try:
                with open(filepath, "r", encoding="utf-8") as f:
                    data = json.load(f)
                profile = StrategyProfile.from_dict(data)
                profiles[profile.strategy_name] = profile
            except (json.JSONDecodeError, KeyError) as e:
                logger.warning(f"EA-102: Skipping corrupt profile {filepath}: {e}")
        
        self._profiles = profiles
        return profiles
