---
doc_id: CON-EX-URGENCY-ALGOS
title: Urgency and Execution Algorithms
type: specification
owner: research
status: approved
version: 1.1
components: [6]
tags: [execution, scheduling]
aliases: ["TWAP", "VWAP", "POV", "Urgency"]
source: "original stage-6 layers 1 to 3"
---

# Urgency and Execution Algorithms

## 1. Summary

One comparison sets execution speed - cost of waiting versus cost of acting. The
chosen urgency then selects a slicing pattern from five families. Intraday VN30F1M
needs only two of them initially.

## 2. Specification

2.1 Urgency comparison:

    cost of waiting = abs(gap) * alpha_decay_speed * value_of_1bp
    cost of acting  = half_spread + impact(gap relative to depth)
    gap               abs(target - current), contracts
    alpha_decay_speed expected edge decay per bar of delay (decay profile)
    value_of_1bp      PnL impact of one basis point of notional move
    half_spread       half the quoted spread, relative terms
    impact(...)       estimated self-impact for trading gap at once

Garleanu-Pedersen operational form: each period move only part of the way toward
target, speed inversely related to cost over signal strength.

2.2 Algorithm families.

    Immediate or marketable limit : cross spread now; small gaps, urgent signal
    TWAP                          : even slices over time; medium gap, averaging
    VWAP                          : historical volume profile slices; large gaps
    POV                           : track trade rate under X percent; large size
    Passive posting               : rest in queue, cancel and replace; earn half-spread

Worked micro-example: gap plus two contracts, spread 0.1 point about 0.008 percent
notional, ask depth fifteen contracts within a tick. Acting costs about 0.0008
percent of capital against waiting at about 0.002 percent per minute with z equal
1.2 and visible decay - verdict, marketable limit at the ask within seconds.

Counter-case: post-open flip from minus five to plus eight on thin books with two-
tick spreads - TWAP twelve minutes, participation capped at ten percent,
cancellation if the composite reverses midway.

2.3 Passive execution's hidden price. Queue risk plus adverse selection: passive
fills arrive precisely when price trades through the order, usually against you.
Backtest stance stays pessimistic - fills count only after price crosses an extra
tick - until live data proves otherwise.

2.4 Practitioner layer. Throttle and cooldown against target jitter; session
awareness (no passive orders across lunch break or into ATC; daily price bands);
slippage attribution per parent order feeding Component 1 cost models and Component
5 sizing buffers; multi-broker routing deferred until scale demands it but interface
designed for it.

---
## Links
- Up: [[stages/stage-6-trade-scheduling.md]]
- Related: [[concepts/execution/order-state-machine.md]], [[concepts/simulation/canonical-pnl.md]]
