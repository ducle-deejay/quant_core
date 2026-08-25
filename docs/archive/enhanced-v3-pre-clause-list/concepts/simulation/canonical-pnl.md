---
doc_id: CON-SIM-CANONICAL-PNL
title: Canonical PnL and Turnover
type: specification
owner: research
status: approved
version: 1.1
components: [1]
tags: [simulation, pnl, turnover]
aliases: ["Canonical PnL", "Turnover Formula"]
source: "follow-up discussions: delta-p as order quantity; fee/half-spread/buffer; annual turnover"
---

# Canonical PnL and Turnover

## 1. Summary

One identity defines simulation PnL exactly for continuous positions under flat costs. It encodes anti-lookahead, order sizing, and turnover accounting in a single line, which is what makes Component 1 fully vectorizable.

## 2. Specification

2.1 The identity:

```text
    pnl(t) = p(t-1) * r(t) - c * abs(p(t) - p(t-1))
```


2.2 Term meanings. r(t) is asset return over bar t. p(t-1) was decided at end of bar t-1 from data no newer than t-1 - that placement is the anti-lookahead mechanism. The change p(t) - p(t-1) is, by accounting identity, exactly the order size needed to move holdings (holding 1.2, target 1.8 means an order of 0.6); order-book mechanics are delegated to Component 6. Absolute value appears because fees are direction-blind: buying five then selling five sums to zero signed but pays on ten. c is cost per unit notional per side: fee plus half-spread plus buffer.

2.3 Cost units for VN30F1M. Spread quoted in points converts to notional fraction: 0.05-point half-spread over mid about 1200 points is roughly 0.42 basis points per side; in cash 5,000 VND per contract per side; broker fees run 500 to 2,000 VND, giving c around half a basis point per side.

2.4 Buffer definition. Deliberate pessimism above measurable costs covering slippage beyond quote, impact on thin depth, partial fills, and decision-to-fill drift. Calibrated downward from live measurement (decision price versus fill price), never guessed upward.

2.5 Turnover. Annual turnover = sum of abs(position changes) divided by days, times 250, expressed in multiples of capital per year. Positions live in capital multiples, so research needs no capital input. Deployment converts back: contracts = p * capital / (price x multiplier).

---
## Links
- Up: [[stages/stage-1-canonical-simulation.md]]
- Related: [[concepts/simulation/canonical-mapping.md]], [[concepts/simulation/no-trade-band.md]], [[concepts/simulation/harness-parameters.md]]
