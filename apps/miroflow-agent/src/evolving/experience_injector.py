# Copyright (c) 2025 MiroMind
# Self-Evolving: Experience Injector module
# Classifies the current task, retrieves relevant experiences / strategy
# recommendations / prompt patches, and assembles them into a single text
# block to be appended to the agent's system prompt.

import logging
import re
from typing import TYPE_CHECKING, Any, List, Optional, Tuple

if TYPE_CHECKING:
    from omegaconf import DictConfig

from .experience_store import ExperienceStore
from .strategy_evolver import StrategyEvolver

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Rule-based classification tables
# ---------------------------------------------------------------------------

_QUESTION_TYPE_RULES: list[tuple[list[str], str]] = [
    (["finance", "market", "stock", "price", "earnings", "trading", "bond",
      "yield", "inflation", "gdp", "econom", "invest", "dividend", "forex",
      "commodity", "crypto", "bitcoin"], "finance_market"),
    (["sport", "game", "match", "team", "player", "score", "league",
      "champion", "tournament", "nba", "nfl", "fifa", "olympic"], "sports_event"),
    (["politi", "election", "vote", "govern", "president", "parliament",
      "senat", "congress", "diplomat", "sanction", "treaty", "geopolit",
      "war", "conflict", "military"], "politics"),
    (["technolog", "software", "ai ", "algorithm", "startup", "chip",
      "semiconduc", "compute", "internet", "robot", "quantum"], "technology"),
    (["entertain", "movie", "film", "music", "celebrit", "actor", "actress",
      "award", "oscar", "grammy", "album", "box office", "netflix"], "entertainment"),
    (["science", "physics", "chemistr", "biolog", "medical", "drug", "vaccine",
      "climate", "space", "nasa", "research", "experiment", "gene"], "science"),
]

_KNOWLEDGE_DOMAIN_MAP: dict[str, str] = {
    "finance_market": "finance",
    "sports_event": "sports",
    "politics": "geopolitics",
    "technology": "tech",
    "entertainment": "entertainment",
    "science": "science",
}

_REASONING_TYPE_RULES: list[tuple[list[str], str]] = [
    (["calculat", "comput", "math", "number", "percent", "ratio",
      "formula", "statistic", "probabilit"], "numerical_computation"),
    (["plan", "schedul", "logist", "optimiz", "allocat", "route",
      "strateg", "organiz"], "planning"),
    (["search", "find", "look up", "lookup", "retrieve", "latest",
      "current", "recent", "news", "update"], "info_retrieval"),
    (["compar", "evaluat", "analyz", "reason", "deduc", "infer",
      "multi-step", "chain", "sequenc"], "multi_step"),
]


def _match_rules(text_lower: str, rules: list[tuple[list[str], str]]) -> Optional[str]:
    best: Optional[str] = None
    best_count = 0
    for keywords, label in rules:
        count = sum(1 for kw in keywords if kw in text_lower)
        if count > best_count:
            best_count = count
            best = label
    return best if best_count > 0 else None


