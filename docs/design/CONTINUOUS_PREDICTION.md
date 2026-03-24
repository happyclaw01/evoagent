# Continuous Prediction System Design

## Overview

A mechanism for EvoAgent to make predictions and continuously update them as new information arrives, then validate against actual outcomes. This turns EvoAgent from a one-shot predictor into a **rolling prediction engine**.

## Core Concept

```
Prediction          Continuous Updates              Validation
   │                      │                            │
   ▼                      ▼                            ▼
T₀: Initial ──→ T₁..Tₙ: Update every 30min ──→ T_end: Compare
prediction       as new data arrives               prediction vs actual
```

Traditional: predict once → check later → learn.
Continuous: predict → update → update → ... → check → learn from the ENTIRE trajectory.

## Three-Phase Architecture

### Phase 1: Initial Prediction (T₀)

Multi-path analysis produces:
- **Direction** (most important): up/down
- **Magnitude**: estimated % change
- **Price targets**: open/close
- **Confidence**: 0-100%
- **Key drivers**: what factors informed the prediction
- **Timestamp**: when prediction was made (data cutoff point)

### Phase 2: Continuous Updates (T₁ ... Tₙ)

At fixed intervals (e.g., every 30 minutes):
1. **Fetch current price** — compare against last update
2. **Scan for breaking events** — news that changes the thesis
3. **Update or maintain** — only update prediction if material change detected
4. **Log the update** — timestamp, price, reason for change (or "no change")

Update triggers (beyond scheduled intervals):
- Price moves > 1% since last update
- Breaking news matching key drivers (e.g., oil price, geopolitical event)
- Significant volume spike

### Phase 3: Validation (T_end)

After the event resolves:
1. **Timestamp check** — how old was the prediction at validation time? What new info emerged after?
2. **Direction accuracy** — did we get up/down right?
3. **Magnitude accuracy** — how far off was the % change?
4. **Update trajectory analysis** — did our updates converge toward the actual result, or diverge?
5. **Driver analysis** — which of our identified key drivers actually mattered?

## Validation Priority (per Enricher's directive)

1. **Timestamp** — When was the prediction made? What info was available?
2. **Direction** — Up or down correct?
3. **Magnitude** — How far off on % change?

## Data Model

```python
@dataclass
class Prediction:
    id: str                    # Unique prediction ID
    target: str                # e.g., "VOO", "BTC", "Arsenal vs Chelsea"
    target_type: str           # "stock", "crypto", "sports", "event"
    created_at: str            # ISO timestamp (UTC)
    data_cutoff: str           # Last data point used
    
    # Prediction values
    direction: str             # "up" / "down" / "neutral"
    confidence: float          # 0.0 - 1.0
    predicted_open: float | None
    predicted_close: float | None
    predicted_change_pct: float | None
    
    # Context
    key_drivers: list[str]     # What informed the prediction
    strategy_used: str         # Which EvoAgent strategy produced this
    
@dataclass  
class PredictionUpdate:
    prediction_id: str
    timestamp: str             # When this update was made
    current_price: float
    updated_direction: str | None      # None = no change
    updated_close: float | None        # None = no change
    updated_confidence: float | None   # None = no change
    reason: str                        # "scheduled" / "breaking_news" / "price_move"
    new_info: str | None               # What changed

@dataclass
class PredictionValidation:
    prediction_id: str
    validated_at: str
    actual_open: float
    actual_close: float
    actual_change_pct: float
    
    # Accuracy metrics
    direction_correct: bool
    magnitude_error_pct: float         # |predicted - actual| change %
    open_error: float                  # |predicted - actual| open price
    close_error: float                 # |predicted - actual| close price
    
    # Post-prediction analysis
    post_prediction_events: list[str]  # Significant events after T₀
    driver_accuracy: dict[str, bool]   # Which drivers were actually relevant
    
    # Update trajectory
    num_updates: int
    final_update_direction: str        # Direction from last update
    final_update_correct: bool         # Was the last update's direction correct?
    convergence: str                   # "converged" / "diverged" / "stable"
```

## Integration with Existing EvoAgent Modules

| Module | Role in Continuous Prediction |
|--------|-------------------------------|
| `multi_path.py` | Initial prediction via parallel strategies |
| `intel_analysis` strategy | Multi-source data collection for updates |
| `devils_advocate` strategy | Challenge the current prediction direction |
| `strategy_tracker.py` (EA-101) | Track which strategy produced the most accurate predictions |
| `experience_extractor.py` (EA-108) | Extract learnings from prediction trajectories |
| `adaptive_selector.py` (EA-104) | Over time, learn which strategy works best for which prediction type |
| `groupthink_detector.py` (EA-309) | Detect if all update paths are converging too quickly (anchoring bias) |
| `reflector.py` | Post-validation reflection: why was the prediction right/wrong? |

## Strategy Selection for Different Prediction Types

| Prediction Type | Best Strategy Combo |
|----------------|---------------------|
| **Stock (daily)** | intel_analysis + depth_first + devils_advocate |
| **Crypto** | breadth_first + lateral_thinking (high noise, need diverse signals) |
| **Sports** | depth_first + verification_heavy (stats-driven) |
| **Geopolitical** | intel_analysis + breadth_first (multi-source critical) |

## Update Frequency Tuning

| Market Phase | Interval | Rationale |
|-------------|----------|-----------|
| Pre-market (6:50-9:30 EDT) | 30 min | Low liquidity, setup phase |
| Market open (9:30-10:30 EDT) | 15 min | Highest volatility |
| Mid-day (10:30-15:00 EDT) | 30 min | Normal trading |
| Market close (15:00-16:00 EDT) | 15 min | Closing volatility |
| After-hours (16:00-20:00 EDT) | 30 min | Low volume, event monitoring |

## Learning Loop

```
Prediction T₀
    │
    ├──→ Update T₁ ... Tₙ (trajectory)
    │
    ▼
Validation T_end
    │
    ├──→ Was direction correct?
    ├──→ Did updates improve or worsen the prediction?
    ├──→ Which drivers actually mattered?
    ├──→ Which strategy performed best?
    │
    ▼
Experience Extraction (EA-108)
    │
    ├──→ "intel_analysis wins for stock predictions during geopolitical crises"
    ├──→ "devils_advocate caught anchoring bias in 3/5 cases"
    ├──→ "opening price predictions are less accurate than direction predictions"
    │
    ▼
Strategy Evolution (EA-104/105)
    │
    └──→ Next prediction uses improved strategy selection + learned biases
```

## Implementation Phases

### Phase 1: Manual (current)
- Predictions made via main session conversation
- Updates via cron jobs sending to Telegram
- Validation via scheduled reminders
- Learnings stored in research-log markdown files

### Phase 2: Semi-automated
- Prediction data model implemented in Python
- Updates automated via scheduled jobs with structured output
- Validation auto-compares predicted vs actual
- Learnings stored in experience_store.py

### Phase 3: Fully automated
- Auto-detect prediction opportunities from conversation
- Self-scheduling updates based on prediction type
- Auto-validation with structured metrics
- Continuous strategy evolution based on prediction accuracy history
