# Copyright (c) 2025 MiroMind
# EA-203: Cross-Dimension Adaptive Optimizer
#
# Auto-tunes the optimal combination of:
#   paths × depth × diversity
# based on accumulated task execution data.
#
# Dimensions:
# - Paths: number of parallel exploration paths (1-8)
# - Depth: max_turns per path (50-300)
# - Diversity: how different the strategies should be (0.0-1.0)
#
# Dependencies: EA-101 (records), EA-102 (profiles), EA-304 (cost tracker)
# Design ref: EVOAGENT_DESIGN.md §9

import json
import logging
import math
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from collections import defaultdict

from .strategy_tracker import StrategyRecordKeeper, StrategyResult

logger = logging.getLogger(__name__)


@dataclass
class DimensionConfig:
    """A configuration in the paths × depth × diversity space."""
    num_paths: int = 3
    max_turns: int = 150
    diversity: float = 0.5       # 0=all same strategy, 1=all different
    
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "DimensionConfig":
        valid = {f.name for f in cls.__dataclass_fields__.values()}
        return cls(**{k: v for k, v in data.items() if k in valid})
    
    def to_key(self) -> str:
        """Hashable key for this configuration."""
        return f"p{self.num_paths}_d{self.max_turns}_v{self.diversity:.1f}"


@dataclass
class DimensionResult:
    """Performance result for a specific dimension configuration."""
    config: DimensionConfig
    task_type: str = "all"
    sample_count: int = 0
    win_rate: float = 0.0
    avg_cost_usd: float = 0.0
    avg_duration_seconds: float = 0.0
    efficiency_score: float = 0.0   # win_rate / cost (higher = better)
    
    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["config"] = self.config.to_dict()
        return d


@dataclass
class DimensionRecommendation:
    """Recommended dimension configuration for a task type."""
    task_type: str
    recommended: DimensionConfig
    confidence: float
    reason: str
    alternatives: List[DimensionConfig] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        d = {
            "task_type": self.task_type,
            "recommended": self.recommended.to_dict(),
            "confidence": round(self.confidence, 3),
            "reason": self.reason,
            "alternatives": [a.to_dict() for a in self.alternatives],
        }
        return d


# Default configs to try
DEFAULT_CONFIGS = [
    DimensionConfig(num_paths=2, max_turns=100, diversity=0.5),
    DimensionConfig(num_paths=3, max_turns=150, diversity=0.5),
    DimensionConfig(num_paths=4, max_turns=150, diversity=0.7),
    DimensionConfig(num_paths=3, max_turns=200, diversity=0.3),
    DimensionConfig(num_paths=2, max_turns=300, diversity=0.5),
]


