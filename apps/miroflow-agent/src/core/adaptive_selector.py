# Copyright (c) 2025 MiroMind
# EA-104: Adaptive Strategy Selection
#
# Dynamically selects strategy combinations using Exploit + Explore balance.
# Analogous to Multi-Armed Bandit: exploit proven winners while exploring
# undersampled or new strategies.
#
# Dependencies: EA-102 (StrategyProfileEngine), EA-103 (TaskClassifier)
# Design ref: EVOAGENT_DESIGN.md §6

import logging
import math
import random
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from .strategy_tracker import StrategyProfileEngine, StrategyProfile
from .task_classifier import TaskClassifier, TaskType

logger = logging.getLogger(__name__)

# Default strategies (cold start / fallback)
DEFAULT_STRATEGIES = ["breadth_first", "depth_first", "lateral_thinking", "verification_heavy"]


@dataclass
class StrategySelection:
    """Result of adaptive strategy selection."""
    strategies: List[str]
    roles: List[str]           # "exploit" or "explore" per strategy
    scores: Dict[str, float]   # UCB scores used for selection
    task_type: str
    task_type_confidence: float
    method: str = "adaptive"   # "adaptive", "cold_start", "fallback"
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "strategies": self.strategies,
            "roles": self.roles,
            "scores": {k: round(v, 4) for k, v in self.scores.items()},
            "task_type": self.task_type,
            "task_type_confidence": round(self.task_type_confidence, 3),
            "method": self.method,
        }


