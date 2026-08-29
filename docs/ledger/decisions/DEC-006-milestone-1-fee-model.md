---
doc_id: DEC-006
title: Milestone-1 fee model keeps scalar cost_per_side at a reference price; two-part price-dependent model deferred
type: decision
owner: research
status: resolved
version: 1.0
components: [1, 5]
tags: [cost-model, entrade, calibration, milestone-1, nautilus-wiring]
source: "owner discussion 2026-08-30: milestone-1 simplicity over exact price dependence; re-calibrate after wiring"
design: [STG-1-CANONICAL-SIM, CON-SIM-CANONICAL-PNL]
code: [crates/alpha-core/src/harness_config.rs, crates/alpha-core/src/canonical/pnl.rs]
test: []
---

# DEC-006 - Milestone-1 Fee Model (scalar at reference price)

## 1. Decision

For milestone 1 (paper execution on the entrade demo), the harness keeps the existing scalar cost model - no code change:

```text
cost_per_side = fee + half_spread + buffer
```

with the entrade fee schedule (OBS-009, OBS-010) converted to basis points at a fixed reference price of 1,500 index points:

| Component | VND per side per contract | bp at reference price 1,500 |
|---|---|---|
| Fee - fixed part (trading + platform + exchange + VSDC clearing) | 15,750 | 1.050 |
| Fee - partnership (price-proportional, 0.045% x 18% of notional, measured 8.22015/point round trip) | 4.1101 x P | 0.411 (constant in bp) |
| **Fee total** | 15,750 + 4.1101 x P | **1.461** |
| Half-spread (canon assumption: 0.05 point = half tick) | 5,000 | 0.333 |
| Buffer (slippage and unmodeled frictions; researcher input) | - | 0.5 |
| **cost_per_side** | - | **2.294 bp = 0.000229** |

## 2. Rationale

- The price-proportional partnership fee (4.1101 x P VND) is constant in relative terms (0.411 bp) and therefore fits the scalar model exactly; no price dependence is lost by folding it into `fee`.
- The fixed-VND components (15,750 fee + 5,000 half-spread) vary in bp with price; a single reference price is chosen for milestone 1. Reference price 1,500 is slightly below the recent trading range (1,700-1,950), so the resulting bp values are slightly conservative (costs are overstated, never understated - the safe direction for screening).
- A sub-tick buffer (0.5 bp = 0.075 points = 0.75 tick at 1,500) is valid as an expected value over many fills; it is accepted as the initial researcher-supplied value and will be calibrated downward from paper/live fills per the canon rule ("calibrated from live fills, never guessed upward").
- Milestone 1 uses MAK order crossing (fill at the spread), so buffer mainly covers decision-to-fill drift on 1-minute bars; the half-spread assumption (0.05 point) remains unmeasured and is flagged for measurement from order-book depth data.

## 3. Accepted limitations (deferred, not forgotten)

- The fixed-VND components are approximated at reference price 1,500; at prices far from 1,500 the error grows (e.g. at 1,200 the true fee is 1.72 bp vs modeled 1.46 bp; at 2,100 true 1.16 bp vs 1.46 bp). Conservative direction holds at prices above 1,500.
- The two-part price-dependent cost model (fixed_vnd_per_side + price_proportional with per-bar price P(t), `cost(P) = 0.1575/P + 0.0000411`) is deferred until after the Nautilus wiring phase; it will be implemented as a reconciliation note (REC) touching STG-1-CANONICAL-SIM.
- The half-spread of 0.05 point is a canon assumption, not yet measured; depth-10 order-book data is available in the nox catalog and measurement is planned before freezing milestone-1 constants.
- The 5% partnership tax on gross PnL (signed; credit on losses observed in demo data) is excluded from cost_per_side by design - it is accounted at the accounting layer.

## Related notes

- [OBS-009](OBS-009-entrade-fee-and-margin-schedule.md) - published entrade fee/margin schedule
- [OBS-010](OBS-010-empirical-entrade-fee-verification.md) - empirical verification (measured 8.22015/point partnership rate, 5% margin, 5% gross-PnL tax)
- Future REC note for the two-part cost model after wiring
