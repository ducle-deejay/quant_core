---
doc_id: DEC-008
title: Live wiring architecture - contract-first, parallel workstreams, full risk overlay in the paper phase
type: decision
owner: research
status: resolved
version: 1.0
components: [5, 6, 7]
tags: [wiring, nautilus, architecture, milestone-1, risk-overlay, contracts]
source: "owner discussion 2026-08-30: achieve milestone 1 (multi-alpha paper portfolio on entrade demo) via parallel workstreams; risk overlay built to live standard from the start"
design: [STG-5-POSITION-CONSTRUCTION, STG-6-TRADE-SCHEDULING, STG-7-RISK-OVERLAY]
code: [src/trading/contracts.py, src/trading/portfolio.py, src/trading/strategies, src/trading/risk]
test: []
---

# DEC-008 - Live Wiring Architecture (contract-first, parallel, full risk in paper)

## 1. Decision

Milestone 1 (multi-alpha portfolio paper execution on the entrade demo) is built as three parallel workstreams joined by a single contract file `src/trading/contracts.py`:

- **Portfolio orchestration** (`src/trading/portfolio.py`) - pure `alpha_core` calls: per-bar scoring of the configured alpha expressions, canonical mapping, weighted combination, volatility targeting, and conversion to a signed target position in contracts. Implements the `Portfolio` protocol (`compute_target(bars, ts) -> TargetPosition`).
- **Bridge strategy** (`src/trading/strategies/bridge.py`) - the Nautilus `Strategy`: subscribes to 1-minute bars (DNSE data client), keeps a rolling buffer, calls `compute_target` every bar, gates the target through the risk controller, and submits/cancels orders (LO default, MAK on demand) through the entrade execution client. No alpha logic lives here.
- **Risk overlay** (`src/trading/risk/overlay.py`) - the Component 7 layer built to **live standard from the paper phase**: exposure caps (L_max from 5% entrade margin), intraday loss limit, flatten/cancel-all circuit breaker with retry, bar-staleness dead-man's switch, and ACTIVE/HALTED/REDUCING states. Implements the `RiskController` protocol (`gate(target)`, `status()`).

The paper runner (`apps/trading/paper.py`) composes the three into a `TradingNode` with the DNSE data client and the entrade demo execution client; end-to-end verification on the demo is the single sequential step.

## 2. Rationale

- The entrade demo environment behaves identically to live (the fee-verification data was exported from demo endpoints, OBS-010), so the risk overlay is built and tested at paper time; moving to live then requires no new risk code, only credential/environment changes.
- The spec-sheet contract (divergence gauges against research expectations) is deferred to a minimal acceptance table (paper fills vs cost model, per DEC-006) - full IC gauges wait until after milestone 1.
- Contract-first avoids interface drift between parallel workstreams; all contract types are Nautilus-free so each module is unit-testable in isolation.

## 3. Accepted gaps (recorded, not silent)

- The risk overlay runs inside the same TradingNode as the strategy for milestone 1 (separate component object, same process). Canon STG-7 5.1 requires a separate process; process separation is deferred to the live phase and is tracked here.
- Combination weights are static per paper run (research-side refit between runs); scheduled refits (Component 4 runtime mode) are later work.
- The vol-target contract mapping is `contracts = round(z / cap * L_max)` with `L_max = floor(capital * safety_factor / (margin_rate * price * 100,000))`, documented in the orchestration module.

## Related notes

- [DEC-006](DEC-006-milestone-1-fee-model.md) - milestone-1 fee model (cost_per_side constant)
- [OBS-009](OBS-009-entrade-fee-and-margin-schedule.md), [OBS-010](OBS-010-empirical-entrade-fee-verification.md) - entrade fee/margin basis
- [DEC-007](DEC-007-repo-layout-and-rename.md) - repo layout the wiring lands in
