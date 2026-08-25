---
doc_id: CON-EX-STATE-MACHINE
title: Order State Machine and Reconciliation
type: specification
owner: research
status: approved
version: 1.1
components: [6]
tags: [execution, oms]
aliases: ["Reconciliation", "Idempotency"]
source: "original stage-6 layer 4"
---

# Order State Machine and Reconciliation

## 1. Summary

The unglamorous layer where desks kill themselves with bugs. Three survival laws: positions update only from confirmed fills; every submission is idempotent; periodic ledger-versus-broker reconciliation treats mismatch as a red alert.

## 2. Specification

2.1 State machine:

```text
    NEW -> SENT -> ACKED -> PARTIALLY_FILLED -> FILLED
                       -> CANCELLED / REJECTED / TIMEOUT
```

2.2 Survival law one. Current position updates only from broker-confirmed fills, never from expectations - a strategy deciding on imagined positions drifts until it explodes.

2.3 Survival law two. Every order submission is idempotent: a three-second network drop must not return as duplicate orders of the same size. Client order identifiers plus deduplication on retry.

2.4 Survival law three. Periodic reconciliation of internal ledger against broker-reported position; mismatch is a red alert requiring investigation, never something to wait out.

2.5 Supporting OMS boundary checks: margin sufficiency, fat-finger price and size, duplicate detection, session boundary - bad orders blocked before leaving home. Slippage telemetry per parent order flows back to cost models and sizing buffers.

Why this layer matters more than it looks: it is the only stage where bugs lose money in the present moment rather than through backtests, and its failure modes - phantom positions, duplicated orders - corrupt every upstream decision simultaneously.

---
## Links
- Up: [stage-6-trade-scheduling](../../stages/stage-6-trade-scheduling.md)
- Related: [urgency-and-execution-algorithms](urgency-and-execution-algorithms.md), [defense-layers](../risk/defense-layers.md)
