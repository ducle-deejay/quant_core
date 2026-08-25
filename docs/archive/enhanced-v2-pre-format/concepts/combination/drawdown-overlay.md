---
doc_id: CON-CB-DRAWDOWN-OVERLAY
title: Drawdown-Based De-Risking Overlay
type: specification
owner: risk
status: approved
version: 1.1
components: [4, 5]
tags: [combination, risk, drawdown]
aliases: ["De-Risking Multiplier", "Pre-Committed Rule Table"]
source: "follow-up discussions: drawdown overlay; pre-committed rule table meaning"
---

# Drawdown-Based De-Risking Overlay

## 1. Summary

Each sub-portfolio carries a multiplier m in the range zero to one that steps down
through a rule table frozen before going live as drawdown deepens, reaching zero at
the kill line. It acts on family-level risk budget, never on individual alpha
scores - separating belief in forecasts from investor pain control.

## 2. Specification

2.1 Standard table shape:

    drawdown from equity peak      multiplier m
    under 5 percent                1.00
    5 to 10 percent                0.75
    10 to 15 percent               0.50
    15 to 20 percent               0.25
    over 20 percent (kill line)    0.00 - shut down, formal review required

2.2 Pre-committed means: written, reviewed, version-controlled before live;
cannot be edited mid-drawdown. This is pre-registration - rules set while calm,
because during a drawdown every "one more week" argument sounds brilliant. If
renegotiation mid-drawdown is allowed, every threshold becomes negotiable and the
mechanism dies at that moment.

2.3 Implementation discipline. Constants in code; changes via logged change-review
cycle; anyone can read exactly what happens at each level. Discrete table over
smooth function: auditable, communicable to operations and investors, reproducible
in backtest to the tick.

2.4 Placement. p_final = p_vol_targeted * m - it multiplies family exposure, never
alpha scores. This overlay is why Chinese CTA products show unusually shallow
drawdowns relative to nominal Sharpe ratios: nonlinear insurance stacked on the
composite, owned by an independent risk team.

Distinct from per-alpha kill criteria in spec sheets: those retire individual
alphas; this de-risks whole running portfolios while leaving forecasts untouched.

---
## Links
- Up: [[stages/stage-4-combination.md]], [[stages/stage-5-position-construction.md]]
- Related: [[concepts/combination/china-two-layer-architecture.md]], [[concepts/risk/defense-layers.md]],
  [[concepts/sizing/china-sizing-stack.md]]
