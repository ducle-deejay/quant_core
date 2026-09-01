---
doc_id: OBS-016
title: Volatility estimate annualization convention - sqrt(bars_per_day) is per-day scale, not per-year
type: observation
owner: research
status: resolved
version: 1.0
components: [5]
tags: [volatility, sizing, convention, quant-api, parity]
source: "UAT 2026-08-31: risk researcher found the vol_target default interacts with a per-day-scaled vol estimate, ~15.8x off true annualization; live orchestrator parity confirmed"
design: []
code: [src/quant_api/risk.py, src/trading/portfolio.py]
test: [src/quant_api/tests/test_risk.py]
---

# OBS-016 - Vol estimate annualization convention (sqrt(bars_per_day) scale)

## 1. Finding

`_rolling_vol` (quant_api.risk, mirroring `trading.portfolio._rolling_vol`)
scales the per-bar std by `sqrt(bars_per_day)` = sqrt(240) and labels the
result "annualized". That scale is PER-DAY vol, not per-year: real VN30F1M
1-minute std ~0.000654 gives vol_est ~0.01 vs a true annualized figure of
~0.16 (sqrt(240*250)). With the default `vol_target = 0.1` the target/estimate
ratio is therefore ~15.8x too large and the `max_contracts` cap binds almost
everywhere in offline portfolio backtests.

## 2. Verdict

Accepted as parity-preserving convention, documented, not code-changed:
`trading.portfolio` (live orchestrator) uses the same scale, so changing
`quant_api.risk` alone would break research/live parity. The label
"annualized" is inaccurate; the correct reading is "per-day vol scale";
the ratio `target_vol / vol_est` is what drives sizing, and `vol_target`
must be interpreted at the same per-day scale (~0.1 per-day target).
Calibration of the default to a true annualized semantics is deferred:
(1) it must change both sides (live + API) together, and (2) it needs live
fill data (milestone-1 cost parity) before any re-tuning.

## 3. Consequence

Docstrings in `quant_api.risk` and `trading.portfolio` should state the
per-day convention; the unit-contract question is tracked here for the
harness-version review (quarterly cadence).

## Related notes

- [DEC-017](DEC-017-quant-api-role-modules.md) - the quant_api contract
- [REC-008](REC-008-orthogonalization-pnl-input.md) - same UAT wave
