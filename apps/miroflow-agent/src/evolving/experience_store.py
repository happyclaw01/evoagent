# Copyright (c) 2025 MiroMind
# Self-Evolving: Experience Store module
# Unified storage, deduplication, multi-dimensional retrieval, and prompt formatting
# for experience data. All other evolving sub-modules (B/C/D) access experiences
# exclusively through this interface.

import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class Experience:
    """Canonical experience schema shared across all evolving sub-modules."""

    # --- core fields (existing) ---
    task_id: str = ""
    question_type: str = ""
    level: int = 2
    question_summary: str = ""
    was_correct: bool = False
    lesson: str = ""
    failure_pattern: Optional[str] = None
    search_strategy: str = ""

    # --- structured tags (new) ---
    reasoning_type: str = ""
    knowledge_domain: str = ""
    tools_used: List[str] = field(default_factory=list)
    strategy_name: str = ""

    # --- metadata (new) ---
    created_at: str = ""
    source_run_id: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "Experience":
        known_fields = {f.name for f in cls.__dataclass_fields__.values()}
        filtered = {k: v for k, v in data.items() if k in known_fields}
        return cls(**filtered)


class ExperienceStore:
    """Unified read/write/query interface over an experiences.jsonl file.

    Sub-module contract:
        B (Reflector)        -> add(), add_batch()
        C (StrategyEvolver)  -> get_all(), query()
        D (ExperienceInjector) -> query(), format_for_prompt()
    """

    def __init__(self, file_path: str, viking_storage=None, viking_context=None):
        self._file_path = Path(file_path) if file_path else Path("data/experiences.jsonl")
        self._store: Dict[str, dict] = {}
        self._viking = viking_storage
        self._viking_context = viking_context
        self._load()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def add(self, experience: dict) -> None:
        """Write a single experience.  Deduplicates by task_id (keeps latest)."""
        experience = self._ensure_created_at(experience)
        task_id = experience.get("task_id", "")
        is_update = task_id in self._store

        self._store[task_id] = experience

        if is_update:
            self._save_all()
        else:
            self._append_one(experience)

        # Viking write-through
        if self._viking is not None and task_id:
            self._viking.put(f"viking://agent/experiences/{task_id}", experience)

    def add_batch(self, experiences: List[dict]) -> int:
        """Batch-write experiences.  Returns count of new/updated entries."""
        count = 0
        for exp in experiences:
            exp = self._ensure_created_at(exp)
            task_id = exp.get("task_id", "")
            if task_id not in self._store or self._store[task_id] != exp:
                self._store[task_id] = exp
                count += 1
                # Viking write-through
                if self._viking is not None and task_id:
                    self._viking.put(f"viking://agent/experiences/{task_id}", exp)

        if count > 0:
            self._save_all()
        return count

    def query(
        self,
        question_type: Optional[str] = None,
        reasoning_type: Optional[str] = None,
        knowledge_domain: Optional[str] = None,
        level: Optional[int] = None,
        was_correct: Optional[bool] = None,
        max_count: int = 10,
        semantic_query: Optional[str] = None,
    ) -> List[dict]:
        """Multi-dimensional AND filter.  Returns matches in reverse-chronological order.

        When *semantic_query* is provided and a viking_context + viking_storage
        are available, a semantic search on OpenViking is performed and the
        results are merged with local matches (deduplicated by task_id).
        """
        results = list(self._store.values())

        if question_type is not None:
            qt_lower = question_type.lower()
            results = [e for e in results if qt_lower in e.get("question_type", "").lower()]
        if reasoning_type is not None:
            rt_lower = reasoning_type.lower()
            results = [e for e in results if rt_lower in e.get("reasoning_type", "").lower()]
        if knowledge_domain is not None:
            kd_lower = knowledge_domain.lower()
            results = [e for e in results if kd_lower in e.get("knowledge_domain", "").lower()]
        if level is not None:
            results = [e for e in results if e.get("level") == level]
        if was_correct is not None:
            results = [e for e in results if e.get("was_correct") == was_correct]

        # Semantic search enrichment via OpenViking
        if semantic_query is not None and self._viking_context is not None and self._viking is not None:
            try:
                remote_hits = self._viking.query_sync(
                    self._viking_context.search_by_embedding(
                        query_text=semantic_query,
                        uri_prefix="viking://agent/experiences/",
                        max_results=max_count,
                    )
                )
                # Merge: dedup by task_id (local wins)
                local_ids = {e.get("task_id") for e in results}
                for hit in remote_hits:
                    data = hit.get("data", {})
                    tid = data.get("task_id", "")
                    if tid and tid not in local_ids:
                        results.append(data)
                        local_ids.add(tid)
            except Exception as e:
                logger.warning(f"Semantic search enrichment failed: {e}")

        results.sort(key=lambda e: e.get("created_at", ""), reverse=True)
        return results[:max_count]

    def get_all(self) -> List[dict]:
        """Return every experience (for sub-module C aggregation)."""
        return list(self._store.values())

    def format_for_prompt(
        self,
        experiences: List[dict],
        max_tokens: int = 1500,
    ) -> str:
        """Format experiences into text suitable for system-prompt injection.

        Approximate token budget: 1 token ~ 4 chars.
        """
        if not experiences:
            return ""

        max_chars = max_tokens * 4
        lines: List[str] = ["\n# Lessons from Past Predictions\n"]

        for exp in experiences:
            q_summary = exp.get("question_summary", "")
            lesson = exp.get("lesson", "")
            failure = exp.get("failure_pattern", "")

            if exp.get("was_correct"):
                line = f"- [OK] {q_summary}: {lesson}"
            else:
                line = f"- [FAIL] {q_summary} (error: {failure}): {lesson}"

            candidate = "\n".join(lines + [line, ""])
            if len(candidate) > max_chars:
                break
            lines.append(line)

        lines.append("")
        text = "\n".join(lines)
        return text if len(text.strip()) > len("# Lessons from Past Predictions") else ""

    def stats(self) -> dict:
        """Return aggregate statistics about the experience store."""
        all_exp = list(self._store.values())
        by_question_type: Dict[str, int] = {}
        by_reasoning_type: Dict[str, int] = {}
        correct = 0

        for e in all_exp:
            if e.get("was_correct"):
                correct += 1
            qt = e.get("question_type", "unknown")
            by_question_type[qt] = by_question_type.get(qt, 0) + 1
            rt = e.get("reasoning_type", "unknown")
            by_reasoning_type[rt] = by_reasoning_type.get(rt, 0) + 1

        return {
            "total": len(all_exp),
            "correct": correct,
            "incorrect": len(all_exp) - correct,
            "by_question_type": by_question_type,
            "by_reasoning_type": by_reasoning_type,
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _load(self) -> None:
        """Load JSONL into in-memory dict keyed by task_id."""
        if not self._file_path.exists():
            return
        try:
            with open(self._file_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        exp = json.loads(line)
                        task_id = exp.get("task_id", "")
                        if task_id:
                            self._store[task_id] = exp
                    except json.JSONDecodeError:
                        continue
        except OSError as exc:
            logger.warning(f"Could not read experience file {self._file_path}: {exc}")

    def _save_all(self) -> None:
        """Full rewrite — guarantees dedup consistency."""
        self._file_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self._file_path, "w", encoding="utf-8") as f:
            for exp in self._store.values():
                f.write(json.dumps(exp, ensure_ascii=False) + "\n")

    def _append_one(self, experience: dict) -> None:
        """Fast-path: append a single new entry (no dedup conflict)."""
        self._file_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self._file_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(experience, ensure_ascii=False) + "\n")

    @staticmethod
    def _ensure_created_at(experience: dict) -> dict:
        if not experience.get("created_at"):
            experience = dict(experience)
            experience["created_at"] = datetime.now(timezone.utc).isoformat()
        return experience
