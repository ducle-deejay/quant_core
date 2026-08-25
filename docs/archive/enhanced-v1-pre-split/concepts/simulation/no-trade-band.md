---
doc_id: CON-SIM-BAND
title: No-Trade Band
type: specification
owner: research
status: approved
version: 1.1
components: [1]
tags: [simulation, transaction-costs]
aliases: ["Hysteresis Band", "Band Selection"]
source: "discussion: band unit consistency; band initial selection"
---

# No-Trade Band

## 1. Summary

Act only when the distance between current target and current position exceeds
the band. This creates a dead-zone where tolerating small deviations is cheaper
than paying to correct them - the hysteresis solution to optimal trading under
transaction costs.

## 2. Specification

2.1 Rule. Trade only if abs(z(t) - p(t-1)) > band. Band 0.35 reads: signal must
move more than 0.35 standard deviations from current position before one round of
costs is worth paying.

2.2 Unit consistency. Valid because position is defined on the z axis (target =
clip(z)); p(t-1) is simply the clipped z from the last permitted trade. Any
nonlinear mapping g(z) forces the comparison through the same g. One space per
comparison, always.

2.3 Initial selection, three method levels.

Level one, heuristic start: measure the standard deviation of z displacement over
one signal halflife on train data; take roughly half as band. For Seed A:
correlation at lag 32 about 0.54 gives displacement std about 0.96, so band about
0.45 to 0.50, yielding roughly one trade per halflife.

Level two, grid sweep with plateau center (most common): sweep {0.2, 0.35, 0.5,
0.75, 1.0} on train data, plot net Sharpe, choose the plateau center - never the
peak, because peaks host overfitting. Freeze factory-wide.

Level three, theory sanity check: optimal-trading results (Whalley-Wilmott family)
give scaling laws - band grows with cost and short-term noise, shrinks with signal
persistence. Used to verify order of magnitude only.

2.4 Governance. One shared harness parameter, tuned once per timeframe, swept on
train only, recorded in the harness version. Periodically re-check that actual
trade cadence still matches signal halflife.

---
## Links
- Up: [[stages/stage-1-canonical-simulation.md]]
- Related: [[concepts/simulation/canonical-mapping.md]], [[concepts/simulation/harness-parameters.md]], [[concepts/simulation/canonical-pnl.md]]
