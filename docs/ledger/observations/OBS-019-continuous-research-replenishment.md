---
doc_id: OBS-019
title: Continuous researcher replenishment and recalibration boundaries
type: observation
owner: research
status: open
version: 1.0
components: [0, 1, 2, 3, 4, 5, 6, 7]
tags: [operating-model, feedback, research-replenishment, extension-points]
source: "owner discussion 2026-09-03: define how four researcher roles continuously replenish and recalibrate the operating model"
design: [OV-LIFECYCLE, STG-0-ALPHA-MINING, STG-1-CANONICAL-SIM, STG-2-EVALUATION, STG-3-ORTHOGONALIZATION, STG-4-COMBINATION, STG-5-POSITION-CONSTRUCTION, STG-6-TRADE-SCHEDULING, STG-7-RISK-OVERLAY]
code: [docs/ledger/decisions/DEC-021-actor-artifact-capability-operating-model.md]
test: []
---

# OBS-019 - Continuous Researcher Replenishment and Recalibration Boundaries

## 1. Finding

A practitioner quantitative-trading shop needs a continuous research replenishment loop across all four researcher roles. For alpha research, the precise boundary is that the Quantitative Researcher continuously contributes research hypotheses and seed expressions, while alpha-mining capabilities use those inputs to produce candidate alphas. The backbone does not originate hypotheses, and alpha mining does not directly produce production alphas.

The same pattern applies to portfolio, risk, and execution research. Each researcher continuously maintains candidate versions of the models and policies within that role's ownership. Research and production evidence feeds diagnosis and recalibration, but it never mutates an active production artifact directly. Only an evaluated, validated, and accepted version becomes an input to the next operating loop.

"Continuous" describes a permanently active research queue and feedback process. It does not mean that each researcher creates a model on every market event, that every review runs as a scheduled software method, or that production hot-swaps an unvalidated artifact.

## 2. Replenishment, Recalibration, and Runtime Execution

These three activities must remain distinct.

2.1 Research replenishment. A researcher introduces new hypotheses, seed expressions, model families, algorithms, policy candidates, or structural alternatives. Replenishment expands or replaces the available research inventory.

2.2 Recalibration. A researcher adjusts parameters, thresholds, estimators, policies, baselines, or model versions in response to new evidence. Recalibration modifies a candidate version of an existing approach.

2.3 Runtime execution. The research or production system applies an active, approved version and records the resulting evidence. Runtime execution does not own the research judgment that creates or changes that version.

The shared practitioner loop is:

```text
production and research evidence
    -> researcher diagnosis
    -> new or recalibrated candidate artifact
    -> offline evaluation
    -> shadow or paper validation where required
    -> accepted version
    -> production runtime
    -> new evidence
```

The live feedback boundary is:

```text
live evidence
    does not directly mutate production models

live evidence
    -> feeds researcher-owned work
    -> produces a candidate version
    -> passes validation and promotion
    -> becomes the new active version
```

## 3. Quantitative Researcher Loop

The Quantitative Researcher keeps the alpha inventory replenished as active alphas decay, become crowded, lose incrementality, or stop matching their research evidence.

3.1 Continuous contributions. The researcher contributes research hypotheses, seed expressions, new data transformations and features, search-space or grammar revisions, candidate constraints, fitness configurations, and new alpha families when existing families become saturated or excessively correlated.

3.2 Continuous recalibration. The researcher recalibrates candidate-search fitness, standardized-backtest configuration, evaluation gates, multiple-testing controls, parameter-stability expectations, live monitoring baselines, and the interpretation of alpha decay and health.

3.3 Evidence inputs. The work consumes production-alpha decay, live-versus-backtest drift, rejected-candidate statistics, family saturation, pool correlation, incrementality failures, regime changes, and post-mortem findings.

3.4 Outputs and boundary. The role-to-machine flow is:

```text
research hypotheses
seed expressions
search configuration
fitness configuration
    -> alpha-mining capability
    -> candidate alphas
```

Candidate alphas must still pass standardized backtest, evaluation, and portfolio incrementality. A candidate is not a production alpha merely because mining produced it.

## 4. Portfolio Researcher Loop

The Portfolio Researcher keeps the alpha collection capable of producing portfolio-level edge after diversification, concentration, turnover, and capacity constraints.

4.1 Continuous research and recalibration. The researcher maintains pool-admission and incrementality policy, active-alpha composition, alpha standardization, combination methods, portfolio weights, covariance, correlation and residual estimates, benchmark portfolios, diversification constraints, turnover and capacity constraints, portfolio-contribution analysis, retirement criteria, and deployment policy.

4.2 Evidence inputs. The work consumes new eligible candidate alphas, decay or retirement of active alphas, correlation drift, concentration changes, portfolio drawdown, marginal alpha contribution, weight instability, capacity evidence, and realized transaction costs.

4.3 Outputs and boundary. The role-to-system flow is:

```text
eligible alpha evidence
    -> candidate active composition
    -> candidate portfolio weights
    -> out-of-sample comparison
    -> accepted composition and weights
```

