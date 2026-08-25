---
doc_id: OBS-003
title: trades_per_day counted band triggers instead of executed changes
type: observation
owner: research
status: resolved
version: 1.0
components: [1]
tags: [simulation, metrics, hysteresis]
source: "system audit invariant sweep; 459 of 500 alphas violated the trade-count consistency check"
design: [STG-1-CANONICAL-SIM]
code: [crates/alpha-core/src/canonical/mapping.rs]
test: [trades_per_day_counts_actual_trades_not_bars]
---

# OBS-003 - trades_per_day Counted Band Triggers Instead of Executed Changes

## 1. Summary

The canonical loop incremented its trade counter on every bar where the previous z left the dead-zone around the current position. While the position sat exactly at the cap, an out-of-band z re-triggered that condition every bar while the clamped target equalled the current position, producing a zero-size order each time. The counter recorded those phantom triggers as trades.

## 2. Finding

The system-audit invariant sweep flagged 459 of 500 alphas: reported `trades_per_day` exceeded actual position changes divided by bars per day. Every alpha that traded at all eventually rode the cap and inflated the metric without bound.

Economically the phantom triggers were harmless - zero-size orders incur no cost in the PnL identity - but the telemetry lied, and Component 6 scheduling plus any turnover analysis downstream would have consumed a number with no physical meaning.

## 3. Consequence and resolution

The counter now increments only when the absolute position change exceeds machine epsilon, matching the definition used everywhere else. The invariant sweep reports zero violations across the full 500-alpha battery.

## Related notes

- [STG-1-CANONICAL-SIM](../../enhanced/stages/stage-1-canonical-simulation.md) - frozen specification of realized turnover reporting
