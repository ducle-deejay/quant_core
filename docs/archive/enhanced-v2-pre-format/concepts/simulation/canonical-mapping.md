---
doc_id: CON-SIM-MAPPING
title: Canonical Mapping
type: specification
owner: research
status: approved
version: 1.1
components: [1]
tags: [simulation]
aliases: ["EWMA Smoothing", "Rolling Z-Score"]
source: "follow-up discussion: step-by-step mapping walkthrough"
---

# Canonical Mapping

## 1. Summary

Four transforms turn a raw score into a comparable position signal. Each fixes
exactly one problem: noise, scale, cost, fat tails.

## 2. Specification

2.1 Step A, EWMA smoothing. s_smooth(t) = lambda_s * score(t) + (1 - lambda_s) *
s_smooth(t-1). Low-pass filter. Trades a few bars of decision lag for much lower
turnover; without it the position chases every tick.

2.2 Step B, rolling z-score. z(t) = (smoothed - rolling mean) / rolling std over
a trailing window. Puts every alpha in standard-deviation-from-own-history units:
cross-alpha comparability plus regime self-adaptation. z = 0 means no information;
linearity preserves confidence ordering.

2.3 Step C, no-trade band. See [[concepts/simulation/no-trade-band.md]] - hysteresis against costs.

2.4 Step D, cap. clip(z, -L, +L). One freak bar must not decide a month; also
margin and position-limit reality.

2.5 Worked thread. Score 37.5 -> smoothed 31.2 -> z = 1.8 -> holding p = 1.2 ->
gap 0.6 exceeds band -> trade to p = 1.8 -> within cap, keep 1.8.

2.6 Production variants. Smoothing: ts_decay_linear (linear weights), Kalman at
forecast level. Normalization: rolling rank or percentile for fat tails;
winsorization before z; dividing by realized return volatility. Caps: soft tanh
squash; multiplying by target-over-realized volatility to fold sizing in
(Component 5). Defaults win because they are causal, vectorizable, few-parameter,
auditable.

2.7 Unit-consistency rule. Target is defined on the z axis (target = clip(z)),
which is why comparing z(t) with p(t-1) is valid; any nonlinear mapping g(z)
forces the band comparison through the same g. One space per comparison.

---
## Links
- Up: [[stages/stage-1-canonical-simulation.md]]
- Related: [[concepts/simulation/no-trade-band.md]], [[concepts/simulation/harness-parameters.md]], [[concepts/sizing/vol-targeting.md]]
