---
doc_id: CON-SIM-HARNESS-PARAMS
title: Harness Parameters
type: specification
owner: research
status: approved
version: 1.1
components: [1]
tags: [simulation, parameters, governance]
aliases: ["EWMA Span Selection", "Z-Window Selection"]
source: "follow-up discussion: who owns window parameters and how they are chosen"
---

# Harness Parameters

## 1. Summary

EWMA span, rolling z-window, band, caps, and cost c are factory-wide assets -
tuned once per timeframe on train data, frozen as a harness version, never
per-alpha. Per-alpha preprocessing kills comparability and smuggles selection bias
in through preprocessing itself.

## 2. Specification

2.1 Three parameter layers. Alpha params (per candidate, judged at Stage 2
plateau); harness params (shared, calibrated before mining runs); infrastructure
constants (bar timeframe, session calendar).

2.2 EWMA span defines the strategy slot: far larger than one bar so filtering
works, far smaller than the shortest acceptable holding period so fast alphas do
not drown in lag. Rule: span equals five to fifteen percent of that minimum
holding period (demo: eight bars for a thirty-minute slot). Fine-tune by grid {4,
8, 16, 32} judged on pool-aggregate net Sharpe across a diverse seed sample -
never one alpha's Sharpe - choosing the knee of the turnover-versus-lag curve.

2.3 Rolling z-window balances two constraints. Long enough for stable mean and
std estimates over autocorrelated series (cover several cycles of the slowest
accepted alpha; 480 bars is about 1.7 days), short enough to exclude dead regimes.
Intraday scores carry strong time-of-day seasonality: either accept a longer
averaging window or seasonally adjust against same-time-of-day history.

2.4 Coupling and versioning. Span, window, and band jointly control the
turnover-lag balance. Order of operations: fix cost model first; choose z-window
from statistical and seasonal constraints; sweep span and band jointly; select
plateau; freeze as a harness version. Changing version later forces re-running the
entire registry. New timescale families get additional profiles (fast, medium,
slow), never a retuned shared harness.

---
## Links
- Up: [[stages/stage-1-canonical-simulation.md]]
- Related: [[concepts/simulation/canonical-mapping.md]], [[concepts/simulation/no-trade-band.md]], [[concepts/simulation/canonical-pnl.md]]
