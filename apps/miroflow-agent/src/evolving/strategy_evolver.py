# Copyright (c) 2025 MiroMind
# Self-Evolving: Strategy Evolver module
# Aggregates meta-knowledge from experiences (strategy preferences, failure
# patterns) and generates prompt patches for underperforming question types.
# Sub-module D (ExperienceInjector) reads results via load_strategy_preferences()
# and load_active_prompt_overrides().

import json
import logging
import re
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from .experience_store import ExperienceStore

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Prompt template for generating prompt patches (section 6 of the spec)
# ---------------------------------------------------------------------------

PATCH_GENERATION_PROMPT = """\
你是一个 AI 系统的 prompt 优化专家。以下是某类题目的历史失败分析：

题目类型：{question_type}
近期表现：{recent_accuracy}（{total} 题中答对 {correct} 题）
高频失败模式：
{failure_patterns}

典型失败案例的 lesson：
{lessons}

请生成一段简洁的 prompt 补充指令（50-150 字），用于插入到 agent 的 system prompt 中，\
帮助 agent 在遇到此类题目时避免上述错误模式。

要求：
- 给出具体、可执行的指令，不要笼统建议
- 针对失败模式逐一给出对策
- 不要重复 system prompt 中已有的通用指令

只返回 prompt 补充指令文本本身，不要加标题或额外解释。"""


