# Copyright (c) 2025 MiroMind
# EA-105: Strategy Parameter Micro-Evolution
#
# Tunes strategy parameters (max_turns, prompt_suffix, temperature hints)
# based on historical performance data from EA-101/EA-102.
#
# Approach: statistical analysis of winning vs losing runs to find
# optimal parameter ranges per strategy per task type.
#
# Dependencies: EA-101 (StrategyRecordKeeper), EA-102 (StrategyProfileEngine)
# Design ref: EVOAGENT_DESIGN.md §5

import json
import logging
import math
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .strategy_tracker import StrategyRecordKeeper, StrategyResult, StrategyProfileEngine

logger = logging.getLogger(__name__)

# Default strategy parameters
DEFAULT_PARAMS = {
    "breadth_first": {"max_turns": 100, "temperature_hint": "balanced"},
    "depth_first": {"max_turns": 300, "temperature_hint": "focused"},
    "lateral_thinking": {"max_turns": 200, "temperature_hint": "creative"},
    "verification_heavy": {"max_turns": 150, "temperature_hint": "precise"},
}


@dataclass
class TuningRecommendation:
    """A parameter tuning recommendation for a strategy."""
    strategy_name: str
    parameter: str
    current_value: Any
    recommended_value: Any
    confidence: float        # 0-1, based on sample size and effect size
    reason: str
    sample_size: int = 0
    task_type: str = "all"   # "all" or specific task type
    
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass 
class TunedParameters:
    """Tuned parameters for a strategy."""
    strategy_name: str
    max_turns: int
    temperature_hint: str    # "focused", "balanced", "creative", "precise"
    adjustments: Dict[str, Any] = field(default_factory=dict)
    task_type_overrides: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    last_tuned_from_samples: int = 0
    
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TunedParameters":
        valid = {f.name for f in cls.__dataclass_fields__.values()}
        return cls(**{k: v for k, v in data.items() if k in valid})
    
    def get_max_turns(self, task_type: Optional[str] = None) -> int:
        """Get max_turns, with optional task-type override."""
        if task_type and task_type in self.task_type_overrides:
            return self.task_type_overrides[task_type].get("max_turns", self.max_turns)
        return self.max_turns


