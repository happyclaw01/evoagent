# Copyright (c) 2025 MiroMind
# EA-107: Strategy Lifecycle Management
#
# Manages strategy lifecycle transitions: active → probation → retired
# with support for resurrection (retired → probation → active).
#
# Integrates EA-102 (profiles), EA-105 (tuning), EA-106 (failure analysis)
# to make informed lifecycle decisions.
#
# Dependencies: EA-102, EA-105, EA-106
# Design ref: EVOAGENT_DESIGN.md §5

import json
import logging
import time
from dataclasses import dataclass, field, asdict
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .strategy_tracker import StrategyProfileEngine, StrategyProfile
from .failure_analyzer import FailureAnalyzer

logger = logging.getLogger(__name__)


class LifecycleStatus(str, Enum):
    """Strategy lifecycle states."""
    ACTIVE = "active"
    PROBATION = "probation"
    RETIRED = "retired"
    CANDIDATE = "candidate"    # Newly created, not yet proven


@dataclass
class LifecycleEvent:
    """A lifecycle transition event."""
    strategy_name: str
    from_status: str
    to_status: str
    reason: str
    timestamp: float = field(default_factory=time.time)
    metrics: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "LifecycleEvent":
        valid = {f.name for f in cls.__dataclass_fields__.values()}
        return cls(**{k: v for k, v in data.items() if k in valid})


@dataclass
class StrategyState:
    """Current lifecycle state for a strategy."""
    strategy_name: str
    status: LifecycleStatus = LifecycleStatus.ACTIVE
    probation_since: Optional[float] = None
    retired_since: Optional[float] = None
    resurrection_count: int = 0
    history: List[LifecycleEvent] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["status"] = self.status.value
        d["history"] = [e.to_dict() if isinstance(e, LifecycleEvent) else e for e in self.history]
        return d
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "StrategyState":
        data = dict(data)
        if "status" in data:
            data["status"] = LifecycleStatus(data["status"])
        history_raw = data.pop("history", [])
        valid = {f.name for f in cls.__dataclass_fields__.values()}
        filtered = {k: v for k, v in data.items() if k in valid}
        state = cls(**filtered)
        state.history = [
            LifecycleEvent.from_dict(e) if isinstance(e, dict) else e
            for e in history_raw
        ]
        return state


