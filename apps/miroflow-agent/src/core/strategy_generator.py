# Copyright (c) 2025 MiroMind
# EA-201: LLM Strategy Generator (Meta-Evolution)
#
# Uses LLM to generate entirely new search strategies based on
# evolution signals: coverage gaps, failure clusters, strategy
# degradation, population sparsity.
#
# Dependencies: EA-102, EA-106, EA-107, EA-108
# Design ref: EVOAGENT_DESIGN.md §8

import json
import logging
import time
import uuid
from dataclasses import dataclass, field, asdict
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .strategy_tracker import StrategyProfileEngine, StrategyProfile
from .failure_analyzer import FailureAnalyzer
from .strategy_lifecycle import StrategyLifecycleManager
from .experience_extractor import ExperienceExtractor, LearningEntry

logger = logging.getLogger(__name__)


class EvolutionSignal(str, Enum):
    """Signals that trigger strategy generation."""
    COVERAGE_GAP = "coverage_gap"       # All strategies < 50% on a task type
    FAILURE_CLUSTER = "failure_cluster"  # Same failure pattern ≥ 3 times
    DEGRADATION = "degradation"         # Recent win rate dropped > 20%
    POPULATION_SPARSE = "population_sparse"  # Active strategies < min threshold
    MUTATION = "mutation"               # Variation of existing high-performer
    CROSSOVER = "crossover"             # Combine traits from two strategies


@dataclass
class EvolvedStrategy:
    """A strategy generated through meta-evolution."""
    name: str
    description: str
    prompt_suffix: str
    max_turns: int = 150
    origin: str = "evolved"
    generation: int = 1
    parent: Optional[str] = None
    parents: List[str] = field(default_factory=list)  # For crossover
    target_task_types: List[str] = field(default_factory=list)
    signal: str = ""                    # Which EvolutionSignal triggered this
    rationale: str = ""
    created_at: float = field(default_factory=time.time)
    strategy_id: str = field(default_factory=lambda: f"evolved_{uuid.uuid4().hex[:8]}")
    
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "EvolvedStrategy":
        valid = {f.name for f in cls.__dataclass_fields__.values()}
        return cls(**{k: v for k, v in data.items() if k in valid})
    
    def to_strategy_variant(self) -> Dict[str, Any]:
        """Convert to the format used by STRATEGY_VARIANTS in multi_path.py."""
        return {
            "name": self.name,
            "description": self.description,
            "prompt_suffix": self.prompt_suffix,
            "max_turns": self.max_turns,
            "origin": self.origin,
            "generation": self.generation,
            "parent": self.parent,
            "target_task_types": self.target_task_types,
        }


@dataclass
class EvolutionSignalDetection:
    """A detected evolution signal."""
    signal_type: EvolutionSignal
    description: str
    context: Dict[str, Any] = field(default_factory=dict)
    priority: str = "medium"  # low, medium, high
    
    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["signal_type"] = self.signal_type.value
        return d


# ─── Builtin Strategy Templates for Mutation/Crossover ──────────────────────

STRATEGY_TEMPLATES = {
    "breadth_first": {
        "traits": ["wide search", "multiple sources", "parallel exploration"],
        "prompt_suffix": "Explore broadly. Check multiple sources before concluding.",
    },
    "depth_first": {
        "traits": ["deep analysis", "follow chains", "thorough investigation"],
        "prompt_suffix": "Go deep. Follow each lead thoroughly before moving on.",
    },
    "lateral_thinking": {
        "traits": ["creative", "unconventional", "analogies", "reframing"],
        "prompt_suffix": "Think laterally. Look for unconventional connections.",
    },
    "verification_heavy": {
        "traits": ["fact-checking", "cross-reference", "skeptical", "precise"],
        "prompt_suffix": "Verify everything. Cross-reference claims from multiple sources.",
    },
}