class StrategyEvolver:
    """Extracts meta-knowledge from experiences and generates prompt patches.

    Public API consumed by sub-module D (ExperienceInjector):
        - load_strategy_preferences()
        - load_active_prompt_overrides(question_type)
    """

    def __init__(
        self,
        experience_store: ExperienceStore,
        preferences_file: str,
        prompt_overrides_file: str,
        min_samples: int = 3,
        failure_threshold: float = 0.4,
    ):
        self._store = experience_store
        self._preferences_path = Path(preferences_file) if preferences_file else Path("data/strategy_preferences.json")
        self._overrides_path = Path(prompt_overrides_file) if prompt_overrides_file else Path("data/prompt_overrides.jsonl")
        self._min_samples = min_samples
        self._failure_threshold = failure_threshold

    # ------------------------------------------------------------------
    # C1: Strategy preference aggregation
    # ------------------------------------------------------------------

    def aggregate_strategy_preferences(self) -> dict:
        """Cross-tabulate question_type x strategy_name and write preferences file.

        Returns the full preferences dict (also persisted to disk).
        """
        all_exp = self._store.get_all()

        stats: Dict[str, Dict[str, Dict[str, int]]] = defaultdict(
            lambda: defaultdict(lambda: {"total": 0, "correct": 0})
        )
        for exp in all_exp:
            qt = exp.get("question_type", "")
            sn = exp.get("strategy_name", "")
            if not qt or not sn:
                continue
            stats[qt][sn]["total"] += 1
            if exp.get("was_correct"):
                stats[qt][sn]["correct"] += 1

        output_stats: Dict[str, dict] = {}
        recommendations: Dict[str, Any] = {}

        for qt, strategies in stats.items():
            qt_stats: Dict[str, dict] = {}
            for sn, counts in strategies.items():
                total = counts["total"]
                correct = counts["correct"]
                accuracy = correct / total if total > 0 else 0.0
                qt_stats[sn] = {
                    "total": total,
                    "correct": correct,
                    "accuracy": round(accuracy, 4),
                }
            qt_stats = dict(
                sorted(qt_stats.items(), key=lambda kv: kv[1]["accuracy"], reverse=True)
            )
            output_stats[qt] = qt_stats

            recs = [
                sn
                for sn, s in qt_stats.items()
                if s["accuracy"] >= 0.5 and s["total"] >= self._min_samples
            ]
            if recs:
                recommendations[qt] = recs
            else:
                has_enough = any(s["total"] >= self._min_samples for s in qt_stats.values())
                recommendations[qt] = [] if has_enough else "insufficient_data"

        result = {
            "version": datetime.now(timezone.utc).isoformat(),
            "stats": output_stats,
            "recommendations": recommendations,
        }

        self._preferences_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self._preferences_path, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)

        logger.info(
            f"Strategy preferences aggregated: {len(output_stats)} question types, "
            f"written to {self._preferences_path}"
        )
        return result

    # ------------------------------------------------------------------
    # Failure pattern aggregation
    # ------------------------------------------------------------------

    def aggregate_failure_patterns(self) -> dict:
        """Group failures by question_type x failure_pattern.

        Returns::

            {
              "finance_market": {
                "top_failures": [
                  {"pattern": "outdated_info", "count": 8, "typical_lesson": "..."},
                  ...
                ]
              }
            }
        """
        all_exp = self._store.get_all()

        buckets: Dict[str, Dict[str, List[dict]]] = defaultdict(lambda: defaultdict(list))
        for exp in all_exp:
            if exp.get("was_correct"):
                continue
            qt = exp.get("question_type", "")
            fp = exp.get("failure_pattern", "")
            if not qt or not fp:
                continue
            buckets[qt][fp].append(exp)

        result: Dict[str, dict] = {}
        for qt, patterns in buckets.items():
            failures = []
            for pattern, exps in patterns.items():
                most_recent = max(exps, key=lambda e: e.get("created_at", ""))
                failures.append({
                    "pattern": pattern,
                    "count": len(exps),
                    "typical_lesson": most_recent.get("lesson", ""),
                })
            failures.sort(key=lambda f: f["count"], reverse=True)
            result[qt] = {"top_failures": failures}

        return result

    # ------------------------------------------------------------------
    # C2: Prompt patch generation
    # ------------------------------------------------------------------

    async def generate_prompt_patches(
        self,
        llm_client: Any,
        model: str = "",
        auto_approve: bool = False,
    ) -> List[dict]:
        """Analyse high-failure question types and call LLM to produce prompt patches.

        Patches are appended to ``prompt_overrides_file``.

        Returns:
            List of generated patch dicts.
        """
        prefs = self.aggregate_strategy_preferences()
        failure_data = self.aggregate_failure_patterns()

        triggered_types: List[str] = []
        stats = prefs.get("stats", {})

        for qt, strategies in stats.items():
            total = sum(s["total"] for s in strategies.values())
            correct = sum(s["correct"] for s in strategies.values())
            if total == 0:
                continue
            accuracy = correct / total
            if accuracy < self._failure_threshold:
                triggered_types.append(qt)
                continue

            fp_data = failure_data.get(qt, {}).get("top_failures", [])
            if any(f["count"] >= 3 for f in fp_data):
                triggered_types.append(qt)

        if not triggered_types:
            logger.info("No question types triggered for prompt patch generation.")
            return []

        logger.info(f"Prompt patch generation triggered for: {triggered_types}")
        patches: List[dict] = []

        for qt in triggered_types:
            qt_stats = stats.get(qt, {})
            total = sum(s["total"] for s in qt_stats.values())
            correct = sum(s["correct"] for s in qt_stats.values())
            accuracy_str = f"{correct}/{total} = {correct / total:.0%}" if total else "N/A"

            fp_entries = failure_data.get(qt, {}).get("top_failures", [])
            fp_text = "\n".join(
                f"- {f['pattern']} ({f['count']} 次)" for f in fp_entries
            ) or "(无)"
            lessons_text = "\n".join(
                f"- {f['typical_lesson']}" for f in fp_entries if f.get("typical_lesson")
            ) or "(无)"

            prompt = PATCH_GENERATION_PROMPT.format(
                question_type=qt,
                recent_accuracy=accuracy_str,
                total=total,
                correct=correct,
                failure_patterns=fp_text,
                lessons=lessons_text,
            )

            create_kwargs: dict[str, Any] = dict(
                messages=[{"role": "user", "content": prompt}],
                max_completion_tokens=512,
                temperature=0.4,
            )
            if model:
                create_kwargs["model"] = model

            try:
                response = await llm_client.chat.completions.create(**create_kwargs)
                content = response.choices[0].message.content.strip()
            except Exception as e:
                logger.warning(f"Failed to generate patch for {qt}: {e}")
                continue

            patch = {
                "question_type": qt,
                "trigger": f"accuracy {accuracy_str} (threshold {self._failure_threshold})",
                "patch_type": "append",
                "content": content,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "auto_approved": auto_approve,
                "applied": False,
            }
            patches.append(patch)

        if patches:
            self._append_overrides(patches)
            logger.info(f"Generated {len(patches)} prompt patches.")

        return patches

    # ------------------------------------------------------------------
    # Read interfaces for sub-module D
    # ------------------------------------------------------------------

    def load_strategy_preferences(self) -> dict:
        """Load the persisted strategy preferences (for ExperienceInjector)."""
        if not self._preferences_path.exists():
            return {}
        try:
            with open(self._preferences_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            logger.warning(f"Could not load strategy preferences: {e}")
            return {}

    def load_active_prompt_overrides(
        self,
        question_type: Optional[str] = None,
    ) -> List[dict]:
        """Return prompt patches that are approved or applied.

        Args:
            question_type: If given, only return patches for this type.
        """
        all_patches = self._load_all_overrides()
        active = [
            p for p in all_patches
            if p.get("auto_approved") or p.get("applied")
        ]
        if question_type:
            qt_lower = question_type.lower()
            active = [p for p in active if qt_lower in p.get("question_type", "").lower()]
        return active

    # ------------------------------------------------------------------
    # Patch management
    # ------------------------------------------------------------------

    def approve_patch(self, index: int) -> None:
        """Mark patch at *index* as approved (``auto_approved = True``)."""
        patches = self._load_all_overrides()
        if 0 <= index < len(patches):
            patches[index]["auto_approved"] = True
            self._rewrite_overrides(patches)
            logger.info(f"Approved patch #{index}")
        else:
            logger.warning(f"Patch index {index} out of range (total {len(patches)})")

    def rollback_patch(self, index: int) -> None:
        """Mark patch at *index* as not applied (``applied = False``)."""
        patches = self._load_all_overrides()
        if 0 <= index < len(patches):
            patches[index]["applied"] = False
            self._rewrite_overrides(patches)
            logger.info(f"Rolled back patch #{index}")
        else:
            logger.warning(f"Patch index {index} out of range (total {len(patches)})")

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _load_all_overrides(self) -> List[dict]:
        if not self._overrides_path.exists():
            return []
        patches: List[dict] = []
        try:
            with open(self._overrides_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        patches.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
        except OSError as e:
            logger.warning(f"Could not read overrides file: {e}")
        return patches

    def _rewrite_overrides(self, patches: List[dict]) -> None:
        self._overrides_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self._overrides_path, "w", encoding="utf-8") as f:
            for p in patches:
                f.write(json.dumps(p, ensure_ascii=False) + "\n")

    def _append_overrides(self, patches: List[dict]) -> None:
        self._overrides_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self._overrides_path, "a", encoding="utf-8") as f:
            for p in patches:
                f.write(json.dumps(p, ensure_ascii=False) + "\n")
