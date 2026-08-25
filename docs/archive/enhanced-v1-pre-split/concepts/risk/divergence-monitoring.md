---
doc_id: CON-RISK-DIVERGENCE
title: Divergence Monitoring
type: specification
owner: risk
status: approved
version: 1.1
components: [7]
tags: [risk, monitoring]
aliases: ["Live-versus-Backtest", "Implementation Shortfall"]
source: "original stage-7 layer 4 + bad morning timeline"
---

# Divergence Monitoring

## 1. Summary

Compare live behavior against spec-sheet expectations on statistically sound
gauges - never day-by-day PnL noise. Each deviation type maps to a different
action; that mapping separates professional monitoring from alarm spam.

## 2. Specification

2.1 Four standard gauges.

    gauge 1: rolling Information Coefficient vs spec sheet
             window at least a multiple of holding period
    gauge 2: implementation shortfall from fills vs Stage 1 cost model
             shortfall = (average fill price - mid at decision) x side
    gauge 3: position tracking error, average abs(current - target), vs design bound
    gauge 4: fill rate, reject rate, latency, feed gaps vs operational baseline

2.2 Worked reading. Spec IC about 0.05; live 0.008 for ten sessions gives a
warning. Combined with slippage at twice model, escalate: drawdown multiplier to
0.5, manual review within twenty-four hours. PnL shortfall alone proves nothing -
after sixty sessions a true-Sharpe-1.2 strategy carries dispersion about 1.5
percent, so a 0.85-standard-deviation miss is ordinary luck.

2.3 Bad-morning timeline (full chain runs without human input):

    09:31 heartbeat miss 2 seconds          -> logged, watched
    09:47 intraday loss minus 1.8 percent   -> drawdown multiplier to 0.75
    10:12 composite reverses, gap 6         -> Component 6 TWAP handles normally
    10:40 loss touches intraday kill line   -> FLATTEN everything, soft halt
    10:41 critical alert, acknowledge in 5 minutes else SMS and phone call
    11:00 post-mortem: slippage was 3x model after news spike
          -> registry event; afternoon cost buffer raised

2.4 Practitioner extras. Automated daily report decomposing PnL into alpha
component, execution slippage, and noise - measurement, not guessing. Alert
escalation ladder with acknowledgment requirements, the antidote to alert fatigue.
Findings routed to post-mortem and back into Stage 1 cost models.

Trap: metrics so noisy everyone learns to ignore them is worse than no monitor - it
trains humans to disable the immune system.

---
## Links
- Up: [[stages/stage-7-risk-overlay-monitoring.md]]
- Related: [[concepts/risk/defense-layers.md]], [[concepts/evaluation/spec-sheet-and-monitoring.md]], [[concepts/evaluation/post-mortem.md]]
