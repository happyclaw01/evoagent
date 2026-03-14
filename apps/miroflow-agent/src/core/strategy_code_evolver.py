# Copyright (c) 2025 MiroMind
# EA-202: Strategy Code Evolution
#
# Evolves strategy representations from pure prompts to executable code.
# Strategies can define custom tool selection logic, search patterns,
# and verification workflows as Python functions.
#
# This enables strategies to go beyond prompt engineering into
# algorithmic behavior.
#
# Dependencies: EA-201 (strategy generator)
# Design ref: EVOAGENT_DESIGN.md §9

import inspect
import json
import logging
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class StrategyCode:
    """A code-level strategy definition."""
    name: str
    description: str
    prompt_suffix: str                # Still used as base prompt
    max_turns: int = 150
    origin: str = "code_evolved"
    generation: int = 1
    parent: Optional[str] = None
    
    # Code-level behaviors
    tool_priority: List[str] = field(default_factory=list)
    pre_actions: List[str] = field(default_factory=list)     # Actions before main loop
    post_actions: List[str] = field(default_factory=list)     # Actions after main loop
    turn_hooks: Dict[str, str] = field(default_factory=dict)  # {turn_number: action}
    
    # Adaptive parameters
    early_stop_confidence: float = 0.8     # Override early stop threshold
    max_retries_per_tool: int = 2
    search_breadth: int = 3                # Number of parallel searches
    verification_rounds: int = 1           # How many verification passes
    backtrack_on_failure: bool = True      # Reset and try different approach
    
    # Metadata
    created_at: float = field(default_factory=time.time)
    
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "StrategyCode":
        valid = {f.name for f in cls.__dataclass_fields__.values()}
        return cls(**{k: v for k, v in data.items() if k in valid})
    
    def get_enhanced_prompt_suffix(self) -> str:
        """Generate prompt suffix that encodes code-level behaviors."""
        parts = [self.prompt_suffix]
        
        if self.tool_priority:
            parts.append(
                f"Preferred tools (in order): {', '.join(self.tool_priority)}."
            )
        
        if self.pre_actions:
            parts.append(
                f"Before starting: {'; '.join(self.pre_actions)}."
            )
        
        if self.search_breadth > 1:
            parts.append(
                f"For each search query, try {self.search_breadth} different phrasings."
            )
        
        if self.verification_rounds > 1:
            parts.append(
                f"Verify your findings {self.verification_rounds} times using different sources."
            )
        
        if self.backtrack_on_failure:
            parts.append(
                "If stuck for more than 3 turns, completely restart with a different approach."
            )
        
        if self.post_actions:
            parts.append(
                f"Before finishing: {'; '.join(self.post_actions)}."
            )
        
        return " ".join(parts)


# ─── Predefined Code Patterns ──────────────────────────────────────────────

CODE_PATTERNS = {
    "exhaustive_search": StrategyCode(
        name="exhaustive_search",
        description="Exhaustive search with multiple query reformulations",
        prompt_suffix="Search thoroughly. Don't settle for the first result.",
        tool_priority=["search", "scrape_webpage"],
        pre_actions=["List 3 different search queries before starting"],
        post_actions=["Cross-reference top findings"],
        search_breadth=5,
        verification_rounds=2,
        max_turns=200,
    ),
    "hypothesis_driven": StrategyCode(
        name="hypothesis_driven",
        description="Form hypothesis first, then search for evidence",
        prompt_suffix=(
            "Start by forming a hypothesis about the answer. "
            "Then systematically search for evidence that supports or refutes it. "
            "If refuted, form a new hypothesis."
        ),
        pre_actions=["State your initial hypothesis clearly"],
        post_actions=["Summarize evidence for and against your final answer"],
        search_breadth=2,
        verification_rounds=2,
        backtrack_on_failure=True,
        max_turns=180,
    ),
    "divide_and_conquer": StrategyCode(
        name="divide_and_conquer",
        description="Break complex tasks into sub-problems",
        prompt_suffix=(
            "Break this task into smaller sub-problems. "
            "Solve each sub-problem independently, then combine results. "
            "If a sub-problem is too hard, break it down further."
        ),
        pre_actions=["Decompose the task into 2-4 sub-problems"],
        post_actions=["Verify that sub-problem solutions combine correctly"],
        max_turns=250,
        verification_rounds=1,
    ),
    "adversarial_search": StrategyCode(
        name="adversarial_search",
        description="Actively seek contradicting evidence",
        prompt_suffix=(
            "For every claim you find, actively search for contradicting evidence. "
            "Your answer should survive adversarial scrutiny."
        ),
        tool_priority=["search", "scrape_webpage"],
        verification_rounds=3,
        backtrack_on_failure=True,
        max_turns=200,
    ),
    "cost_efficient": StrategyCode(
        name="cost_efficient",
        description="Minimize turns and API calls while maintaining quality",
        prompt_suffix=(
            "Be efficient. Plan your search strategy before executing. "
            "Aim to answer in as few turns as possible without sacrificing accuracy."
        ),
        pre_actions=["Plan your approach in 1 turn before acting"],
        search_breadth=1,
        verification_rounds=1,
        max_turns=80,
        max_retries_per_tool=1,
    ),
}


