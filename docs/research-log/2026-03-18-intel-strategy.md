# 2026-03-18: Intelligence Analysis Strategy

## Inspiration

Observed methodology from Hormuz Strait intelligence analysis (built as a separate skill).
The analyst approach follows a disciplined multi-source pattern:

1. **Source diversification** — AIS data, news agencies, official data, domain-specific sources
2. **Cross-validation** — Same claim must appear in ≥2 independent sources
3. **Quantitative baseline** — Compare current numbers against historical normal ranges
4. **Anomaly detection** — Flag sudden changes, contradictions, missing data
5. **Structured output** — Status ratings with confidence levels
6. **Source attribution** — Every claim cites its source and date

## Mapping to EvoAgent

This methodology maps directly to our multi-path architecture:

### `intel_analysis` Strategy

A new strategy variant that instructs the agent to behave like an OSINT analyst.
Key difference from existing strategies:

- `breadth_first` → searches widely but doesn't cross-validate
- `depth_first` → goes deep but may miss conflicting sources
- `lateral_thinking` → creative but not systematic
- `verification_heavy` → verifies but doesn't establish baselines
- **`intel_analysis`** → combines all four: wide search, deep verification, baseline comparison, structured output

### `devils_advocate` Strategy

Also inspired by the intelligence analysis process: the need for a contrarian voice
to prevent groupthink (directly addresses the "someone said" vulnerability from EA-309).

This strategy deliberately tries to disprove the emerging consensus. If all paths
agree but the devil's advocate path also agrees after trying to disagree, confidence
is much higher.

**Connection to EA-309 (Groupthink Detector):** When groupthink is detected, the
system should automatically add a devil's advocate path. This is a natural integration
point.

## Impact on "Someone Said" Attack

The "someone said" attack worked because all paths accepted the injected information.
With `devils_advocate`:

- breadth_first: might accept "someone said X"
- depth_first: might accept "someone said X"  
- **devils_advocate**: "Wait, let me check if X is actually true..."

This won't fully solve the problem (the devil's advocate might also be anchored),
but it adds a structural defense layer.

## Future Work

1. Connect `devils_advocate` to EA-309: auto-spawn when groupthink score > threshold
2. Define "intelligence task" classifier in EA-103 to auto-select `intel_analysis`
3. Test against FutureX L3/L4 questions (which require multi-source analysis)
