---
doc_id: CON-SZ-METHODS
title: Position Sizing Methods
type: specification
owner: research
status: approved
version: 1.1
components: [5]
tags: [sizing]
aliases: ["Kelly", "ATR Sizing", "Fixed Notional"]
source: "follow-up discussion: vol targeting confirmation; sizing method taxonomy"
---

# Position Sizing Methods

## 1. Summary

Vol targeting is one member of a family of sizing methods. Production reality is
hybrid: a vol-targeting frame, a Kelly-informed target choice, and drawdown overlay
multiplication.

## 2. Catalog

2.1 Fixed notional. Constant exposure regardless of volatility; the baseline this
project started from.

2.2 Vol targeting. p(t) = z(t) times target-over-estimated volatility: exposure
inversely proportional to measured volatility, keeping realized account volatility
near the declared target. Default choice; do not leave without quantitative reason.

2.3 ATR-based sizing. Contracts = risk budget over (ATR times multiplier). The CTA
cousin - same philosophy that higher volatility means smaller size.

2.4 Fractional Kelly. Size proportional to Kelly's edge-over-odds optimum, then
take half or quarter. Conceptual anchor for choosing the volatility target; full
Kelly trusts edge estimates fatally.

2.5 CPPI-style or drawdown-scaled. Exposure falls faster than capital, protecting a
floor - the spirit of the drawdown overlay.

2.6 Signal-confidence sizing. Size proportional to signal strength - already
embedded through z(t) inside the vol-targeting formula.

## 3. Knob map

All methods adjust position size but touch different inputs of
p(t) = z(t) * (vol_target / vol_est): blended forecast and floor touch vol_est;
gap-adjusted sizing touches vol_est via gap risk; regime-aware targets touch
vol_target; drawdown multipliers scale the product. They combine rather than
compete.

Terminology anchor: the thing adjusted is never the signal. Forecasts are
dimensionless; money appears only when Stage 5 converts forecast into exposure.
Position sizing is that conversion and lives at portfolio level only - see
[[concepts/sizing/scaling-layer-separation.md]].

---
## Links
- Up: [[stages/stage-5-position-construction.md]]
- Related: [[concepts/sizing/vol-targeting.md]], [[concepts/sizing/leverage-cap.md]], [[concepts/sizing/china-sizing-stack.md]],
  [[concepts/sizing/scaling-layer-separation.md]]
