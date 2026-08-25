---
doc_id: STG-7-RISK-OVERLAY
title: Component 7 - Risk Overlay and Monitoring
type: specification
owner: risk
status: approved
version: 2.0
components: [7]
tags: [risk, monitoring, stage-hub]
source: "docs/original/pipeline_stages/07_risk_overlay_monitoring.md (no follow-up Q&A occurred). Reformatted per REF-STYLE."
---

# 7. Risk Overlay and Monitoring

## 1. Component contract

    INPUT : real-time position/exposure, PnL stream, order telemetry (Stage 6),
            infrastructure and feed state,
            spec-sheet expectations (backtest benchmarks)
    OUTPUT: interventions (block orders, reduce multipliers, flatten),
            alerts to humans on an escalation ladder

## 2. Summary

Component 7 is the immune system, designed under the assumption that everything
above it will eventually fail - bad data, bugs, dead alphas, exchange outages,
human error. Earlier components make money; this one guarantees that no failure
above can kill the account. Principle number one: the risk layer is independent
of the strategy layer - different process, different codebase, ideally different
owners. At Chinese firms the risk-control team is organizationally separate from
alpha and may switch alphas off, never the reverse.

## 3. Specification

3.1 Layer 1, pre-trade checks. Per order, installed at the OMS but owned by
risk: margin sufficiency, fat-finger price and size, duplicate detection,
position limits, exchange rate-limit headroom. Cheapest layer, blocks the most.

3.2 Layer 2, exposure caps. Static ceilings hard-coded inside the risk process,
not referenceable from strategy configuration. Physical embodiment of L_max from
Component 5 ([[concepts/sizing/leverage-cap.md]]).

3.3 Layer 3, drawdown circuit breakers. Three distinct levels, never conflated:

    soft halt : no new positions, still manage existing ones   <- suspicion
    flatten   : close all positions in the market              <- lost control
    shutdown  : disconnect and lock the system                 <- last resort

Automatic triggers: intraday loss limit derived from the volatility target (at
0.95 percent daily, three standard deviations is about 2.9 percent of capital,
14.5 million VND on 500 million, kill line nearby); total drawdown past the rule
table's kill line; severe divergence per 3.4.

3.4 Layer 4, live-versus-backtest divergence monitoring. Compare on statistically
sound gauges, never day-by-day PnL noise:

    gauge 1: rolling Information Coefficient vs spec sheet
             (window at least a multiple of holding period)
    gauge 2: implementation shortfall measured from fills vs Stage 1 cost model
             shortfall = (average fill price - mid at decision) x side
    gauge 3: position tracking error, average abs(current - target), vs design bound
    gauge 4: fill rate, reject rate, latency, feed gaps vs operational baseline

Worked reading: spec IC about 0.05, live 0.008 for ten sessions gives a warning;
combined with slippage at twice model gives escalation - drawdown multiplier to
0.5, manual review within twenty-four hours. Each deviation type maps to a
different action; that mapping separates professional monitoring from alarm spam.

3.5 Dead man's switch and stale-feed detector. Strategy heartbeat silent longer
than X seconds means default to worst case (soft halt or flatten), never "hope it
returns". Price data frozen too long is itself an emergency: a blind strategy
still sending orders is the worst scenario available.

## 4. Worked example - one bad morning

    09:31 feed heartbeat miss (2 seconds)      -> logged, watched
    09:47 intraday loss minus 1.8 percent      -> m_drawdown auto-lowered to 0.75
    10:12 composite reverses, gap 6 contracts  -> Component 6 TWAP handles normally
    10:40 loss touches intraday kill line      -> FLATTEN everything, soft halt
    10:41 critical alert -> acknowledge within 5 minutes, else SMS + phone call
    11:00 post-mortem: slippage since 09:47 was 3x model after a news spike
         -> registry event logged; afternoon cost buffer raised

The chain runs without human input; humans are informed so they can decide what
comes next.

## 5. Failure modes

5.1 Risk code in the same process as strategy - a strategy crash takes its
guardian down exactly when needed most.
5.2 Divergence metrics so noisy that everyone learns to ignore them - worse than
no monitor, because it trains humans to disable the immune system.
5.3 Relying on broker-side protection - margin calls are slow; the only fast
responder for your account is your own system.
5.4 Ownerless alerts flying into a twenty-person channel.
5.5 Manual interventions without immutable logging - post-mortems learn nothing.

## 6. The loop closes

Feedback edges turn the pipeline into a living cycle: fills recalibrate cost
models in Component 1; divergence triggers spec-sheet kill criteria in Component
2; every failure is logged as trials into the registry; post-mortem findings
become new gates for the next mining generation. Operating cadence: per bar for
Components 5, 6 and watchful 7; daily PnL decomposition report; weekly slippage
review; monthly pool health; quarterly risk budgets and harness version review.

One-sentence summary of the whole system: Components 0 to 4 decide whether you
have an edge, 5 and 6 decide how much survives costs, 7 decides whether you stay
alive to collect it.

---
## Related notes
- [[stages/stage-6-trade-scheduling.md]]
- [[concepts/risk/defense-layers.md]] - layer mechanics and circuit-breaker detail
- [[concepts/risk/divergence-monitoring.md]] - gauges and the bad-morning timeline
- [[framework-lifecycle.md]] - feedback edges and operating cadence in full