class StrategyTuner:
    """
    EA-105: Tunes strategy parameters based on historical data.
    
    Analyzes winning vs losing runs to recommend parameter adjustments:
    - max_turns: increase if winners use more turns, decrease if wasted
    - temperature_hint: adjust based on task type performance
    
    Usage:
        tuner = StrategyTuner(record_keeper, profile_engine)
        recommendations = tuner.analyze("breadth_first")
        tuned = tuner.get_tuned_params("breadth_first", task_type="search")
    """
    
    MIN_SAMPLES_FOR_TUNING = 5
    # If winners use >20% more/fewer turns than losers, recommend change
    TURNS_SIGNIFICANCE_THRESHOLD = 0.2
    # Max adjustment per tuning cycle (prevent wild swings)
    MAX_TURNS_ADJUSTMENT_RATIO = 0.3
    
    def __init__(
        self,
        record_keeper: StrategyRecordKeeper,
        profile_engine: StrategyProfileEngine,
        params_dir: str = "data/strategy_params",
    ):
        self._keeper = record_keeper
        self._engine = profile_engine
        self._params_dir = Path(params_dir)
        self._params_dir.mkdir(parents=True, exist_ok=True)
        self._tuned: Dict[str, TunedParameters] = {}
    
    def analyze(self, strategy_name: str) -> List[TuningRecommendation]:
        """
        Analyze a strategy's history and produce tuning recommendations.
        
        Returns list of recommendations sorted by confidence.
        """
        records = self._keeper.get_records_for_strategy(strategy_name)
        if len(records) < self.MIN_SAMPLES_FOR_TUNING:
            return []
        
        recommendations = []
        
        # Analyze max_turns
        turns_rec = self._analyze_turns(strategy_name, records)
        if turns_rec:
            recommendations.append(turns_rec)
        
        # Analyze per task type
        by_type = self._group_by_task_type(records)
        for task_type, type_records in by_type.items():
            if len(type_records) >= self.MIN_SAMPLES_FOR_TUNING:
                type_turns_rec = self._analyze_turns(
                    strategy_name, type_records, task_type=task_type
                )
                if type_turns_rec:
                    recommendations.append(type_turns_rec)
        
        # Analyze cost efficiency
        cost_rec = self._analyze_cost_efficiency(strategy_name, records)
        if cost_rec:
            recommendations.append(cost_rec)
        
        recommendations.sort(key=lambda r: r.confidence, reverse=True)
        return recommendations
    
    def _analyze_turns(
        self,
        strategy_name: str,
        records: List[StrategyResult],
        task_type: str = "all",
    ) -> Optional[TuningRecommendation]:
        """Analyze turn usage patterns between winners and losers."""
        winners = [r for r in records if r.is_winner and r.turns_used > 0]
        losers = [r for r in records if not r.is_winner and r.status == "success" and r.turns_used > 0]
        
        if len(winners) < 2 or len(losers) < 2:
            return None
        
        avg_winner_turns = sum(r.turns_used for r in winners) / len(winners)
        avg_loser_turns = sum(r.turns_used for r in losers) / len(losers)
        
        current = DEFAULT_PARAMS.get(strategy_name, {}).get("max_turns", 100)
        if strategy_name in self._tuned:
            current = self._tuned[strategy_name].max_turns
        
        # If winners consistently use more turns → increase budget
        # If winners use fewer turns → decrease (they're efficient)
        if avg_loser_turns > 0:
            ratio = avg_winner_turns / avg_loser_turns
        else:
            return None
        
        diff = abs(ratio - 1.0)
        if diff < self.TURNS_SIGNIFICANCE_THRESHOLD:
            return None  # Not significant
        
        # Calculate recommended value
        if ratio > 1.0:
            # Winners need more turns
            adjustment = min(diff, self.MAX_TURNS_ADJUSTMENT_RATIO)
            recommended = int(current * (1 + adjustment))
            reason = (
                f"Winners avg {avg_winner_turns:.0f} turns vs losers "
                f"{avg_loser_turns:.0f} — increase budget"
            )
        else:
            # Winners are more efficient
            adjustment = min(diff, self.MAX_TURNS_ADJUSTMENT_RATIO)
            recommended = max(10, int(current * (1 - adjustment * 0.5)))
            reason = (
                f"Winners avg {avg_winner_turns:.0f} turns vs losers "
                f"{avg_loser_turns:.0f} — can reduce budget"
            )
        
        # Confidence based on sample size
        n = len(winners) + len(losers)
        confidence = min(0.9, 0.3 + 0.05 * n)
        
        return TuningRecommendation(
            strategy_name=strategy_name,
            parameter="max_turns",
            current_value=current,
            recommended_value=recommended,
            confidence=round(confidence, 3),
            reason=reason,
            sample_size=n,
            task_type=task_type,
        )
    
    def _analyze_cost_efficiency(
        self,
        strategy_name: str,
        records: List[StrategyResult],
    ) -> Optional[TuningRecommendation]:
        """Detect if a strategy is consistently over-budget for its win rate."""
        profile = self._engine.get_profile(strategy_name)
        if not profile or profile.total_runs < self.MIN_SAMPLES_FOR_TUNING:
            return None
        
        # Compare against average cost across all strategies
        all_profiles = self._engine.get_all_profiles()
        if len(all_profiles) < 2:
            return None
        
        avg_cost_all = sum(
            p.avg_cost_usd for p in all_profiles.values() if p.avg_cost_usd > 0
        ) / max(1, sum(1 for p in all_profiles.values() if p.avg_cost_usd > 0))
        
        if avg_cost_all == 0 or profile.avg_cost_usd == 0:
            return None
        
        cost_ratio = profile.avg_cost_usd / avg_cost_all
        
        # If cost > 1.5x average but win rate below average → recommend reduction
        if cost_ratio > 1.5:
            avg_win_all = sum(
                p.win_rate for p in all_profiles.values()
            ) / len(all_profiles)
            
            if profile.win_rate < avg_win_all:
                return TuningRecommendation(
                    strategy_name=strategy_name,
                    parameter="max_turns",
                    current_value=DEFAULT_PARAMS.get(strategy_name, {}).get("max_turns", 100),
                    recommended_value="reduce by 20%",
                    confidence=0.5,
                    reason=(
                        f"Cost {cost_ratio:.1f}x average but win rate "
                        f"{profile.win_rate:.0%} below avg {avg_win_all:.0%}"
                    ),
                    sample_size=profile.total_runs,
                )
        
        return None
    
    def _group_by_task_type(
        self, records: List[StrategyResult]
    ) -> Dict[str, List[StrategyResult]]:
        """Group records by task type, excluding 'unknown'."""
        groups: Dict[str, List[StrategyResult]] = {}
        for r in records:
            if r.task_type and r.task_type != "unknown":
                groups.setdefault(r.task_type, []).append(r)
        return groups
    
    def apply_recommendations(
        self,
        strategy_name: str,
        recommendations: Optional[List[TuningRecommendation]] = None,
        min_confidence: float = 0.5,
    ) -> TunedParameters:
        """
        Apply tuning recommendations to produce TunedParameters.
        
        Only applies recommendations above min_confidence.
        """
        if recommendations is None:
            recommendations = self.analyze(strategy_name)
        
        defaults = DEFAULT_PARAMS.get(strategy_name, {"max_turns": 100, "temperature_hint": "balanced"})
        
        # Start from current tuned or defaults
        if strategy_name in self._tuned:
            params = self._tuned[strategy_name]
        else:
            params = TunedParameters(
                strategy_name=strategy_name,
                max_turns=defaults["max_turns"],
                temperature_hint=defaults.get("temperature_hint", "balanced"),
            )
        
        total_samples = 0
        for rec in recommendations:
            if rec.confidence < min_confidence:
                continue
            
            total_samples = max(total_samples, rec.sample_size)
            
            if rec.parameter == "max_turns" and isinstance(rec.recommended_value, int):
                if rec.task_type == "all":
                    params.max_turns = rec.recommended_value
                else:
                    params.task_type_overrides.setdefault(rec.task_type, {})
                    params.task_type_overrides[rec.task_type]["max_turns"] = rec.recommended_value
                
                params.adjustments[f"max_turns_{rec.task_type}"] = {
                    "from": rec.current_value,
                    "to": rec.recommended_value,
                    "confidence": rec.confidence,
                    "reason": rec.reason,
                }
        
        params.last_tuned_from_samples = total_samples
        self._tuned[strategy_name] = params
        return params
    
    def get_tuned_params(
        self,
        strategy_name: str,
        task_type: Optional[str] = None,
    ) -> TunedParameters:
        """Get tuned parameters, auto-analyzing if not yet tuned."""
        if strategy_name not in self._tuned:
            recs = self.analyze(strategy_name)
            if recs:
                self.apply_recommendations(strategy_name, recs)
            else:
                defaults = DEFAULT_PARAMS.get(
                    strategy_name,
                    {"max_turns": 100, "temperature_hint": "balanced"},
                )
                self._tuned[strategy_name] = TunedParameters(
                    strategy_name=strategy_name,
                    max_turns=defaults["max_turns"],
                    temperature_hint=defaults.get("temperature_hint", "balanced"),
                )
        
        return self._tuned[strategy_name]
    
    def save(self) -> List[str]:
        """Save all tuned parameters to disk."""
        saved = []
        for name, params in self._tuned.items():
            filepath = self._params_dir / f"{name}.json"
            with open(filepath, "w", encoding="utf-8") as f:
                json.dump(params.to_dict(), f, indent=2, ensure_ascii=False)
            saved.append(str(filepath))
        return saved
    
    def load(self) -> Dict[str, TunedParameters]:
        """Load tuned parameters from disk."""
        for filepath in self._params_dir.glob("*.json"):
            try:
                with open(filepath, "r", encoding="utf-8") as f:
                    data = json.load(f)
                params = TunedParameters.from_dict(data)
                self._tuned[params.strategy_name] = params
            except (json.JSONDecodeError, KeyError) as e:
                logger.warning(f"EA-105: Skipping corrupt params {filepath}: {e}")
        return dict(self._tuned)