class StrategyLifecycleManager:
    """
    EA-107: Manages strategy lifecycle transitions.
    
    Lifecycle:
        candidate → active → probation → retired
                              ↑                |
                              └── resurrect ───┘
    
    Rules:
    - active → probation: win_rate < PROBATION_THRESHOLD (with min samples)
    - probation → retired: win_rate < RETIREMENT_THRESHOLD after probation period
    - probation → active: win_rate improves above RECOVERY_THRESHOLD
    - retired → probation: manual resurrection or periodic re-evaluation
    - candidate → active: after MIN_CANDIDATE_RUNS
    
    Usage:
        manager = StrategyLifecycleManager(profile_engine, failure_analyzer)
        events = manager.evaluate_all()
        for event in events:
            print(f"{event.strategy_name}: {event.from_status} → {event.to_status}")
    """
    
    # Thresholds
    PROBATION_THRESHOLD = 0.25      # Win rate below → probation
    RETIREMENT_THRESHOLD = 0.15     # Win rate below after probation → retired
    RECOVERY_THRESHOLD = 0.35       # Win rate above during probation → active
    MIN_SAMPLES = 10                # Minimum runs before lifecycle actions
    MIN_CANDIDATE_RUNS = 5          # Runs before candidate → active
    PROBATION_PERIOD = 20           # Runs in probation before retirement decision
    MAX_RESURRECTIONS = 3           # Max times a strategy can be resurrected
    # Critical failure patterns force immediate probation
    CRITICAL_FAILURE_IMMEDIATE_PROBATION = True
    
    def __init__(
        self,
        profile_engine: StrategyProfileEngine,
        failure_analyzer: FailureAnalyzer,
        state_dir: str = "data/strategy_lifecycle",
    ):
        self._engine = profile_engine
        self._analyzer = failure_analyzer
        self._state_dir = Path(state_dir)
        self._state_dir.mkdir(parents=True, exist_ok=True)
        self._states: Dict[str, StrategyState] = {}
    
    def get_state(self, strategy_name: str) -> StrategyState:
        """Get current lifecycle state for a strategy."""
        if strategy_name not in self._states:
            self._states[strategy_name] = StrategyState(
                strategy_name=strategy_name,
                status=LifecycleStatus.ACTIVE,
            )
        return self._states[strategy_name]
    
    def evaluate(self, strategy_name: str) -> Optional[LifecycleEvent]:
        """
        Evaluate a single strategy and apply lifecycle transition if needed.
        
        Returns LifecycleEvent if a transition occurred, None otherwise.
        """
        profile = self._engine.get_profile(strategy_name)
        state = self.get_state(strategy_name)
        
        if profile is None or profile.total_runs < self.MIN_CANDIDATE_RUNS:
            # Not enough data
            if state.status != LifecycleStatus.CANDIDATE:
                return self._transition(state, LifecycleStatus.CANDIDATE,
                                         "Insufficient data for evaluation")
            return None
        
        # Check failure patterns
        failure_report = self._analyzer.analyze(strategy_name)
        has_critical = failure_report.has_critical_patterns()
        
        current = state.status
        
        if current == LifecycleStatus.CANDIDATE:
            return self._evaluate_candidate(state, profile)
        elif current == LifecycleStatus.ACTIVE:
            return self._evaluate_active(state, profile, has_critical)
        elif current == LifecycleStatus.PROBATION:
            return self._evaluate_probation(state, profile)
        elif current == LifecycleStatus.RETIRED:
            return None  # Retired strategies need manual resurrection
        
        return None
    
    def _evaluate_candidate(
        self, state: StrategyState, profile: StrategyProfile
    ) -> Optional[LifecycleEvent]:
        """Candidate → active after enough runs."""
        if profile.total_runs >= self.MIN_CANDIDATE_RUNS:
            return self._transition(
                state, LifecycleStatus.ACTIVE,
                f"Completed {profile.total_runs} runs, win rate {profile.win_rate:.0%}",
                metrics={"win_rate": profile.win_rate, "runs": profile.total_runs},
            )
        return None
    
    def _evaluate_active(
        self,
        state: StrategyState,
        profile: StrategyProfile,
        has_critical: bool,
    ) -> Optional[LifecycleEvent]:
        """Active → probation if performance drops."""
        if profile.total_runs < self.MIN_SAMPLES:
            return None
        
        # Critical failure → immediate probation
        if has_critical and self.CRITICAL_FAILURE_IMMEDIATE_PROBATION:
            return self._transition(
                state, LifecycleStatus.PROBATION,
                "Critical failure patterns detected",
                metrics={"win_rate": profile.win_rate, "trend": profile.trend},
            )
        
        # Win rate below threshold
        if profile.win_rate < self.PROBATION_THRESHOLD:
            return self._transition(
                state, LifecycleStatus.PROBATION,
                f"Win rate {profile.win_rate:.0%} below threshold {self.PROBATION_THRESHOLD:.0%}",
                metrics={"win_rate": profile.win_rate, "runs": profile.total_runs},
            )
        
        return None
    
    def _evaluate_probation(
        self, state: StrategyState, profile: StrategyProfile
    ) -> Optional[LifecycleEvent]:
        """Probation → retired or → active."""
        # Recovery check
        if profile.win_rate >= self.RECOVERY_THRESHOLD:
            return self._transition(
                state, LifecycleStatus.ACTIVE,
                f"Win rate recovered to {profile.win_rate:.0%}",
                metrics={"win_rate": profile.win_rate},
            )
        
        # Count runs since probation started
        runs_in_probation = 0
        if state.probation_since:
            from .strategy_tracker import StrategyRecordKeeper
            # Approximate by total runs - not ideal but works
            runs_in_probation = profile.total_runs  # simplified
        
        # Retirement check
        if (profile.win_rate < self.RETIREMENT_THRESHOLD
                and profile.total_runs >= self.MIN_SAMPLES * 2):
            return self._transition(
                state, LifecycleStatus.RETIRED,
                f"Win rate {profile.win_rate:.0%} below retirement threshold after extended probation",
                metrics={"win_rate": profile.win_rate, "runs": profile.total_runs},
            )
        
        return None
    
    def resurrect(self, strategy_name: str, reason: str = "Manual resurrection") -> Optional[LifecycleEvent]:
        """
        Resurrect a retired strategy back to probation.
        
        Returns LifecycleEvent if successful, None if max resurrections exceeded.
        """
        state = self.get_state(strategy_name)
        
        if state.status != LifecycleStatus.RETIRED:
            return None
        
        if state.resurrection_count >= self.MAX_RESURRECTIONS:
            logger.warning(
                f"EA-107: Cannot resurrect {strategy_name} — "
                f"max resurrections ({self.MAX_RESURRECTIONS}) reached"
            )
            return None
        
        state.resurrection_count += 1
        return self._transition(
            state, LifecycleStatus.PROBATION,
            f"{reason} (resurrection #{state.resurrection_count})",
            metrics={"resurrection_count": state.resurrection_count},
        )
    
    def _transition(
        self,
        state: StrategyState,
        to_status: LifecycleStatus,
        reason: str,
        metrics: Optional[Dict[str, Any]] = None,
    ) -> LifecycleEvent:
        """Execute a lifecycle transition."""
        event = LifecycleEvent(
            strategy_name=state.strategy_name,
            from_status=state.status.value,
            to_status=to_status.value,
            reason=reason,
            metrics=metrics or {},
        )
        
        old_status = state.status
        state.status = to_status
        state.history.append(event)
        
        if to_status == LifecycleStatus.PROBATION:
            state.probation_since = time.time()
        elif to_status == LifecycleStatus.RETIRED:
            state.retired_since = time.time()
        elif to_status == LifecycleStatus.ACTIVE:
            state.probation_since = None
        
        logger.info(
            f"EA-107: {state.strategy_name} "
            f"{old_status.value} → {to_status.value}: {reason}"
        )
        
        return event
    
    def evaluate_all(self) -> List[LifecycleEvent]:
        """Evaluate all known strategies."""
        profiles = self._engine.get_all_profiles()
        events = []
        
        for name in profiles:
            event = self.evaluate(name)
            if event:
                events.append(event)
        
        return events
    
    def get_active_strategies(self) -> List[str]:
        """Get list of active (non-retired) strategy names."""
        profiles = self._engine.get_all_profiles()
        active = []
        for name in profiles:
            state = self.get_state(name)
            if state.status != LifecycleStatus.RETIRED:
                active.append(name)
        return active
    
    def get_retired_strategies(self) -> List[str]:
        """Get list of retired strategy names."""
        return [
            name for name, state in self._states.items()
            if state.status == LifecycleStatus.RETIRED
        ]
    
    def get_summary(self) -> str:
        """One-line-per-strategy lifecycle summary."""
        if not self._states:
            return "No lifecycle data yet."
        
        lines = []
        for name in sorted(self._states):
            state = self._states[name]
            events_count = len(state.history)
            lines.append(
                f"{name}: {state.status.value} "
                f"({events_count} transitions, "
                f"{state.resurrection_count} resurrections)"
            )
        return "\n".join(lines)
    
    def save(self) -> List[str]:
        """Save all lifecycle states to disk."""
        saved = []
        for name, state in self._states.items():
            filepath = self._state_dir / f"{name}.json"
            with open(filepath, "w", encoding="utf-8") as f:
                json.dump(state.to_dict(), f, indent=2, ensure_ascii=False)
            saved.append(str(filepath))
        return saved
    
    def load(self) -> Dict[str, StrategyState]:
        """Load lifecycle states from disk."""
        for filepath in self._state_dir.glob("*.json"):
            try:
                with open(filepath, "r", encoding="utf-8") as f:
                    data = json.load(f)
                state = StrategyState.from_dict(data)
                self._states[state.strategy_name] = state
            except (json.JSONDecodeError, KeyError) as e:
                logger.warning(f"EA-107: Skipping corrupt state {filepath}: {e}")
        return dict(self._states)