class StrategyGenerator:
    """
    EA-201: Generates new strategies through meta-evolution.
    
    Detects evolution signals and produces new strategies via:
    - Mutation: Tweak a successful strategy's parameters/prompt
    - Crossover: Combine traits from two strategies
    - Gap-filling: Create strategies targeting uncovered task types
    - Repair: Create strategies to address failure patterns
    
    Note: In production, this would call an LLM to generate prompt_suffix.
    For now, uses template-based generation (deterministic, testable).
    
    Usage:
        generator = StrategyGenerator(profile_engine, failure_analyzer,
                                       lifecycle_manager, experience_extractor)
        signals = generator.detect_signals()
        strategies = generator.generate_from_signals(signals)
        generator.save_strategies(strategies)
    """
    
    MIN_ACTIVE_STRATEGIES = 3
    COVERAGE_GAP_THRESHOLD = 0.5   # All strategies below this = gap
    DEGRADATION_THRESHOLD = 0.2    # Win rate drop > this = degradation
    MAX_EVOLVED_PER_CYCLE = 3      # Max strategies generated per cycle
    
    def __init__(
        self,
        profile_engine: StrategyProfileEngine,
        failure_analyzer: FailureAnalyzer,
        lifecycle_manager: StrategyLifecycleManager,
        experience_extractor: ExperienceExtractor,
        strategies_dir: str = "data/evolved_strategies",
    ):
        self._engine = profile_engine
        self._analyzer = failure_analyzer
        self._lifecycle = lifecycle_manager
        self._extractor = experience_extractor
        self._strategies_dir = Path(strategies_dir)
        self._strategies_dir.mkdir(parents=True, exist_ok=True)
        self._evolved: List[EvolvedStrategy] = []
    
    def detect_signals(self) -> List[EvolutionSignalDetection]:
        """
        Scan current state for evolution signals.
        
        Returns list of detected signals sorted by priority.
        """
        signals = []
        
        signals.extend(self._detect_coverage_gaps())
        signals.extend(self._detect_failure_clusters())
        signals.extend(self._detect_degradation())
        signals.extend(self._detect_population_sparsity())
        
        # Sort by priority
        priority_order = {"high": 0, "medium": 1, "low": 2}
        signals.sort(key=lambda s: priority_order.get(s.priority, 3))
        
        return signals
    
    def _detect_coverage_gaps(self) -> List[EvolutionSignalDetection]:
        """Detect task types where all strategies perform poorly."""
        signals = []
        profiles = self._engine.get_all_profiles()
        
        if not profiles:
            return signals
        
        # Collect all task types
        all_task_types = set()
        for p in profiles.values():
            all_task_types.update(p.task_type_win_rates.keys())
        
        for task_type in all_task_types:
            win_rates = []
            for p in profiles.values():
                if task_type in p.task_type_win_rates:
                    count = p.task_type_counts.get(task_type, 0)
                    if count >= 3:
                        win_rates.append(p.task_type_win_rates[task_type])
            
            if win_rates and all(wr < self.COVERAGE_GAP_THRESHOLD for wr in win_rates):
                signals.append(EvolutionSignalDetection(
                    signal_type=EvolutionSignal.COVERAGE_GAP,
                    description=(
                        f"All strategies below {self.COVERAGE_GAP_THRESHOLD:.0%} "
                        f"on '{task_type}' tasks (best: {max(win_rates):.0%})"
                    ),
                    context={
                        "task_type": task_type,
                        "win_rates": {p.strategy_name: p.task_type_win_rates.get(task_type, 0)
                                      for p in profiles.values()},
                    },
                    priority="high",
                ))
        
        return signals
    
    def _detect_failure_clusters(self) -> List[EvolutionSignalDetection]:
        """Detect repeated failure patterns."""
        signals = []
        learnings = self._extractor.get_high_priority_learnings()
        
        failure_learnings = [
            e for e in learnings
            if e.category == "failure_pattern"
        ]
        
        # Group by pattern type
        pattern_groups: Dict[str, List[LearningEntry]] = {}
        for e in failure_learnings:
            key = e.evidence.get("pattern_type", "unknown")
            pattern_groups.setdefault(key, []).append(e)
        
        for pattern_type, entries in pattern_groups.items():
            if len(entries) >= 2:  # Multiple strategies with same pattern
                signals.append(EvolutionSignalDetection(
                    signal_type=EvolutionSignal.FAILURE_CLUSTER,
                    description=(
                        f"'{pattern_type}' failure pattern across "
                        f"{len(entries)} strategies"
                    ),
                    context={
                        "pattern_type": pattern_type,
                        "affected_strategies": [e.strategy_name for e in entries],
                    },
                    priority="high",
                ))
        
        return signals
    
    def _detect_degradation(self) -> List[EvolutionSignalDetection]:
        """Detect strategies with declining performance."""
        signals = []
        profiles = self._engine.get_all_profiles()
        
        for name, profile in profiles.items():
            if profile.trend == "declining" and profile.total_runs >= 10:
                drop = profile.win_rate - profile.recent_win_rate
                if drop > self.DEGRADATION_THRESHOLD:
                    signals.append(EvolutionSignalDetection(
                        signal_type=EvolutionSignal.DEGRADATION,
                        description=(
                            f"'{name}' declining: {profile.win_rate:.0%} → "
                            f"{profile.recent_win_rate:.0%} ({drop:.0%} drop)"
                        ),
                        context={
                            "strategy_name": name,
                            "overall_win_rate": profile.win_rate,
                            "recent_win_rate": profile.recent_win_rate,
                            "drop": drop,
                        },
                        priority="medium",
                    ))
        
        return signals
    
    def _detect_population_sparsity(self) -> List[EvolutionSignalDetection]:
        """Detect when too few strategies are active."""
        signals = []
        active = self._lifecycle.get_active_strategies()
        
        if len(active) < self.MIN_ACTIVE_STRATEGIES:
            signals.append(EvolutionSignalDetection(
                signal_type=EvolutionSignal.POPULATION_SPARSE,
                description=(
                    f"Only {len(active)} active strategies "
                    f"(minimum: {self.MIN_ACTIVE_STRATEGIES})"
                ),
                context={
                    "active_count": len(active),
                    "active_strategies": active,
                    "retired": self._lifecycle.get_retired_strategies(),
                },
                priority="high",
            ))
        
        return signals
    
    def generate_from_signals(
        self, signals: List[EvolutionSignalDetection]
    ) -> List[EvolvedStrategy]:
        """
        Generate new strategies based on detected signals.
        
        Uses template-based generation (LLM integration is future work).
        """
        generated = []
        
        for signal in signals[:self.MAX_EVOLVED_PER_CYCLE]:
            strategy = self._generate_for_signal(signal)
            if strategy:
                generated.append(strategy)
        
        self._evolved.extend(generated)
        return generated
    
    def _generate_for_signal(
        self, signal: EvolutionSignalDetection
    ) -> Optional[EvolvedStrategy]:
        """Generate a strategy for a specific signal."""
        if signal.signal_type == EvolutionSignal.COVERAGE_GAP:
            return self._generate_gap_filler(signal)
        elif signal.signal_type == EvolutionSignal.FAILURE_CLUSTER:
            return self._generate_failure_repair(signal)
        elif signal.signal_type == EvolutionSignal.DEGRADATION:
            return self._generate_replacement(signal)
        elif signal.signal_type == EvolutionSignal.POPULATION_SPARSE:
            return self._generate_mutation(signal)
        elif signal.signal_type == EvolutionSignal.MUTATION:
            return self._generate_mutation(signal)
        elif signal.signal_type == EvolutionSignal.CROSSOVER:
            return self._generate_crossover(signal)
        return None
    
    def _generate_gap_filler(
        self, signal: EvolutionSignalDetection
    ) -> EvolvedStrategy:
        """Generate a strategy targeting an uncovered task type."""
        task_type = signal.context.get("task_type", "unknown")
        
        # Task-type-specific prompt hints
        type_hints = {
            "search": "Focus on finding precise facts. Use multiple search queries with different phrasings. Cross-reference between sources.",
            "compute": "Break calculations into clear steps. Verify intermediate results. Show your work explicitly.",
            "creative": "Generate multiple diverse ideas before selecting. Use brainstorming techniques. Combine unexpected concepts.",
            "verify": "Be skeptical of every claim. Find primary sources. Look for contradicting evidence actively.",
            "multi-hop": "Map out the reasoning chain first. Identify all required sub-questions. Solve them in dependency order.",
        }
        
        hint = type_hints.get(task_type, "Adapt your approach based on what works.")
        
        return EvolvedStrategy(
            name=f"evolved_{task_type}_specialist",
            description=f"Specialized strategy for {task_type} tasks (gap-filler)",
            prompt_suffix=(
                f"You are optimized for {task_type} tasks. {hint} "
                f"If your initial approach stalls, try a completely different angle."
            ),
            max_turns=150,
            target_task_types=[task_type],
            signal=signal.signal_type.value,
            rationale=signal.description,
            parent=None,
        )
    
    def _generate_failure_repair(
        self, signal: EvolutionSignalDetection
    ) -> EvolvedStrategy:
        """Generate a strategy that avoids known failure patterns."""
        pattern_type = signal.context.get("pattern_type", "unknown")
        affected = signal.context.get("affected_strategies", [])
        
        repair_hints = {
            "repeated_reason": "Before each action, check if this approach has failed before. If so, try the opposite.",
            "task_type_weakness": "Identify the task type early and adapt your strategy accordingly.",
            "temporal_cluster": "If you encounter errors, pause and reassess rather than retrying the same approach.",
            "cost_waste": "Set clear milestones. If no progress after 5 turns, change approach entirely.",
        }
        
        hint = repair_hints.get(pattern_type, "Learn from past failures and avoid repeating them.")
        
        return EvolvedStrategy(
            name=f"evolved_repair_{pattern_type}",
            description=f"Repair strategy addressing '{pattern_type}' failures",
            prompt_suffix=(
                f"IMPORTANT: Previous strategies have failed due to '{pattern_type}'. "
                f"{hint} Be adaptive and self-correcting."
            ),
            max_turns=120,
            signal=signal.signal_type.value,
            rationale=f"Addresses {pattern_type} pattern affecting: {', '.join(affected)}",
            parent=affected[0] if affected else None,
        )
    
    def _generate_replacement(
        self, signal: EvolutionSignalDetection
    ) -> EvolvedStrategy:
        """Generate a replacement for a degrading strategy."""
        parent_name = signal.context.get("strategy_name", "unknown")
        parent_template = STRATEGY_TEMPLATES.get(parent_name, {})
        parent_traits = parent_template.get("traits", [])
        
        return EvolvedStrategy(
            name=f"evolved_{parent_name}_v2",
            description=f"Enhanced version of {parent_name} (addressing degradation)",
            prompt_suffix=(
                f"You are an improved version of the '{parent_name}' strategy. "
                f"Retain core strengths ({', '.join(parent_traits[:2]) if parent_traits else 'thoroughness'}) "
                f"but be more adaptive. If one approach isn't working after 3 attempts, "
                f"switch to a different method entirely."
            ),
            max_turns=int(signal.context.get("max_turns", 150) * 1.1),
            signal=signal.signal_type.value,
            rationale=signal.description,
            parent=parent_name,
            generation=2,
        )
    
    def _generate_mutation(
        self, signal: EvolutionSignalDetection
    ) -> EvolvedStrategy:
        """Generate a mutated variant of a high-performing strategy."""
        profiles = self._engine.get_all_profiles()
        
        # Find best active strategy as mutation base
        best_name = None
        best_rate = 0.0
        for name, profile in profiles.items():
            if profile.status != "retired" and profile.win_rate > best_rate:
                best_rate = profile.win_rate
                best_name = name
        
        if not best_name:
            best_name = "breadth_first"
        
        parent_template = STRATEGY_TEMPLATES.get(best_name, {})
        parent_suffix = parent_template.get("prompt_suffix", "")
        
        return EvolvedStrategy(
            name=f"evolved_{best_name}_mutant",
            description=f"Mutation of {best_name} with increased exploration",
            prompt_suffix=(
                f"Base approach: {parent_suffix} "
                f"MUTATION: Additionally, after every major finding, "
                f"spend one turn exploring an unexpected angle. "
                f"Look for connections others might miss."
            ),
            max_turns=180,
            signal=signal.signal_type.value,
            rationale=f"Mutation of top performer '{best_name}' ({best_rate:.0%} win rate)",
            parent=best_name,
            generation=2,
        )
    
    def _generate_crossover(
        self, signal: EvolutionSignalDetection
    ) -> EvolvedStrategy:
        """Combine traits from two strategies."""
        parents = signal.context.get("parents", [])
        if len(parents) < 2:
            profiles = self._engine.get_all_profiles()
            sorted_profiles = sorted(
                profiles.values(), key=lambda p: p.win_rate, reverse=True
            )
            parents = [p.strategy_name for p in sorted_profiles[:2]]
        
        if len(parents) < 2:
            parents = ["breadth_first", "depth_first"]
        
        t1 = STRATEGY_TEMPLATES.get(parents[0], {})
        t2 = STRATEGY_TEMPLATES.get(parents[1], {})
        traits1 = t1.get("traits", ["thorough"])
        traits2 = t2.get("traits", ["creative"])
        
        return EvolvedStrategy(
            name=f"evolved_crossover_{'_'.join(p[:2] for p in parents)}",
            description=f"Crossover of {parents[0]} × {parents[1]}",
            prompt_suffix=(
                f"Combine two approaches: "
                f"From {parents[0]}: {', '.join(traits1[:2])}. "
                f"From {parents[1]}: {', '.join(traits2[:2])}. "
                f"Start with {parents[0]}'s approach, then apply "
                f"{parents[1]}'s perspective to refine and validate."
            ),
            max_turns=175,
            parents=parents,
            signal=signal.signal_type.value,
            rationale=f"Crossover of {parents[0]} and {parents[1]}",
            generation=2,
        )
    
    def generate_mutation_of(self, strategy_name: str) -> EvolvedStrategy:
        """Manually trigger a mutation of a specific strategy."""
        signal = EvolutionSignalDetection(
            signal_type=EvolutionSignal.MUTATION,
            description=f"Manual mutation of {strategy_name}",
            context={"strategy_name": strategy_name},
        )
        result = self._generate_mutation(signal)
        # Override parent with explicit target
        result.parent = strategy_name
        result.name = f"evolved_{strategy_name}_mutant"
        self._evolved.append(result)
        return result
    
    def generate_crossover_of(
        self, strategy_a: str, strategy_b: str
    ) -> EvolvedStrategy:
        """Manually trigger a crossover between two strategies."""
        signal = EvolutionSignalDetection(
            signal_type=EvolutionSignal.CROSSOVER,
            description=f"Manual crossover of {strategy_a} × {strategy_b}",
            context={"parents": [strategy_a, strategy_b]},
        )
        return self._generate_crossover(signal)
    
    def save_strategies(self, strategies: Optional[List[EvolvedStrategy]] = None) -> List[str]:
        """Save evolved strategies to disk."""
        to_save = strategies or self._evolved
        saved = []
        for s in to_save:
            filepath = self._strategies_dir / f"{s.strategy_id}.json"
            with open(filepath, "w", encoding="utf-8") as f:
                json.dump(s.to_dict(), f, indent=2, ensure_ascii=False)
            saved.append(str(filepath))
        
        logger.info(f"EA-201: Saved {len(saved)} evolved strategies")
        return saved
    
    def load_strategies(self) -> List[EvolvedStrategy]:
        """Load evolved strategies from disk."""
        strategies = []
        for filepath in sorted(self._strategies_dir.glob("*.json")):
            try:
                with open(filepath, "r", encoding="utf-8") as f:
                    data = json.load(f)
                strategies.append(EvolvedStrategy.from_dict(data))
            except (json.JSONDecodeError, KeyError) as e:
                logger.warning(f"EA-201: Skipping corrupt strategy {filepath}: {e}")
        
        self._evolved = strategies
        return strategies
    
    def get_all_evolved(self) -> List[EvolvedStrategy]:
        """Get all evolved strategies (in-memory)."""
        return list(self._evolved)
    
    def get_summary(self) -> str:
        """Summary of evolved strategies."""
        if not self._evolved:
            return "No evolved strategies yet."
        
        lines = [f"Evolved strategies: {len(self._evolved)}"]
        for s in self._evolved:
            lines.append(
                f"  {s.name} (gen {s.generation}, signal={s.signal}, "
                f"parent={s.parent or 'none'})"
            )
        return "\n".join(lines)