class ExperienceInjector:
    """Retrieves and assembles experience context for injection into the agent's
    system prompt before each task.

    Replaces the simple ExperienceStore.query() call that was previously in
    orchestrator.py.
    """

    def __init__(
        self,
        experience_store: ExperienceStore,
        strategy_evolver: Optional[StrategyEvolver] = None,
        cfg: Optional["DictConfig"] = None,
    ):
        self._store = experience_store
        self._evolver = strategy_evolver
        self._cfg = cfg or {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def classify_task(
        self,
        task_description: str,
        llm_client: Any = None,
    ) -> dict:
        """Classify a task description into structured labels.

        Uses keyword rules by default (``classify_method="rule"``).
        When ``classify_method="llm"`` and *llm_client* is provided, falls
        back to an LLM call (not yet implemented -- returns rule-based result).
        """
        method = self._cfg.get("classify_method", "rule") if self._cfg else "rule"

        if method == "llm" and llm_client is not None:
            return self._classify_via_llm(task_description, llm_client)

        return self._classify_via_rules(task_description)

    def inject(
        self,
        task_description: str,
        llm_client: Any = None,
        max_tokens: int = 2000,
    ) -> str:
        """Core method: classify task, retrieve all relevant context, assemble
        and truncate to *max_tokens*, return text ready for system-prompt
        concatenation.

        Returns ``""`` when no content is available.
        """
        labels = self.classify_task(task_description, llm_client)
        question_type = labels.get("question_type", "")

        failures, successes = self._retrieve_experiences(labels)

        failure_text = self._format_experiences(failures, successes)
        strategy_text = self._retrieve_strategy_recommendations(question_type)
        prompt_patch = self._retrieve_prompt_patches(question_type)

        success_text = ""
        if successes and self._cfg.get("inject_successes", True):
            success_text = self._format_success_only(successes)

        return self._assemble_and_truncate(
            prompt_patch=prompt_patch,
            failure_text=failure_text,
            strategy_text=strategy_text,
            success_text=success_text,
            max_tokens=max_tokens,
        )

    # ------------------------------------------------------------------
    # Private: classification
    # ------------------------------------------------------------------

    @staticmethod
    def _classify_via_rules(task_description: str) -> dict:
        text_lower = task_description.lower()

        question_type = _match_rules(text_lower, _QUESTION_TYPE_RULES) or "other"
        knowledge_domain = _KNOWLEDGE_DOMAIN_MAP.get(question_type, "other")
        reasoning_type = _match_rules(text_lower, _REASONING_TYPE_RULES) or "logical_reasoning"

        return {
            "question_type": question_type,
            "reasoning_type": reasoning_type,
            "knowledge_domain": knowledge_domain,
            "level": None,
        }

    @staticmethod
    def _classify_via_llm(task_description: str, llm_client: Any) -> dict:
        """Placeholder for LLM-based classification (future implementation)."""
        logger.debug("LLM classification not yet implemented, falling back to rules")
        return ExperienceInjector._classify_via_rules(task_description)

    # ------------------------------------------------------------------
    # Private: retrieval
    # ------------------------------------------------------------------

    def _retrieve_experiences(
        self,
        task_labels: dict,
        max_failures: int = 3,
        max_successes: int = 2,
    ) -> Tuple[List[dict], List[dict]]:
        """Retrieve failure and success experiences with graceful degradation.

        Tries exact match on ``question_type + reasoning_type`` first; if
        insufficient, relaxes to ``question_type`` only.
        """
        qt = task_labels.get("question_type")
        rt = task_labels.get("reasoning_type")

        failures: List[dict] = []
        successes: List[dict] = []

        if self._cfg.get("inject_failures", True):
            failures = self._store.query(
                question_type=qt, reasoning_type=rt,
                was_correct=False, max_count=max_failures,
            )
            if len(failures) < max_failures and qt:
                extras = self._store.query(
                    question_type=qt, was_correct=False, max_count=max_failures,
                )
                seen = {f.get("task_id") for f in failures}
                for e in extras:
                    if e.get("task_id") not in seen:
                        failures.append(e)
                        if len(failures) >= max_failures:
                            break

        if self._cfg.get("inject_successes", True):
            successes = self._store.query(
                question_type=qt, reasoning_type=rt,
                was_correct=True, max_count=max_successes,
            )
            if len(successes) < max_successes and qt:
                extras = self._store.query(
                    question_type=qt, was_correct=True, max_count=max_successes,
                )
                seen = {s.get("task_id") for s in successes}
                for e in extras:
                    if e.get("task_id") not in seen:
                        successes.append(e)
                        if len(successes) >= max_successes:
                            break

        return failures, successes

    def _retrieve_strategy_recommendations(self, question_type: str) -> Optional[str]:
        """Format strategy recommendations for *question_type* into text."""
        if not self._cfg.get("inject_strategy_recommendations", True):
            return None
        if not self._evolver or not question_type:
            return None

        prefs = self._evolver.load_strategy_preferences()
        stats = prefs.get("stats", {}).get(question_type)
        if not stats:
            return None

        recs = prefs.get("recommendations", {}).get(question_type, [])
        if isinstance(recs, str):
            return None

        lines = [
            f"## Strategy Recommendations",
            f'Based on past performance on similar "{question_type}" questions:',
        ]

        recommended = []
        avoid = []
        for sn, s in stats.items():
            acc_pct = f"{s['accuracy']:.0%}"
            if sn in recs:
                recommended.append(f"{sn} ({acc_pct} acc)")
            elif s.get("total", 0) >= 3 and s["accuracy"] < 0.4:
                avoid.append(f"{sn} ({acc_pct} acc on this type)")

        if recommended:
            lines.append(f"- Recommended: {', '.join(recommended)}")
        if avoid:
            lines.append(f"- Avoid: {', '.join(avoid)}")

        if not recommended and not avoid:
            return None

        return "\n".join(lines)

    def _retrieve_prompt_patches(self, question_type: str) -> Optional[str]:
        """Retrieve active prompt patches for *question_type*."""
        if not self._cfg.get("inject_prompt_patches", True):
            return None
        if not self._evolver or not question_type:
            return None

        patches = self._evolver.load_active_prompt_overrides(question_type)
        if not patches:
            return None

        lines = [f"## Special Instructions for {question_type} Questions"]
        for p in patches:
            content = p.get("content", "").strip()
            if content:
                lines.append(content)

        return "\n".join(lines) if len(lines) > 1 else None

    # ------------------------------------------------------------------
    # Private: formatting helpers
    # ------------------------------------------------------------------

    def _format_experiences(
        self,
        failures: List[dict],
        successes: List[dict],
    ) -> str:
        """Format failure (and optionally success) experiences into text."""
        items = failures if self._cfg.get("inject_failures", True) else []
        if not items:
            return ""

        lines = ["## Lessons from Past Predictions"]
        for exp in items:
            q_summary = exp.get("question_summary", "")
            lesson = exp.get("lesson", "")
            failure = exp.get("failure_pattern", "")
            lines.append(f"- [FAIL] {q_summary} (error: {failure}): {lesson}")

        return "\n".join(lines)

    @staticmethod
    def _format_success_only(successes: List[dict]) -> str:
        if not successes:
            return ""
        lines: list[str] = []
        for exp in successes:
            q_summary = exp.get("question_summary", "")
            lesson = exp.get("lesson", "")
            lines.append(f"- [OK] {q_summary}: {lesson}")
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Private: assembly with priority-based truncation
    # ------------------------------------------------------------------

    @staticmethod
    def _assemble_and_truncate(
        prompt_patch: Optional[str],
        failure_text: str,
        strategy_text: Optional[str],
        success_text: str,
        max_tokens: int,
    ) -> str:
        """Assemble sections in priority order, truncating lower-priority
        sections when the total exceeds *max_tokens* (estimated at 4 chars/token).
        """
        max_chars = max_tokens * 4
        header = "# ===== Self-Evolving Context ====="
        sections: list[str] = []

        for section in [prompt_patch, failure_text, strategy_text, success_text]:
            if not section:
                continue
            candidate_len = len(header) + sum(len(s) for s in sections) + len(section) + len(sections) * 2 + 4
            if candidate_len > max_chars:
                remaining = max_chars - len(header) - sum(len(s) for s in sections) - len(sections) * 2 - 4
                if remaining > 50:
                    sections.append(section[:remaining] + "...")
                break
            sections.append(section)

        if not sections:
            return ""

        return header + "\n\n" + "\n\n".join(sections)
