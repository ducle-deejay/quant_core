---
doc_id: STG-6-TRADE-SCHEDULING
title: Component 6 - Trade Scheduling
type: specification
owner: research
status: approved
version: 2.0
components: [6]
tags: [execution, stage-hub]
source: "docs/original/pipeline_stages/06_trade_scheduling.md (no follow-up Q&A occurred). Reformatted per REF-STYLE."
---

# 6. Trade Scheduling

## 1. Component contract

```text
    INPUT : target_position(t) from Component 5
            current_position(t) from the reconciled ledger
            order book state (depth, spread), cost model
    OUTPUT: stream of child orders - side, price, size, send time
            plus full telemetry (every event, fill, measured slippage)
```


## 2. Summary

Component 6 is where the system touches the real market. Everything upstream produces one sentence - what exposure should be. This component answers how to get there at the cheapest price, balancing three simultaneous costs: explicit cost (fees plus spread when crossing), impact cost (your own order pushing price against you on a thin book), and the risk of waiting (alpha decay and drift while slicing). It is the only layer where a single buggy line loses money in the present moment rather than through a backtest.

## 3. Specification

3.1 Urgency decision. One comparison sets speed:

```text
    cost of waiting = abs(gap) * alpha_decay_speed * value_of_1bp
    cost of acting  = half_spread + impact(gap relative to depth)
    gap               abs(target - current), contracts
    alpha_decay_speed expected edge decay per bar of delay (decay profile)
    value_of_1bp      PnL impact of one basis point of notional move
    half_spread       half the quoted spread, relative terms
    impact(...)       estimated self-impact for trading gap at once
```


Strong signal or fast decay means act now; weak signal or gap far beyond depth means slice. This is the Garleanu-Pedersen result operationally: each period move only part of the way toward target, with speed inversely related to cost-over-signal-strength.

3.2 Execution algorithm families.

```text
    Immediate / marketable limit : cross the spread now; small gaps, urgent signal
    TWAP                          : even slices over time; medium gap, averaging
    VWAP                          : historical volume profile slices; large gaps
    POV                           : track trade rate, stay under X percent; large size
    Passive posting               : rest in queue, cancel/replace; earn half-spread
```


For intraday VN30F1M most days need only marketable limit and TWAP over minutes. Do not build the full collection before data demands it.

3.3 Passive execution discipline. Limit orders save the half-spread but carry queue risk and adverse selection - passive fills arrive precisely when price trades through them, usually against you. Backtest stance stays pessimistic: fills count only when price crosses an extra tick, until live data proves otherwise.

3.4 Order state machine and reconciliation.

```text
    NEW -> SENT -> ACKED -> PARTIALLY_FILLED -> FILLED
                       -> CANCELLED / REJECTED / TIMEOUT
```


Three survival laws. Current position updates only from broker-confirmed fills, never from expectations. Every submission is idempotent - network retries must never duplicate orders. Periodic ledger-versus-broker reconciliation treats any mismatch as a red alert.

3.5 Operational additions. Throttle and cooldown: act only when the gap exceeds threshold AND a cooldown elapsed since last submission, killing turnover caused by target jitter. Pre-trade checks at the OMS: margin, fat-finger price and size, duplicates, session boundary. Session awareness: no passive orders hanging across lunch break or into ATC; daily price bands make off-band orders meaningless. Slippage attribution loop: per parent order measure implementation shortfall = (average fill minus mid at decision) times side, decomposed by session hour, volatility regime, and size - reviewed weekly, results pumped back into Component 1 cost models and Component 5 sizing buffers.

## 4. Worked example

Target moves from +3 to +5 contracts:

```text
    gap = +2 contracts; spread 0.1 point (about 0.008 percent notional)
    ask-side depth 15 contracts within one tick
    cost of acting  = 2 x half_spread, about 0.0008 percent of capital
    cost of waiting = about 0.002 percent per minute at z = 1.2 with visible decay
    verdict: marketable limit at the ask, filled within seconds
```


Opposite case: post-open flip from minus five to plus eight (gap thirteen contracts) on thin depth with two-tick spreads - TWAP over twelve minutes with POV capped at ten percent, cancellation if the composite reverses midway.

## 5. Failure modes

5.1 Strategy seeing unconfirmed fills - deciding on imagined positions until drift becomes explosion. 5.2 Ignoring own impact on thin books - flat-cost backtests never show it. 5.3 Sending orders in toxic windows - first seconds after open and minutes before lunch have the widest spreads and strongest adverse selection. 5.4 Non-idempotent retries - a three-second network drop returns as duplicate orders. 5.5 Chasing every recomputed target - fee death by jitter; throttling is mandatory medicine.

One-sentence summary: this component does not make you rich - it decides how much you pay for becoming rich through earlier components; in intraday trading that payment is exactly the border between positive and negative Sharpe.

---
## Related notes
- [[stages/stage-5-position-construction.md]], [[stages/stage-7-risk-overlay-monitoring.md]]
- [[concepts/execution/urgency-and-execution-algorithms.md]] - urgency math and algorithm families
- [[concepts/execution/order-state-machine.md]] - states, survival laws, OMS boundary checks