class DimensionOptimizer:
    """
    EA-203: Optimizes paths × depth × diversity configuration.
    
    Tracks which dimension configurations produce the best results
    for each task type, and recommends optimal configurations.
    
    Uses a simplified Bayesian optimization approach:
    1. Track (config, task_type) → performance
    2. Compute efficiency = win_rate / normalized_cost
    3. Recommend the most efficient config per task type
    4. Suggest exploration of untried configs
    
    Usage:
        optimizer = DimensionOptimizer(record_keeper)
        optimizer.record_run(
            config=DimensionConfig(num_paths=3, max_turns=150, diversity=0.5),
            task_type="search",
            won=True,
            cost=0.02,
            duration=30.0,
        )
        rec = optimizer.recommend("search")
        # rec.recommended = DimensionConfig(num_paths=3, ...)
    """
    
    MIN_SAMPLES = 3
    MIN_SAMPLES_FOR_RECOMMENDATION = 5
    
    def __init__(
        self,
        record_keeper: StrategyRecordKeeper,
        data_dir: str = "data/dimension_optimizer",
    ):
        self._keeper = record_keeper
        self._data_dir = Path(data_dir)
        self._data_dir.mkdir(parents=True, exist_ok=True)
        # {config_key: {task_type: [results]}}
        self._results: Dict[str, Dict[str, List[Dict]]] = defaultdict(
            lambda: defaultdict(list)
        )
    
    def record_run(
        self,
        config: DimensionConfig,
        task_type: str,
        won: bool,
        cost: float = 0.0,
        duration: float = 0.0,
    ) -> None:
        """Record a run result for a dimension configuration."""
        key = config.to_key()
        self._results[key][task_type].append({
            "won": won,
            "cost": cost,
            "duration": duration,
            "timestamp": time.time(),
        })
        self._results[key]["all"].append({
            "won": won,
            "cost": cost,
            "duration": duration,
            "timestamp": time.time(),
        })
    
    def get_results(
        self, config: DimensionConfig, task_type: str = "all"
    ) -> Optional[DimensionResult]:
        """Get aggregated results for a config + task type."""
        key = config.to_key()
        runs = self._results.get(key, {}).get(task_type, [])
        
        if not runs:
            return None
        
        wins = sum(1 for r in runs if r["won"])
        costs = [r["cost"] for r in runs if r["cost"] > 0]
        durations = [r["duration"] for r in runs if r["duration"] > 0]
        
        win_rate = wins / len(runs)
        avg_cost = sum(costs) / len(costs) if costs else 0.0
        avg_duration = sum(durations) / len(durations) if durations else 0.0
        
        # Efficiency: win_rate / normalized_cost (avoid div by zero)
        efficiency = win_rate / max(avg_cost, 0.001)
        
        return DimensionResult(
            config=config,
            task_type=task_type,
            sample_count=len(runs),
            win_rate=win_rate,
            avg_cost_usd=avg_cost,
            avg_duration_seconds=avg_duration,
            efficiency_score=efficiency,
        )
    
    def recommend(self, task_type: str = "all") -> DimensionRecommendation:
        """
        Recommend the best dimension configuration for a task type.
        
        Returns the config with highest efficiency score among those
        with sufficient samples.
        """
        candidates = []
        
        for config_key, type_results in self._results.items():
            runs = type_results.get(task_type, [])
            if len(runs) < self.MIN_SAMPLES:
                continue
            
            # Parse config from key
            config = self._parse_config_key(config_key)
            if config is None:
                continue
            
            result = self.get_results(config, task_type)
            if result:
                candidates.append(result)
        
        if not candidates:
            # No data — return default
            return DimensionRecommendation(
                task_type=task_type,
                recommended=DimensionConfig(num_paths=3, max_turns=150, diversity=0.5),
                confidence=0.0,
                reason="No historical data — using default configuration",
            )
        
        # Sort by efficiency score
        candidates.sort(key=lambda r: r.efficiency_score, reverse=True)
        
        best = candidates[0]
        confidence = min(0.9, 0.3 + 0.05 * best.sample_count)
        
        alternatives = [r.config for r in candidates[1:3]]
        
        return DimensionRecommendation(
            task_type=task_type,
            recommended=best.config,
            confidence=round(confidence, 3),
            reason=(
                f"Best efficiency: {best.win_rate:.0%} win rate, "
                f"${best.avg_cost_usd:.4f} avg cost, "
                f"{best.sample_count} samples"
            ),
            alternatives=alternatives,
        )
    
    def recommend_all_task_types(self) -> Dict[str, DimensionRecommendation]:
        """Recommend configs for all observed task types."""
        task_types = set()
        for config_results in self._results.values():
            task_types.update(config_results.keys())
        
        task_types.discard("all")
        
        recs = {"all": self.recommend("all")}
        for tt in sorted(task_types):
            recs[tt] = self.recommend(tt)
        
        return recs
    
    def suggest_exploration(self) -> List[DimensionConfig]:
        """
        Suggest untried or under-sampled configurations for exploration.
        
        Returns configs from DEFAULT_CONFIGS that haven't been tried enough.
        """
        suggestions = []
        
        for config in DEFAULT_CONFIGS:
            key = config.to_key()
            total_runs = sum(
                len(runs) for task_runs in self._results.get(key, {}).values()
                for runs in [task_runs]
            )
            # Only count "all" to avoid double-counting
            all_runs = len(self._results.get(key, {}).get("all", []))
            
            if all_runs < self.MIN_SAMPLES_FOR_RECOMMENDATION:
                suggestions.append(config)
        
        return suggestions
    
    def _parse_config_key(self, key: str) -> Optional[DimensionConfig]:
        """Parse a config key like 'p3_d150_v0.5' back to DimensionConfig."""
        try:
            parts = key.split("_")
            num_paths = int(parts[0][1:])
            max_turns = int(parts[1][1:])
            diversity = float(parts[2][1:])
            return DimensionConfig(
                num_paths=num_paths,
                max_turns=max_turns,
                diversity=diversity,
            )
        except (IndexError, ValueError):
            return None
    
    def get_heatmap_data(self) -> List[Dict[str, Any]]:
        """
        Get data for visualizing the paths × depth performance heatmap.
        
        Returns list of {paths, depth, diversity, win_rate, cost, samples}.
        """
        data = []
        for config_key, type_results in self._results.items():
            config = self._parse_config_key(config_key)
            if config is None:
                continue
            
            result = self.get_results(config, "all")
            if result and result.sample_count > 0:
                data.append({
                    "paths": config.num_paths,
                    "depth": config.max_turns,
                    "diversity": config.diversity,
                    "win_rate": round(result.win_rate, 3),
                    "avg_cost": round(result.avg_cost_usd, 4),
                    "efficiency": round(result.efficiency_score, 2),
                    "samples": result.sample_count,
                })
        
        return data
    
    def save(self) -> str:
        """Save optimizer state to disk."""
        filepath = self._data_dir / "dimension_state.json"
        
        # Convert defaultdict to regular dict for JSON
        state = {}
        for config_key, type_results in self._results.items():
            state[config_key] = {}
            for task_type, runs in type_results.items():
                state[config_key][task_type] = runs
        
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2, ensure_ascii=False)
        
        logger.info(f"EA-203: Saved dimension optimizer state to {filepath}")
        return str(filepath)
    
    def load(self) -> None:
        """Load optimizer state from disk."""
        filepath = self._data_dir / "dimension_state.json"
        if not filepath.exists():
            return
        
        with open(filepath, "r", encoding="utf-8") as f:
            state = json.load(f)
        
        self._results = defaultdict(lambda: defaultdict(list))
        for config_key, type_results in state.items():
            for task_type, runs in type_results.items():
                self._results[config_key][task_type] = runs
    
    def get_summary(self) -> str:
        """Summary of optimizer state."""
        total_configs = len(self._results)
        total_runs = sum(
            len(self._results[k].get("all", []))
            for k in self._results
        )
        
        if total_runs == 0:
            return "No dimension optimization data yet."
        
        lines = [f"Configurations tested: {total_configs}, total runs: {total_runs}"]
        
        rec = self.recommend("all")
        lines.append(
            f"Best overall: {rec.recommended.num_paths} paths × "
            f"{rec.recommended.max_turns} depth × "
            f"{rec.recommended.diversity:.1f} diversity"
        )
        lines.append(f"Confidence: {rec.confidence:.0%}")
        
        suggestions = self.suggest_exploration()
        if suggestions:
            lines.append(f"Untested configs: {len(suggestions)}")
        
        return "\n".join(lines)