class AdaptiveSelector:
    """
    EA-104: Exploit + Explore strategy selection.
    
    Uses Upper Confidence Bound (UCB1) algorithm variant:
      score = win_rate + C * sqrt(ln(N) / n_i)
    where:
      - win_rate: historical win rate (optionally task-type-specific)
      - C: exploration coefficient (higher = more exploration)
      - N: total runs across all strategies
      - n_i: runs for strategy i
    
    Usage:
        selector = AdaptiveSelector(profile_engine, classifier)
        selection = selector.select(
            task="What is the GDP of China?",
            num_paths=3,
        )
        # selection.strategies = ["depth_first", "breadth_first", "lateral_thinking"]
        # selection.roles = ["exploit", "exploit", "explore"]
    """
    
    # UCB exploration coefficient (sqrt(2) is theoretically optimal)
    EXPLORATION_C = 1.414
    # Minimum samples before a strategy is considered "known"
    MIN_SAMPLES = 3
    # Bonus score for strategies with very few samples (encourages exploration)
    COLD_STRATEGY_BONUS = 0.5
    # When task type confidence is below this, fall back to overall win rate
    TASK_TYPE_CONFIDENCE_THRESHOLD = 0.4
    
    def __init__(
        self,
        profile_engine: StrategyProfileEngine,
        classifier: TaskClassifier,
        exploration_c: Optional[float] = None,
        available_strategies: Optional[List[str]] = None,
    ):
        self._engine = profile_engine
        self._classifier = classifier
        self._exploration_c = exploration_c or self.EXPLORATION_C
        self._available = available_strategies or DEFAULT_STRATEGIES
    
    def select(
        self,
        task: str,
        num_paths: int,
        force_explore: Optional[List[str]] = None,
        exclude: Optional[List[str]] = None,
    ) -> StrategySelection:
        """
        Select strategies for a multi-path run.
        
        Args:
            task: The task description.
            num_paths: Number of paths (strategies) to select.
            force_explore: Strategies to force into explore slots.
            exclude: Strategies to exclude.
        
        Returns:
            StrategySelection with ordered strategies and roles.
        """
        num_paths = max(1, min(num_paths, len(self._available)))
        exclude = set(exclude or [])
        force_explore = list(force_explore or [])
        
        # Step 1: Classify task (EA-103)
        classification = self._classifier.classify(task)
        task_type = classification.task_type.value
        task_confidence = classification.confidence
        
        # Step 2: Get profiles (EA-102)
        profiles = self._engine.get_all_profiles()
        
        # Cold start: no profiles at all
        if not profiles:
            return self._cold_start_selection(
                num_paths, task_type, task_confidence, exclude
            )
        
        # Step 3: Compute UCB scores
        ucb_scores = self._compute_ucb_scores(
            profiles, task_type, task_confidence
        )
        
        # Step 4: Filter and select
        candidates = [
            s for s in self._available
            if s not in exclude
        ]
        
        if not candidates:
            return self._cold_start_selection(
                num_paths, task_type, task_confidence, exclude
            )
        
        # Step 5: Assign exploit/explore roles
        strategies, roles = self._assign_roles(
            candidates, ucb_scores, num_paths, profiles, force_explore
        )
        
        return StrategySelection(
            strategies=strategies,
            roles=roles,
            scores=ucb_scores,
            task_type=task_type,
            task_type_confidence=task_confidence,
            method="adaptive",
        )
    
    def _compute_ucb_scores(
        self,
        profiles: Dict[str, StrategyProfile],
        task_type: str,
        task_confidence: float,
    ) -> Dict[str, float]:
        """Compute UCB1 scores for all available strategies."""
        total_runs = sum(p.total_runs for p in profiles.values())
        if total_runs == 0:
            return {s: self.COLD_STRATEGY_BONUS for s in self._available}
        
        ln_total = math.log(total_runs) if total_runs > 0 else 0
        scores = {}
        
        for strategy in self._available:
            profile = profiles.get(strategy)
            
            if profile is None or profile.total_runs == 0:
                # Never seen: high exploration bonus
                scores[strategy] = self.COLD_STRATEGY_BONUS + self._exploration_c
                continue
            
            if profile.status == "retired":
                # Retired strategies get a penalty but aren't excluded
                scores[strategy] = max(0.0, profile.win_rate - 0.2)
                continue
            
            # Win rate: use task-type-specific if confident enough
            if (task_type != "unknown"
                    and task_confidence >= self.TASK_TYPE_CONFIDENCE_THRESHOLD
                    and task_type in profile.task_type_win_rates
                    and profile.task_type_counts.get(task_type, 0) >= self.MIN_SAMPLES):
                win_rate = profile.task_type_win_rates[task_type]
            else:
                win_rate = profile.win_rate
            
            # UCB1: exploitation + exploration
            n_i = profile.total_runs
            exploration_term = self._exploration_c * math.sqrt(ln_total / n_i)
            
            scores[strategy] = win_rate + exploration_term
        
        return scores
    
    def _assign_roles(
        self,
        candidates: List[str],
        ucb_scores: Dict[str, float],
        num_paths: int,
        profiles: Dict[str, StrategyProfile],
        force_explore: List[str],
    ) -> Tuple[List[str], List[str]]:
        """Assign exploit/explore roles based on UCB scores and design table."""
        # Determine exploit/explore slot counts (from design doc §6.2)
        exploit_count, explore_count = self._get_slot_counts(num_paths)
        
        # Sort candidates by UCB score
        ranked = sorted(
            candidates,
            key=lambda s: ucb_scores.get(s, 0),
            reverse=True,
        )
        
        strategies = []
        roles = []
        used = set()
        
        # Fill exploit slots (top-scored strategies)
        for s in ranked:
            if len(strategies) >= exploit_count:
                break
            if s not in used and s not in force_explore:
                strategies.append(s)
                roles.append("exploit")
                used.add(s)
        
        # Fill explore slots
        # Priority: force_explore > low-sample > remaining by UCB
        explore_candidates = []
        
        # Force-explore first
        for s in force_explore:
            if s not in used and s in candidates:
                explore_candidates.append(s)
        
        # Low-sample strategies
        for s in ranked:
            if s not in used and s not in explore_candidates:
                profile = profiles.get(s)
                if profile is None or profile.total_runs < self.MIN_SAMPLES:
                    explore_candidates.append(s)
        
        # Remaining by reverse UCB (explore the less-tried)
        for s in reversed(ranked):
            if s not in used and s not in explore_candidates:
                explore_candidates.append(s)
        
        for s in explore_candidates:
            if len(strategies) >= num_paths:
                break
            if s not in used:
                strategies.append(s)
                roles.append("explore")
                used.add(s)
        
        # If we still don't have enough (shouldn't happen with enough candidates)
        for s in ranked:
            if len(strategies) >= num_paths:
                break
            if s not in used:
                strategies.append(s)
                roles.append("explore")
                used.add(s)
        
        return strategies, roles
    
    @staticmethod
    def _get_slot_counts(num_paths: int) -> Tuple[int, int]:
        """
        Get exploit/explore slot counts from design doc §6.2.
        
        | paths | exploit | explore |
        |-------|---------|---------|
        |   1   |    1    |    0    |
        |   2   |    1    |    1    |
        |   3   |    2    |    1    |
        |   4   |    2    |    2    |
        |   5   |    3    |    2    |
        """
        if num_paths <= 1:
            return 1, 0
        exploit = (num_paths + 1) // 2
        explore = num_paths - exploit
        return exploit, explore
    
    def _cold_start_selection(
        self,
        num_paths: int,
        task_type: str,
        task_confidence: float,
        exclude: set,
    ) -> StrategySelection:
        """Fallback when no historical data exists."""
        available = [s for s in self._available if s not in exclude]
        selected = available[:num_paths]
        
        return StrategySelection(
            strategies=selected,
            roles=["explore"] * len(selected),
            scores={s: 0.0 for s in selected},
            task_type=task_type,
            task_type_confidence=task_confidence,
            method="cold_start",
        )
    
    def get_exploration_rate(self) -> float:
        """Get current explore ratio across recent selections (for monitoring)."""
        profiles = self._engine.get_all_profiles()
        if not profiles:
            return 1.0  # Full exploration in cold start
        
        total = sum(p.total_runs for p in profiles.values())
        if total == 0:
            return 1.0
        
        # As total runs increase, exploration should naturally decrease
        # via UCB's sqrt(ln(N)/n_i) term
        min_runs = min(p.total_runs for p in profiles.values())
        if min_runs >= self.MIN_SAMPLES * 3:
            return 0.2  # Mostly exploiting
        elif min_runs >= self.MIN_SAMPLES:
            return 0.35
        else:
            return 0.5