class StrategyCodeEvolver:
    """
    EA-202: Evolves strategies at the code level.
    
    Provides a library of code-level strategy patterns that go beyond
    prompt engineering. Strategies can specify:
    - Tool selection priority
    - Pre/post action hooks
    - Search breadth and verification depth
    - Backtracking behavior
    
    Usage:
        evolver = StrategyCodeEvolver()
        strategy = evolver.get_pattern("hypothesis_driven")
        prompt = strategy.get_enhanced_prompt_suffix()
        
        # Create variation
        variant = evolver.create_variant("hypothesis_driven",
            search_breadth=4, verification_rounds=3)
    """
    
    def __init__(self, patterns_dir: str = "data/code_patterns"):
        self._patterns_dir = Path(patterns_dir)
        self._patterns_dir.mkdir(parents=True, exist_ok=True)
        self._patterns: Dict[str, StrategyCode] = dict(CODE_PATTERNS)
        self._custom: Dict[str, StrategyCode] = {}
    
    def get_pattern(self, name: str) -> Optional[StrategyCode]:
        """Get a code pattern by name."""
        return self._custom.get(name) or self._patterns.get(name)
    
    def list_patterns(self) -> List[str]:
        """List all available pattern names."""
        return list(set(list(self._patterns.keys()) + list(self._custom.keys())))
    
    def create_variant(
        self,
        base_name: str,
        variant_name: Optional[str] = None,
        **overrides,
    ) -> StrategyCode:
        """
        Create a variant of an existing pattern with parameter overrides.
        
        Args:
            base_name: Pattern to base on.
            variant_name: Name for the variant.
            **overrides: Parameters to override (e.g., search_breadth=5).
        
        Returns:
            New StrategyCode instance.
        """
        base = self.get_pattern(base_name)
        if base is None:
            raise ValueError(f"Unknown pattern: {base_name}")
        
        # Copy base as dict, apply overrides
        d = base.to_dict()
        d.update(overrides)
        d["name"] = variant_name or f"{base_name}_variant"
        d["parent"] = base_name
        d["origin"] = "code_evolved"
        d["generation"] = base.generation + 1
        d["created_at"] = time.time()
        
        variant = StrategyCode.from_dict(d)
        self._custom[variant.name] = variant
        return variant
    
    def evolve_from_profile(
        self,
        strategy_name: str,
        win_rate: float,
        avg_turns: float,
        strengths: List[str],
        weaknesses: List[str],
    ) -> StrategyCode:
        """
        Create an evolved code strategy based on performance profile.
        
        Adjusts parameters based on observed performance.
        """
        base = self.get_pattern(strategy_name)
        
        overrides = {}
        
        # If high win rate but expensive → reduce turns
        if win_rate > 0.7 and avg_turns > 150:
            overrides["max_turns"] = int(avg_turns * 0.8)
            overrides["search_breadth"] = max(1, (base.search_breadth if base else 3) - 1)
        
        # If low win rate → increase verification
        if win_rate < 0.3:
            overrides["verification_rounds"] = (base.verification_rounds if base else 1) + 1
            overrides["backtrack_on_failure"] = True
            overrides["max_turns"] = int(avg_turns * 1.2) if avg_turns > 0 else 200
        
        # If weak on verification → add pre-action
        if "verify" in weaknesses:
            overrides["pre_actions"] = ["State confidence level before answering"]
            overrides["post_actions"] = ["Double-check all factual claims"]
        
        variant_name = f"evolved_{strategy_name}_code"
        
        if base:
            return self.create_variant(strategy_name, variant_name, **overrides)
        else:
            # No base pattern — create from scratch
            code = StrategyCode(
                name=variant_name,
                description=f"Code-evolved strategy based on {strategy_name}",
                prompt_suffix=f"Evolved from {strategy_name}. Focus on areas of strength.",
                parent=strategy_name,
                origin="code_evolved",
                **overrides,
            )
            self._custom[code.name] = code
            return code
    
    def save(self) -> List[str]:
        """Save custom patterns to disk."""
        saved = []
        for name, pattern in self._custom.items():
            filepath = self._patterns_dir / f"{name}.json"
            with open(filepath, "w", encoding="utf-8") as f:
                json.dump(pattern.to_dict(), f, indent=2, ensure_ascii=False)
            saved.append(str(filepath))
        return saved
    
    def load(self) -> Dict[str, StrategyCode]:
        """Load custom patterns from disk."""
        for filepath in self._patterns_dir.glob("*.json"):
            try:
                with open(filepath, "r", encoding="utf-8") as f:
                    data = json.load(f)
                pattern = StrategyCode.from_dict(data)
                self._custom[pattern.name] = pattern
            except (json.JSONDecodeError, KeyError) as e:
                logger.warning(f"EA-202: Skipping corrupt pattern {filepath}: {e}")
        return dict(self._custom)
    
    def get_summary(self) -> str:
        """Summary of available patterns."""
        builtin = list(self._patterns.keys())
        custom = list(self._custom.keys())
        lines = [
            f"Code patterns: {len(builtin)} builtin, {len(custom)} custom",
            f"Builtin: {', '.join(builtin)}",
        ]
        if custom:
            lines.append(f"Custom: {', '.join(custom)}")
        return "\n".join(lines)
