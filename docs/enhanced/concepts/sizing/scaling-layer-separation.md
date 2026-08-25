---
doc_id: CON-SZ-SCALING-LAYERS
title: Scaling-Layer Separation
type: specification
owner: research
status: approved
version: 1.1
components: [1, 4, 5]
tags: [sizing, architecture]
aliases: ["Alpha-Level vs Portfolio-Level Scaling", "Exposure Semantics", "Sizing Is Risk Management"]
source: "follow-up discussions: two scaling layers; exposure terminology; sizing as risk management"
---

# Scaling-Layer Separation

## 1. Summary

Position sizing happens once, at portfolio level. Alpha-level normalization in the harness is unit standardization for comparability, not sizing. Confusing the two produces systems where nobody knows which knob controls risk.

## 2. Terminology chain

Alpha set = alpha pool. Weighted sum = composite score or forecast. Converted number = target position. Collection across instruments = portfolio. Forecasts are dimensionless; money appears only when Stage 5 converts forecast into exposure. Position sizing is that conversion and lives at portfolio level only.

## 3. The two layers and their single jobs

Layer one, alpha-level normalization inside the Stage 1 harness: standardizes units so alphas are comparable - grading every exam onto one zero-to-hundred scale. No money involved; fixed-notional simulation only.

Layer two, portfolio-level vol targeting in Stage 5: converts dimensionless forecast into real exposure against capital. The only true sizing.

Both legitimately coexist because they solve different problems. Failure mode: volatility scaling stacked three layers deep - then no single knob controls risk and effective leverage goes undeclared.

## 4. Exposure semantics

Notional exposure equals p times capital. Risk exposure equals p times capital times estimated volatility. Equal notionals carry unequal risks across assets - hence sizing keys on volatility, managing the second quantity through the first.

## 5. Sizing is risk management itself

Loss equals position times adverse move. The adverse move is uncontrollable; position is the only factor under your hand. Defense ordering: position sizing (proactive, continuous), limits and caps (static bounds), kill switch and de-risking overlay (reactive), diversification (structural). Good risk management means never having bet large enough for a bad stretch to be lethal.

---
## Links
- Up: [stage-1-canonical-simulation](../../stages/stage-1-canonical-simulation.md), [stage-4-combination](../../stages/stage-4-combination.md), [stage-5-position-construction](../../stages/stage-5-position-construction.md)
- Related: [canonical-pnl](../simulation/canonical-pnl.md), [vol-targeting](vol-targeting.md), [position-sizing-methods](position-sizing-methods.md)
