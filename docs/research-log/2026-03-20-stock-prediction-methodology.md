# 2026-03-20: Stock Prediction Validation Methodology

## Correction Priority

When validating stock predictions against actual results, follow this order:

1. **Timestamp first** — When was the prediction made?
   - Information changes constantly. A prediction made Friday evening vs Sunday night may face completely different conditions.
   - Record: prediction timestamp, data cutoff point, any major events between prediction and market open.
   - If significant events occurred after prediction (e.g., weekend ceasefire, new sanctions), note them as "post-prediction information" — the prediction was correct *given what was known at the time*, or wrong even with available data.

2. **Direction second** — Was the predicted direction (up/down) correct?
   - This is the most important accuracy signal. Getting direction right matters more than exact numbers.
   - Record: predicted direction vs actual direction (correct/incorrect)

3. **Magnitude third** — How far off was the predicted change percentage?
   - Compare predicted % change vs actual % change
   - Record: magnitude error = |predicted_change% - actual_change%|

## Why This Order

- Direction accuracy is binary and actionable (buy/sell decision)
- Magnitude error is continuous and less critical (position sizing)
- A prediction that gets direction right but magnitude wrong is still useful
- A prediction that gets magnitude close but direction wrong is harmful

## Metrics to Track

| Metric | Formula | Target |
|--------|---------|--------|
| Direction accuracy | correct_directions / total_predictions | > 55% |
| Magnitude MAE | mean(|predicted_% - actual_%|) | minimize |
| Open price error | |predicted_open - actual_open| | minimize |
| Close price error | |predicted_close - actual_close| | minimize |

## First Prediction: VOO 3/23/2026

- **Prediction timestamp:** 2026-03-20 20:15 UTC (Friday, after market close)
- **Data cutoff:** VOO close $597.58, after-hours $598.90 (3/20 16:10 EDT)
- Predicted open: ~$597
- Predicted close: ~$593
- Predicted direction: down
- Confidence: 70%
- Key drivers: Middle East war, oil price surge, technical breakdown
- **Post-prediction risk:** Weekend events (ceasefire talks, further escalation, Fed statements) could invalidate basis

Validation scheduled for 3/23 21:00 UTC.
