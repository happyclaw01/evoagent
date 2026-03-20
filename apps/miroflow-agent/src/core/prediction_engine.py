# EA-408: Continuous Prediction Engine
# EA-409: Prediction Update Scheduler
# EA-410: Prediction Validation & Trajectory Analysis
#
# Turns EvoAgent from a one-shot predictor into a rolling prediction engine.
# Prediction → Continuous Updates → Validation → Learning

import hashlib
import json
import logging
import os
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# EA-408: Core Data Models
# ---------------------------------------------------------------------------

@dataclass
class Prediction:
    """A prediction with metadata and context."""
    id: str
    target: str                          # e.g., "VOO", "BTC", "Arsenal vs Chelsea"
    target_type: str                     # "stock", "crypto", "sports", "event"
    created_at: str                      # ISO timestamp (UTC)
    data_cutoff: str                     # Last data point used
    resolve_at: str                      # When the prediction should be validated

    # Prediction values
    direction: str                       # "up" / "down" / "neutral"
    confidence: float                    # 0.0 - 1.0
    predicted_open: Optional[float] = None
    predicted_close: Optional[float] = None
    predicted_change_pct: Optional[float] = None

    # Context
    key_drivers: List[str] = field(default_factory=list)
    strategies_used: List[str] = field(default_factory=list)
    raw_path_results: List[Dict[str, Any]] = field(default_factory=list)

    # Update tracking
    updates: List["PredictionUpdate"] = field(default_factory=list)
    validation: Optional["PredictionValidation"] = None

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        return d

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "Prediction":
        updates = [PredictionUpdate(**u) for u in d.pop("updates", [])]
        val_data = d.pop("validation", None)
        validation = PredictionValidation(**val_data) if val_data else None
        return cls(**d, updates=updates, validation=validation)


@dataclass
class PredictionUpdate:
    """A single update to an existing prediction."""
    prediction_id: str
    timestamp: str                       # ISO timestamp (UTC)
    current_price: float
    updated_direction: Optional[str] = None      # None = no change
    updated_close: Optional[float] = None        # None = no change
    updated_confidence: Optional[float] = None   # None = no change
    reason: str = "scheduled"            # "scheduled" / "breaking_news" / "price_move"
    new_info: Optional[str] = None       # What changed

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class PredictionValidation:
    """Validation result comparing prediction to actual outcome."""
    prediction_id: str
    validated_at: str
    actual_open: float
    actual_close: float
    actual_change_pct: float

    # Accuracy (priority order per Enricher directive)
    # 1. Timestamp awareness (handled by post_prediction_events)
    # 2. Direction accuracy
    # 3. Magnitude accuracy
    direction_correct: bool = False
    magnitude_error_pct: float = 0.0
    open_error: float = 0.0
    close_error: float = 0.0

    # Post-prediction analysis
    post_prediction_events: List[str] = field(default_factory=list)
    driver_accuracy: Dict[str, bool] = field(default_factory=dict)

    # Update trajectory analysis
    num_updates: int = 0
    final_update_direction: Optional[str] = None
    final_update_correct: bool = False
    convergence: str = "stable"          # "converged" / "diverged" / "stable"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# EA-408: Prediction Engine
# ---------------------------------------------------------------------------

