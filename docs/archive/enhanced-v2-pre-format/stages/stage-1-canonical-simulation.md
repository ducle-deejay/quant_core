---
doc_id: STG-1-CANONICAL-SIM
title: Component 1 - Canonical Simulation
type: specification
owner: research
status: approved
version: 2.0
components: [1]
tags: [simulation, stage-hub]
source: "docs/original/pipeline_stages/01_canonical_simulation.md + follow-up discussions. Reformatted per REF-STYLE."
---

# 1. Canonical Simulation

## 1. Component contract

    INPUT : score series (from Component 0), harness configuration
    OUTPUT: daily gross/net PnL series; realized turnover; cost drag;
            stored dossier in the alpha registry

## 2. Summary

Component 1 applies one uniform conversion to every candidate leaving mining:
score in, canonical position out, net-of-cost PnL and a standardized dossier
out. Its single purpose is comparability - from here on "a good alpha" is an
objective statement (net-of-cost, common leverage), never a researcher's
impression.

## 3. Specification

3.1 Canonical mapping. Every score passes through the same four steps:

    score -> EWMA smoothing -> rolling z-score -> no-trade band -> cap +/-
    result = canonical position p(t)
    (transforms A-D specified in clauses 3.1-3.4 below)

No alpha may choose its own band or cap. The rule is a factory-wide asset.

3.2 Canonical PnL. Computed by the exact identity:

    pnl(t) = p(t-1) * r(t) - c * abs(p(t) - p(t-1))
    r(t)      asset return over bar t
    p(t-1)    decided at end of bar t-1 from data <= t-1 (anti-lookahead)
    c         cost per unit notional per side = fee + half-spread + buffer
    abs(...)  fees are direction-blind; the position change IS the order size

with c flat (fee plus half-spread approximation). Fully vectorized over the full
history in tens of milliseconds per alpha.

3.3 Artifact bundle. Each candidate leaves with: daily gross/net PnL series
(input to Stage 2 grading, Stage 3 regression, Stage 4 weights); realized
turnover of the canonical position; cost drag as percentage of gross consumed.
Stored in the alpha registry with metadata (params, code version, creation date,
trial count).

3.4 Deliberate exclusions. No real order simulation, no entry/exit logic, no
queue matching - event-driven backtest is reserved for finalists past Components
2 and 3. No per-alpha sizing tuning - an alpha that survives only under special
sizing is fitting noise.

## 4. Worked example

See [[case-studies/seed-alpha-demo.md]] for two seeds through this component with numbers, and
[[concepts/simulation/canonical-mapping.md]] clause 2.5 for the step-by-step numeric thread
(score 37.5 -> smoothed 31.2 -> z = 1.8 -> trade from p = 1.2 to p = 1.8).

## 5. Failure modes

5.1 Per-alpha preprocessing choices (own smoothing windows) - destroys
comparability and smuggles selection bias into preprocessing itself.
Prevention: harness parameters are factory-wide assets ([[concepts/simulation/harness-parameters.md]]).

5.2 Lookahead in the PnL identity - writing p(t) times r(t) instead of p(t-1)
times r(t) steals future information. Prevention: the contract fixes the timing.

5.3 Treating canonical results as tradable results - the stage deliberately
excludes order-book mechanics; those belong to Component 6.

---
## Related notes
- [[concepts/simulation/canonical-mapping.md]] - the four mapping steps explained individually
- [[concepts/simulation/no-trade-band.md]] - hysteresis logic and band selection methods
- [[concepts/simulation/canonical-pnl.md]] - PnL identity dissected term by term, cost units for VN30F1M
- [[concepts/simulation/harness-parameters.md]] - who owns span/window/band and how they are calibrated
- [[stages/stage-0-alpha-mining.md]], [[stages/stage-2-evaluation-screening.md]]
