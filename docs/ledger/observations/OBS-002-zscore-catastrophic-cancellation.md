---
doc_id: OBS-002
title: Unanchored variance lost precision under large score offsets
type: observation
owner: research
status: resolved
version: 1.0
components: [1]
tags: [simulation, numerical-stability, floating-point]
source: "metamorphic shift-invariance test written during the audit build; failed at first computed bar"
design: [STG-1-CANONICAL-SIM]
code: [crates/alpha-core/src/canonical/mapping.rs]
test: [metamorphic_shift_invariance]
---

# OBS-002 - Unanchored Variance Lost Precision Under Large Score Offsets

## 1. Summary

The rolling z-score computed variance as `E[x^2] - (E[x])^2` on raw values. For any score riding on a large offset - the metamorphic test used a constant near 12345; real candidates can sit near price scale in the hundreds or thousands - the two terms nearly cancel while each carries full-magnitude rounding noise. The derived standard deviation was garbage relative to the true fluctuation scale.

## 2. Finding

The failure appeared the moment the shift-invariance metamorphic test ran: adding a constant to every score must not change positions, yet positions diverged at the very first computed z-score bar. The magnitude of the deviation matched catastrophic cancellation of two terms around 1.5e8 whose true difference is below 20.

This observation matters beyond the test: an alpha whose score hovers far from zero with small fluctuations would have received silently wrong normalisation on real data, with no crash and no NaN to announce it.

## 3. Consequence and resolution

The accumulators are now anchored at `smoothed[0]`: all running sums operate on centred values `x - anchor`, keeping both terms at fluctuation scale. The anchored form makes shift invariance hold to floating-point exactness and removes the cancellation class entirely. The differential check against the naive two-pass reference confirms agreement within 2.91e-9 worst-case relative deviation over 472k bars.

## Related notes

- [STG-1-CANONICAL-SIM](../../enhanced/stages/stage-1-canonical-simulation.md) - frozen specification of Step B rolling z-score