class PredictionEngine:
    """Manages the lifecycle of predictions: create, update, validate, learn."""

    def __init__(self, store_dir: str = "data/predictions"):
        self.store_dir = Path(store_dir)
        self.store_dir.mkdir(parents=True, exist_ok=True)
        self.predictions: Dict[str, Prediction] = {}
        self._load_all()

    def _load_all(self):
        """Load all predictions from disk."""
        for f in self.store_dir.glob("*.json"):
            try:
                with open(f) as fh:
                    data = json.load(fh)
                    pred = Prediction.from_dict(data)
                    self.predictions[pred.id] = pred
            except Exception as e:
                logger.warning(f"Failed to load prediction {f}: {e}")

    def _save(self, prediction: Prediction):
        """Persist a prediction to disk."""
        path = self.store_dir / f"{prediction.id}.json"
        with open(path, "w") as f:
            json.dump(prediction.to_dict(), f, indent=2, ensure_ascii=False)

    def _generate_id(self, target: str) -> str:
        """Generate a unique prediction ID."""
        ts = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
        h = hashlib.md5(f"{target}{ts}{time.time()}".encode()).hexdigest()[:8]
        return f"pred_{target}_{ts}_{h}"

    # --- EA-408: Create ---

    def create_prediction(
        self,
        target: str,
        target_type: str,
        direction: str,
        confidence: float,
        resolve_at: str,
        predicted_open: Optional[float] = None,
        predicted_close: Optional[float] = None,
        predicted_change_pct: Optional[float] = None,
        key_drivers: Optional[List[str]] = None,
        strategies_used: Optional[List[str]] = None,
        raw_path_results: Optional[List[Dict]] = None,
    ) -> Prediction:
        """Create a new prediction."""
        now = datetime.now(timezone.utc).isoformat()
        pred = Prediction(
            id=self._generate_id(target),
            target=target,
            target_type=target_type,
            created_at=now,
            data_cutoff=now,
            resolve_at=resolve_at,
            direction=direction,
            confidence=confidence,
            predicted_open=predicted_open,
            predicted_close=predicted_close,
            predicted_change_pct=predicted_change_pct,
            key_drivers=key_drivers or [],
            strategies_used=strategies_used or [],
            raw_path_results=raw_path_results or [],
        )
        self.predictions[pred.id] = pred
        self._save(pred)
        logger.info(f"Created prediction {pred.id}: {target} {direction} (conf={confidence})")
        return pred

    # --- EA-409: Update ---

    def update_prediction(
        self,
        prediction_id: str,
        current_price: float,
        reason: str = "scheduled",
        new_info: Optional[str] = None,
        updated_direction: Optional[str] = None,
        updated_close: Optional[float] = None,
        updated_confidence: Optional[float] = None,
    ) -> PredictionUpdate:
        """Record an update to an existing prediction."""
        pred = self.predictions.get(prediction_id)
        if not pred:
            raise ValueError(f"Prediction {prediction_id} not found")

        now = datetime.now(timezone.utc).isoformat()
        update = PredictionUpdate(
            prediction_id=prediction_id,
            timestamp=now,
            current_price=current_price,
            updated_direction=updated_direction,
            updated_close=updated_close,
            updated_confidence=updated_confidence,
            reason=reason,
            new_info=new_info,
        )
        pred.updates.append(update)
        self._save(pred)
        logger.info(
            f"Updated prediction {prediction_id}: price=${current_price}, "
            f"reason={reason}, direction_change={updated_direction}"
        )
        return update

    def should_update(
        self,
        prediction_id: str,
        current_price: float,
        price_threshold_pct: float = 1.0,
    ) -> tuple[bool, str]:
        """Determine if a prediction update is warranted based on price movement.

        Returns (should_update, reason).
        """
        pred = self.predictions.get(prediction_id)
        if not pred:
            return False, "prediction_not_found"

        # Get last known price
        if pred.updates:
            last_price = pred.updates[-1].current_price
        elif pred.predicted_close:
            last_price = pred.predicted_close
        else:
            return True, "no_baseline"

        pct_change = abs(current_price - last_price) / last_price * 100
        if pct_change >= price_threshold_pct:
            return True, f"price_move_{pct_change:.1f}pct"

        return False, "within_threshold"

    # --- EA-410: Validate ---

    def validate_prediction(
        self,
        prediction_id: str,
        actual_open: float,
        actual_close: float,
        post_prediction_events: Optional[List[str]] = None,
        driver_accuracy: Optional[Dict[str, bool]] = None,
    ) -> PredictionValidation:
        """Validate a prediction against actual results.

        Validation priority (per directive):
        1. Timestamp — awareness of when prediction was made
        2. Direction — up/down correct?
        3. Magnitude — how far off?
        """
        pred = self.predictions.get(prediction_id)
        if not pred:
            raise ValueError(f"Prediction {prediction_id} not found")

        now = datetime.now(timezone.utc).isoformat()

        # Calculate actual change
        if pred.predicted_open and pred.predicted_open > 0:
            base_price = pred.predicted_open
        elif pred.predicted_close and pred.predicted_close > 0:
            base_price = pred.predicted_close
        else:
            base_price = actual_open

        actual_change_pct = (actual_close - actual_open) / actual_open * 100

        # Priority 2: Direction accuracy
        actual_direction = "up" if actual_close > actual_open else "down" if actual_close < actual_open else "neutral"
        direction_correct = pred.direction == actual_direction

        # Priority 3: Magnitude accuracy
        predicted_change = pred.predicted_change_pct or 0.0
        if pred.predicted_open and pred.predicted_close:
            predicted_change = (pred.predicted_close - pred.predicted_open) / pred.predicted_open * 100
        magnitude_error_pct = abs(predicted_change - actual_change_pct)

        # Price errors
        open_error = abs(pred.predicted_open - actual_open) if pred.predicted_open else 0.0
        close_error = abs(pred.predicted_close - actual_close) if pred.predicted_close else 0.0

        # Update trajectory analysis
        num_updates = len(pred.updates)
        final_update_direction = None
        final_update_correct = False
        convergence = "stable"

        if pred.updates:
            # Get last update with a direction change
            for u in reversed(pred.updates):
                if u.updated_direction:
                    final_update_direction = u.updated_direction
                    break
            if final_update_direction:
                final_update_correct = final_update_direction == actual_direction

            # Convergence analysis: did updates move predictions closer to actual?
            if num_updates >= 2:
                last_close = pred.updates[-1].updated_close or pred.predicted_close
                first_close = pred.updates[0].updated_close or pred.predicted_close
                if last_close and first_close:
                    last_error = abs(last_close - actual_close)
                    first_error = abs(first_close - actual_close)
                    if last_error < first_error * 0.8:
                        convergence = "converged"
                    elif last_error > first_error * 1.2:
                        convergence = "diverged"

        validation = PredictionValidation(
            prediction_id=prediction_id,
            validated_at=now,
            actual_open=actual_open,
            actual_close=actual_close,
            actual_change_pct=actual_change_pct,
            direction_correct=direction_correct,
            magnitude_error_pct=magnitude_error_pct,
            open_error=open_error,
            close_error=close_error,
            post_prediction_events=post_prediction_events or [],
            driver_accuracy=driver_accuracy or {},
            num_updates=num_updates,
            final_update_direction=final_update_direction,
            final_update_correct=final_update_correct,
            convergence=convergence,
        )

        pred.validation = validation
        self._save(pred)

        logger.info(
            f"Validated {prediction_id}: direction={'✅' if direction_correct else '❌'}, "
            f"magnitude_error={magnitude_error_pct:.2f}%, convergence={convergence}"
        )
        return validation

    # --- EA-410: Reporting ---

    def generate_report(self, prediction_id: str) -> str:
        """Generate a human-readable validation report."""
        pred = self.predictions.get(prediction_id)
        if not pred:
            return f"Prediction {prediction_id} not found"

        lines = []
        lines.append(f"## Prediction Report: {pred.target}")
        lines.append(f"**Created:** {pred.created_at}")
        lines.append(f"**Target:** {pred.target} ({pred.target_type})")
        lines.append("")

        # Prediction
        lines.append("### Prediction")
        lines.append(f"- Direction: {pred.direction} (confidence: {pred.confidence:.0%})")
        if pred.predicted_open:
            lines.append(f"- Open: ${pred.predicted_open:.2f}")
        if pred.predicted_close:
            lines.append(f"- Close: ${pred.predicted_close:.2f}")
        lines.append(f"- Key drivers: {', '.join(pred.key_drivers)}")
        lines.append(f"- Strategies: {', '.join(pred.strategies_used)}")
        lines.append("")

        # Updates
        if pred.updates:
            lines.append(f"### Updates ({len(pred.updates)} total)")
            for u in pred.updates:
                change = ""
                if u.updated_direction:
                    change += f"direction→{u.updated_direction} "
                if u.updated_close:
                    change += f"close→${u.updated_close:.2f} "
                if not change:
                    change = "no change"
                lines.append(f"- {u.timestamp}: ${u.current_price:.2f} [{u.reason}] {change}")
            lines.append("")

        # Validation
        v = pred.validation
        if v:
            lines.append("### Validation")
            lines.append(f"1. **Timestamp:** Predicted at {pred.created_at}, validated at {v.validated_at}")
            if v.post_prediction_events:
                lines.append(f"   Post-prediction events: {', '.join(v.post_prediction_events)}")
            lines.append(f"2. **Direction:** {'✅ CORRECT' if v.direction_correct else '❌ WRONG'} "
                        f"(predicted {pred.direction}, actual {'up' if v.actual_close > v.actual_open else 'down'})")
            lines.append(f"3. **Magnitude:** error {v.magnitude_error_pct:.2f}%")
            if pred.predicted_open:
                lines.append(f"   Open: predicted ${pred.predicted_open:.2f} vs actual ${v.actual_open:.2f} (error ${v.open_error:.2f})")
            if pred.predicted_close:
                lines.append(f"   Close: predicted ${pred.predicted_close:.2f} vs actual ${v.actual_close:.2f} (error ${v.close_error:.2f})")
            lines.append(f"   Actual change: {v.actual_change_pct:+.2f}%")
            lines.append("")

            # Trajectory
            if v.num_updates > 0:
                lines.append("### Update Trajectory")
                lines.append(f"- Total updates: {v.num_updates}")
                lines.append(f"- Convergence: {v.convergence}")
                if v.final_update_direction:
                    lines.append(f"- Final update direction: {v.final_update_direction} "
                                f"({'✅' if v.final_update_correct else '❌'})")

        return "\n".join(lines)

    # --- Statistics ---

    def get_accuracy_stats(self) -> Dict[str, Any]:
        """Compute aggregate accuracy statistics across all validated predictions."""
        validated = [p for p in self.predictions.values() if p.validation]
        if not validated:
            return {"total": 0, "message": "No validated predictions yet"}

        total = len(validated)
        direction_correct = sum(1 for p in validated if p.validation.direction_correct)
        magnitude_errors = [p.validation.magnitude_error_pct for p in validated]
        convergence_counts = {"converged": 0, "diverged": 0, "stable": 0}
        for p in validated:
            convergence_counts[p.validation.convergence] = (
                convergence_counts.get(p.validation.convergence, 0) + 1
            )

        return {
            "total": total,
            "direction_accuracy": direction_correct / total,
            "direction_correct": direction_correct,
            "direction_wrong": total - direction_correct,
            "avg_magnitude_error_pct": sum(magnitude_errors) / total,
            "min_magnitude_error_pct": min(magnitude_errors),
            "max_magnitude_error_pct": max(magnitude_errors),
            "convergence": convergence_counts,
        }

    def list_predictions(self, status: Optional[str] = None) -> List[Prediction]:
        """List predictions, optionally filtered by status."""
        preds = list(self.predictions.values())
        if status == "pending":
            preds = [p for p in preds if p.validation is None]
        elif status == "validated":
            preds = [p for p in preds if p.validation is not None]
        return sorted(preds, key=lambda p: p.created_at, reverse=True)
