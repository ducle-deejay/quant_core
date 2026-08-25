---
doc_id: CON-RISK-DEFENSE
title: Defense Layers and Circuit Breakers
type: specification
owner: risk
status: approved
version: 1.1
components: [7]
tags: [risk, kill-switch]
aliases: ["Circuit Breakers", "Dead Man's Switch"]
source: "original stage-7 content"
---

# Defense Layers and Circuit Breakers

## 1. Summary

Four defense layers ordered by depth - pre-trade checks, static caps, dynamic
circuit breakers, divergence monitoring - plus the dead man's switch. The risk
layer is independent of strategy by design and defaults to worst case on silence.

## 2. Specification

2.1 Layer 1, pre-trade checks. Per order, at the OMS: margin, fat-finger price and
size, duplicates, position limits, exchange rate-limit headroom. Cheapest layer,
blocks the most.

2.2 Layer 2, exposure caps. Static ceilings hard-coded inside the risk process, not
referenceable from strategy configuration - the physical embodiment of L_max.

2.3 Layer 3, drawdown circuit breakers, three distinct levels:

    soft halt : no new positions, still manage existing ones   <- suspicion
    flatten   : close all positions in the market              <- lost control
    shutdown  : disconnect and lock the system                 <- last resort

Automatic triggers: intraday loss limit derived from volatility target (0.95
percent daily means three standard deviations about 2.9 percent of capital, 14.5
million VND on 500 million, kill line nearby); total drawdown past the rule table
kill line; severe divergence per the monitoring note.

2.4 Dead man's switch. Strategy heartbeat silent longer than X seconds defaults to
worst case - soft halt or flatten, never "hope it returns". Paired with a stale-
feed detector: frozen price data is itself an emergency, because a blind strategy
still sending orders is the worst available scenario.

2.5 Organizational principle. Risk process separate from strategy - different
process, codebase, owner. Chinese risk-control teams can switch alphas off, never
the reverse. A guardian switchable by its patient is not a guardian.

2.6 Practitioner extras. Pre-committed runbooks per failure scenario written while
calm; scheduled chaos drills - a kill switch never rehearsed has never worked;
immutable logging of manual interventions.

Traps: shared process with strategy; reliance on broker-side protection (margin
calls are slow - your own system is the only fast responder); ownerless alerts;
unlogged interventions.

---
## Links
- Up: [[stages/stage-7-risk-overlay-monitoring.md]]
- Related: [[concepts/risk/divergence-monitoring.md]], [[concepts/combination/drawdown-overlay.md]], [[concepts/sizing/leverage-cap.md]]
