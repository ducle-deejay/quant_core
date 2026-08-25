---
doc_id: CON-SZ-LEVERAGE-CAP
title: Leverage Cap and L Max Derivation
type: specification
owner: research
status: approved
version: 1.1
components: [5]
tags: [sizing, risk, leverage]
aliases: ["Leverage Cap", "L Max"]
source: "follow-up discussion: policy cap vs physical conversion; L max derivation"
---

# Leverage Cap and L Max

## 1. Summary

L is a policy number in multiples-of-capital units chosen by risk management.
L_max is derived as the minimum of physical constraints less a safety factor. Policy
sits above conversion; the contracts formula merely translates it.

## 2. Specification

2.1 Two layers, previously conflated under one symbol. Policy layer:
p(t) = clip(p(t), -L, +L) - for example "never hold more than three times capital".
Physical conversion layer:

    max_contracts = capital * L / (price x multiplier 100000 x margin_rate)
    capital      account capital, currency units
    price        current futures price, index points
    multiplier   contract multiplier (100000 VND per index point)
    margin_rate  broker margin requirement as a fraction (e.g., 0.18)

2.2 Deriving L_max - take the minimum of three constraints:

    margin constraint    = usable_margin_fraction / margin_rate
                           example: 0.60 usable, rate 18 percent -> 3.3
    overnight gap stress = tolerated_loss / worst_historical_gap
                           example: 7.5 percent tolerated, 2.5 percent worst -> 3.0
    regulatory limit     = exchange contract limit converted to multiples of capital
    usable_margin_fraction   share of capital allowed as margin
    tolerated_loss           max overnight loss accepted, fraction of capital
    worst_historical_gap     largest adverse overnight gap observed

then choose L below L_max with an additional twenty-to-thirty percent safety
margin. L is never arbitrary - it is the minimum of material constraints less h
buffer.

2.3 Enforcement location matters: caps live hard-coded inside the Component 7 risk
process, not referenceable from strategy configuration.

---
## Links
- Up: [[stages/stage-5-position-construction.md]]
- Related: [[concepts/sizing/vol-targeting.md]], [[concepts/sizing/scaling-layer-separation.md]], [[concepts/risk/defense-layers.md]]
