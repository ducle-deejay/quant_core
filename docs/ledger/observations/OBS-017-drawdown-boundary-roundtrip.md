---
doc_id: OBS-017
title: Drawdown ladder exact-boundary round-trip - kill line missed at exactly 20%
type: observation
owner: research
status: resolved
version: 1.0
components: [5]
tags: [drawdown, ladder, boundary, quant-api, binding]
source: "practitioner review 2026-09-01: drawdown_multiplier_py([0.20]) returned 0.25 - the kill line did not fire at exactly 20% (canon CON-CB-DRAWDOWN-OVERLAY requires reproducibility to the tick)"
design: []
code: [src/alpha-core/src/strategies/sizing/drawdown_overlay.rs, src/alpha-core/src/python_bindings/portfolio.rs]
test: [src/alpha-core/src/strategies/sizing/drawdown_overlay.rs, src/quant_api/tests/test_risk.py]
---

# OBS-017 - Drawdown ladder exact-boundary round-trip

## 1. Finding

`alpha_core.drawdown_multiplier_py([0.10])` returned 0.75 (the table's
10-15% band requires 0.50) and `[0.20]` returned 0.25 (kill line requires
0.00). The ladder is equity-based with a "band above" convention (exact
threshold rolls to the next band, verified by its own Rust tests using
exact IEEE divisions like 90.0/100.0). The Python binding feeds equity =
`1.0 - drawdown`; the round-trip is inexact (0.10 -> 0.0999..., 0.20 ->
0.1999...), so an exact boundary input landed epsilon below the threshold
and rolled to the WRONG (lower) band.

## 2. Verdict

Fixed in the engine: `raw_drawdown` now snaps the computed drawdown to 12
decimals, which is identity away from boundaries and lands exact decimal
inputs exactly on their thresholds. Verified: 0.05 -> 0.75, 0.10 -> 0.50,
0.15 -> 0.25, 0.20 -> 0.00 (kill fires). Rust suite (226 tests) green;
boundary regression tests added on the Python side (test_risk.py
test_drawdown_boundary_exact).

## 3. Consequence

The overlay is again reproducible to the tick at every frozen band
boundary. No other caller of the ladder is affected away from boundaries.

## Related notes

- [OBS-016](OBS-016-vol-estimate-annualization-convention.md) - vol scale
  convention from the same review wave
- [REC-009](REC-009-combination-standardized-scores.md) - combination
  standardization from the same review wave