When an active alpha decays, the Portfolio Researcher does more than fill an empty slot. The role determines which candidate adds incremental value and how the entire portfolio should be reallocated.

## 5. Risk Researcher Loop

The Risk Researcher owns the model that adjusts position sizing and keeps permitted exposure aligned with current risk evidence.

5.1 Continuous research and recalibration. The researcher maintains position-sizing methods, volatility targets and estimators, risk budgets, risk multipliers, exposure and leverage caps, drawdown and intraday-loss policy, stress scenarios, alpha-health intervention policy, reduce, halt, flatten and shutdown thresholds, restart conditions, and regime-sensitive risk adjustments.

5.2 Evidence inputs. The work consumes realized volatility, drawdown distributions, portfolio concentration, correlation spikes, position-tracking error, tail events, stress results, alpha-health deterioration, differences between expected and realized exposure, risk incidents, and post-mortems.

5.3 Outputs and boundary. The role-to-runtime flow is:

```text
candidate sizing model
candidate risk budget
candidate intervention policy
    -> validation
    -> accepted risk-policy version
    -> automatic runtime application
```

Runtime risk continuously monitors and acts under the active policy. The Risk Researcher recalibrates candidate policies outside the order path and does not approve each live order or emergency intervention.

## 6. Execution Researcher Loop

The Execution Researcher keeps as much forecast value as possible after spread, impact, latency, liquidity, and venue behavior.

6.1 Continuous research and recalibration. The researcher maintains the transaction-cost model, spread and impact estimates, fill-probability model, urgency policy, passive-versus-aggressive decision, execution-algorithm parameters, order-type and placement policy, time-of-day behavior, size and liquidity buckets, capacity estimates, and scheduling or slicing policy.

6.2 Evidence inputs. The work consumes broker-confirmed fills, implementation shortfall, slippage by time, volatility and order size, reject and cancel rates, latency, order-book depth, fill rates, forecast decay relative to waiting cost, venue and session behavior, incidents, and post-mortems.

6.3 Outputs and boundary. The role-to-runtime flow is:

```text
candidate cost model
candidate execution policy
candidate execution algorithm or configuration
    -> replay, backtest, or paper validation
    -> accepted execution version
    -> production runtime
```

Execution evidence also feeds the standardized backtest so candidate alphas face realistic costs, portfolio construction so sizing reflects capacity, and Risk Researcher work when liquidity or execution quality deteriorates.

## 7. Extension-Point Ownership

The existing research extension points align with researcher ownership as follows.

```text
Quantitative Researcher
    ga_fitness
    researcher-defined hypotheses and seed expressions

Portfolio Researcher
    combine_methods

Risk Researcher
    sizing_methods
    risk_policies

Execution Researcher
    execution_algorithms
    versioned cost-model artifacts
```

The current extension-point list does not explicitly represent seed expressions as a research-input boundary. That gap should be corrected at the artifact level before any API is designed.

```text
Alpha-mining research inputs
    research hypotheses
    seed expressions
    search-space or grammar version
    fitness configuration version
```

Do not resolve the gap by inventing a submission or registration method. The operating model first defines the artifact boundary. An implementation decision may later choose an API, file format, catalog, registry, or other transport after the use case and contract are understood.

## 8. Proposed Operating-Model Correction

The Quantitative Researcher step should distinguish continuously replenished research inputs from machine candidate generation.

Replace the conceptual wording:

```text
Quantitative Researcher defines:
    hypotheses
    hypothesis seeds
```

with:

```text
Quantitative Researcher defines and continuously replenishes:
    research hypotheses
    seed expressions
    search-space or grammar configuration
    fitness configuration
```

Add the cross-role feedback principle:

```text
Each research role continuously maintains candidate versions of the models
and policies it owns.

Runtime evidence feeds researcher-owned recalibration. It never mutates an
active production artifact directly.

Only validated and accepted versions become inputs to the next operating loop.
```

This correction targets the operating model established by DEC-021. Because DEC-021 is already resolved, its text must not be rewritten. After the actor boundaries, artifact names, validation requirements, and promotion semantics are approved, a successor decision must record the corrected operating model and supersede the affected DEC-021 wording.

## 9. Resolution Condition

This observation remains open until the owner approves the continuous replenishment and recalibration semantics for all four researcher roles, including the seed-expression artifact boundary and the rule that runtime evidence cannot directly mutate active production artifacts. Resolution requires a successor decision rather than an edit to resolved DEC-021.

## Related Notes

- [DEC-021](../decisions/DEC-021-actor-artifact-capability-operating-model.md) - current resolved operating model whose research feedback semantics require this extension.
- [OBS-018](OBS-018-operating-model-contract-leakage.md) - prior correction separating researcher activities from implementation contracts.
- [alpha mining](../../enhanced/stages/stage-0-alpha-mining.md) - frozen boundary where humans supply seeds and machines enumerate or genetically breed expressions.
- [framework lifecycle](../../enhanced/framework-lifecycle.md) - frozen continuous-loop and feedback-cadence model.
- [risk overlay and monitoring](../../enhanced/stages/stage-7-risk-overlay-monitoring.md) - frozen boundary between automatic runtime risk and subsequent human decisions.
