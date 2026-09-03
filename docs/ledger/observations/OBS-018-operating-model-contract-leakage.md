---
doc_id: OBS-018
title: Operating-model algorithm conflates researcher activity with implementation contracts
type: observation
owner: research
status: resolved
version: 1.0
components: [0, 1, 2, 3, 4, 5, 6, 7]
tags: [operating-model, lifecycle, research-roles, api-contracts]
source: "owner discussion 2026-09-03: correction review of DEC-019 and DEC-020"
design: [OV-LIFECYCLE, STG-0-ALPHA-MINING, STG-1-CANONICAL-SIM, STG-2-EVALUATION, STG-3-ORTHOGONALIZATION, STG-4-COMBINATION, STG-5-POSITION-CONSTRUCTION, STG-6-TRADE-SCHEDULING, STG-7-RISK-OVERLAY]
code: [docs/ledger/decisions/DEC-019-systematic-trading-lifecycle-operating-model.md, docs/ledger/decisions/DEC-020-systematic-trading-operating-model-correction.md, docs/ledger/decisions/DEC-021-actor-artifact-capability-operating-model.md]
test: []
---

# OBS-018 - Operating-Model Algorithm Conflates Researcher Activity With Implementation Contracts

## 1. Finding

The lifecycle sketches in DEC-019 and DEC-020 express the operating model as `Module.method()` calls and then repeat those calls in a method table. This turns a business-level description of participants, activities, artifacts, system capabilities, and feedback into a premature implementation contract. In particular, activities owned by researchers are represented as methods the backbone is expected to implement.

DEC-020 currently states that it supersedes DEC-019 as the implementation guide, so names appearing both in its module structure and method table are reasonably read as implementation commitments. This is already incorrect for `Alpha.generate_hypotheses()`: hypothesis formation is a conceptual lifecycle activity performed by a researcher, not a method the backbone owns.

The correction must not be limited to removing that one method. The operating-model algorithm needs a consistent abstraction boundary across research, portfolio construction, execution, risk, and feedback. It should say who performs an activity, what artifact enters or leaves a component, which part is automated, and which approved model or policy the runtime applies. Actual Python and Rust API contracts belong in a later implementation design.

## 2. Canon Boundaries

The frozen lifecycle canon distinguishes component, build-phase, and runtime-loop vocabularies. Components have input/output contracts, but those contracts do not prescribe class or method names. The lifecycle also places manual research before factory automation: hand-written seeds pass through the research harness first, while grammar, genetic search, registry instrumentation, and clustering arrive in a later automation phase.

The alpha-mining canon makes the human/machine boundary explicit: humans supply hypothesis seeds; machines enumerate or genetically breed expressions. Therefore hypothesis formation stays outside the backbone, while candidate enumeration or search may be automated from researcher-defined inputs.

The risk canon establishes the opposite boundary for live intervention. The runtime risk chain operates without human input and informs humans so they can decide what follows. Risk-policy research is human-owned, but application of the active policy, including automatic reduction, halt, or flatten actions, is runtime behavior.

## 3. Business Users and Participation

The current operating model has four business-user personas. Nautilus, `quant_core`, and broker adapters are system components rather than users. A Quant Developer builds the system but is not an operating-model actor. No separate operator or deployment-approver persona is established by this correction; adding one requires an explicit owner decision.

3.1 Quantitative Researcher. This user owns hypothesis formation, supplies hypothesis seeds, defines research constraints, designs alpha search spaces and fitness, designs experiments, reviews standardized-backtest and evaluation evidence, investigates rejected candidates, defines the interpretation of alpha-health evidence, and owns changes to the alpha research harness and evaluation policy.

3.2 Portfolio Researcher. This user owns pool incrementality, active-composition research, combination and weighting policy, benchmark selection, portfolio contribution analysis, pool-health review, and retirement research. The Portfolio Researcher receives alpha evidence from the Quantitative Researcher and supplies portfolio targets and composition artifacts to downstream position construction.

3.3 Execution Researcher. This user owns transaction-cost assumptions, execution-cost models, urgency policy, execution-algorithm research, slippage analysis, fill-quality research, and changes to scheduling parameters. The Execution Researcher supplies cost evidence to standardized backtests and position sizing as well as approved execution policy to the live runtime.

3.4 Risk Researcher. This user owns the model that adjusts position sizing, including risk budgets, risk multipliers, exposure constraints, drawdown policy, live intervention thresholds, and escalation rules. The Risk Researcher defines and versions the policy; the runtime applies its active version independently.

3.5 Participation by operating stage. User participation spans the complete loop as follows.

- Hypothesis formation - the Quantitative Researcher uses research observations, post-mortems, live failures, and family statistics to define hypotheses and seeds. Other researchers may supply evidence through cross-functional post-mortems.
- Alpha mining - the Quantitative Researcher defines the search space, candidate constraints, and fitness. Machine capabilities may enumerate or genetically breed candidate expressions from those inputs.
- Standardized backtest - the Quantitative Researcher owns experiment design and interpretation. The Execution Researcher supplies the approved cost assumptions or model used by the harness.
- Evaluation and screening - the Quantitative Researcher owns evaluation-policy research and investigates failures. The system may apply the active objective gates and produce the pass/fail evidence.
- Pool incrementality and orthogonalization - the Portfolio Researcher owns the admission policy, with the Quantitative Researcher supplying the candidate evidence. The system computes residual and incrementality statistics.
- Active composition and weights - the Portfolio Researcher owns composition, combination, weighting, benchmark, and deployment-policy research. The system may run a scheduled refit using the active policy.
- Position construction - the Portfolio Researcher owns the conversion from portfolio signal to desired exposure. The Risk Researcher owns the risk budget, multiplier, and constraints that adjust the position size.
- Trade scheduling - the Execution Researcher owns cost, urgency, and execution-policy research. The runtime converts an allowed target into primary-order intent, while Nautilus owns execution-algorithm timing, slicing, spawned orders, and order state.
- Live risk overlay - the Risk Researcher owns policy design. Quantitative and Execution Researchers supply alpha-health and execution evidence. Runtime risk applies the active policy automatically and alerts humans.
- Alpha monitoring - the Quantitative Researcher interprets live-versus-backtest drift and alpha-health evidence; Portfolio and Risk Researchers consume the findings where they affect composition or exposure.
- Portfolio monitoring - the Portfolio Researcher owns profit-and-loss attribution review, pool-health analysis, portfolio contribution, and retirement research, with alpha evidence from the Quantitative Researcher.
- Execution feedback - the Execution Researcher analyzes fills, implementation shortfall, and slippage, then researches and validates cost-model or scheduling-policy changes.
- Risk review - the Risk Researcher reviews risk budgets and the position-sizing overlay with portfolio evidence from the Portfolio Researcher.
- Post-mortem - all four researchers contribute evidence and update the model or policy within their own ownership boundary.

## 4. Contract Leakage in the Current Algorithm

The following findings refer to the `ALGORITHM SYSTEMATIC_TRADING_LIFECYCLE` section of DEC-020. Some named operations may eventually be useful system capabilities, but their presence in an operating-model algorithm must not be treated as approval of a particular method name, signature, or owning class.

4.1 Structural leakage. The method-bearing `Module structure`, the pervasive `Module.method()` notation in the algorithm, and the final `Method table` collectively turn every activity into an API promise. Even correctly automated computations are specified at the wrong abstraction level. The operating model should retain component input/output contracts and ownership, not implementation signatures.

4.2 Initialization detail. `load active configuration`, Nautilus configuration, and node construction are valid runtime concerns, but the current presentation is lower-level than the surrounding business model. The high-level algorithm should state that the system loads the active, owner-approved deployment artifacts and that Nautilus starts, restores, connects, and reconciles before trading. Concrete constructors and configuration APIs belong in implementation design.

4.3 Autonomous research. `WHILE system_active` followed by `Alpha.generate_hypotheses()` models research as an autonomous daemon and assigns hypothesis creation to the backbone. This contradicts the present manual-research boundary and the canon statement that humans provide hypothesis seeds. The research loop must start when the Quantitative Researcher supplies hypotheses or seeds.

4.4 Hidden human/machine boundary in candidate generation. `Alpha.generate_candidates(hypotheses, market_data)` makes candidate production look like one opaque system action. The operating model needs to separate researcher-defined hypotheses, seeds, grammar or search space, constraints, and fitness from machine enumeration or genetic breeding. Candidate-search automation remains valid; automatic hypothesis creation does not.

4.5 Evaluation and baseline ownership. `Alpha.run_standard_backtest()`, `Alpha.evaluate_candidate()`, `Portfolio.orthogonalize_against_pool()`, and `Portfolio.evaluate_incrementality()` can represent automated calculations, but the current chain hides who owns the harness configuration, evaluation policy, and pool-admission policy. Likewise, `Alpha.define_live_monitoring_baseline()` collapses statistical derivation, interpretation, review, and versioning into one method. The operating model must distinguish researcher ownership from system application of an active policy.

4.6 Automatic portfolio research and promotion. The weekly chain `Portfolio.select_active_composition()` to `Portfolio.fit_weights()`, `Portfolio.compare_weights_out_of_sample()`, `Portfolio.publish_active_composition()`, and an `ACTIVE` lifecycle transition removes the Portfolio Researcher from the model. It also silently chooses automatic promotion whenever candidate weights beat a benchmark. The corrected model should state that the Portfolio Researcher owns composition, weighting, benchmark, and deployment policy; the system can run the active policy and produce candidate artifacts. Whether every passing refit is automatically activated or requires review is a separate governance decision and must not be decided implicitly by this algorithm.

4.7 Live transformation expressed as API. The live business flow is valid: active alpha scores become standardized scores, decision contributions, a composite score, a desired target, a risk-adjusted allowed target, a primary-order intent, and finally Nautilus-managed execution. Names such as `Portfolio.combine_scores()`, `Portfolio.build_target_position()`, `Risk.apply_portfolio_constraints()`, and `Execution.create_order_schedule()` nevertheless prescribe APIs from an operating-model sketch. DEC-020 should express the artifact transformations and ownership boundaries. Later implementation design can decide which existing method remains, which Rust primitive is wired, and which Nautilus capability is invoked.

4.8 Risk research versus automatic runtime intervention. The continuous risk chain must not be converted into a human approval loop. The Risk Researcher defines and versions the sizing, limit, monitoring, and intervention policies. Runtime risk applies the active version, automatically reduces exposure or halts or flattens where required, and alerts humans. In contrast, `Risk.review_risk_budgets()` in the quarterly feedback section is researcher work presented as a scheduled method.

4.9 Feedback research presented as scheduled methods. The calls `Execution.fit_cost_model()`, `Portfolio.review_pool()`, `Portfolio.assess_portfolio_contribution()`, `Portfolio.evaluate_pool_membership()`, `Alpha.rerun_parameter_stability()`, `Risk.review_risk_budgets()`, `Alpha.review_backtest_harness()`, `Alpha.version_backtest_harness()`, `Alpha.update_candidate_generation_rules()`, and `Alpha.update_evaluation_rules()` combine evidence calculation, research judgment, model changes, and deployment into implementation contracts. Daily, weekly, monthly, and quarterly labels are operating cadences, not by themselves approval for scheduled API calls or immediate replacement of active models.

4.10 Post-mortem ownership. The final chain `post_mortems -> Alpha.generate_hypotheses() -> Alpha.update_candidate_generation_rules() -> Alpha.update_evaluation_rules()` incorrectly assigns interpretation and research-policy changes to Alpha methods. Post-mortems feed all relevant researchers. Each researcher may propose and validate a new artifact within that role's ownership, and only an accepted version becomes an input to the next loop.

## 5. Proposed Correction to DEC-020

The correction should address the abstraction error systematically instead of deleting isolated methods.

1. Replace the method-bearing `Module structure` with an `Actors and responsibilities` section covering the four researcher personas, system capabilities, Nautilus ownership, and the artifacts passed between them.
2. State explicitly that the lifecycle algorithm is an operating-model view. Activity and capability labels in that algorithm are not public methods, signatures, or implementation commitments.
3. Rewrite the algorithm in the form `actor -> business activity -> artifact -> system capability -> resulting artifact or state`.
4. Separate every model or policy into two steps: the owning researcher defines, reviews, and versions it; the system applies the active version.
5. Express Components 0 through 7 as stable input/output boundaries, preserving the lifecycle semantics established by the canon.
6. Treat daily, weekly, monthly, and quarterly labels as business operating cadences. State separately which calculations run automatically, which evidence is reviewed by a researcher, and how a revised artifact becomes active.
7. Preserve automatic live risk intervention. Human ownership of risk research must not weaken the independent runtime controls.
8. Preserve the live artifact flow from score to target to allowed target to primary-order intent to Nautilus execution, while removing premature method signatures from the operating-model algorithm.
9. Remove the `Method table` from DEC-020 or replace it with a `Capability and ownership` section containing no `Module.method()` signatures. Actual API contracts should be proposed in a separate implementation plan or decision after the operating model is approved.
10. Do not replace deleted researcher-activity methods with invented submission or registration APIs. For example, removing `Alpha.generate_hypotheses()` must not introduce `Alpha.submit_hypothesis()`, `Alpha.register_hypothesis()`, or `Alpha.create_hypothesis()` without a separate requirement and contract discussion.

## 6. Proposed High-Level Algorithm Shape

The corrected algorithm should preserve the complete loop while exposing actors and artifacts rather than method calls.

```text
RESEARCH AND ADMISSION

    Quantitative Researcher
        uses research evidence and post-mortems
        -> defines hypotheses, seeds, search space, constraints, and fitness

    Alpha-mining capability
        consumes researcher-defined research inputs and market data
        -> produces candidate expressions and provenance

    Standardized-backtest and evaluation capabilities
        apply the active harness and evaluation policy
        -> produce backtest evidence, gate results, and research records

    Portfolio Researcher
        owns incrementality and pool-admission policy

    Orthogonalization and incrementality capabilities
        consume candidate and active-pool evidence
        -> produce eligibility evidence and lifecycle results


PORTFOLIO RESEARCH AND REFIT

    Portfolio Researcher
        defines and versions composition, combination, weighting,
        benchmark, and deployment policies

    Scheduled refit
        applies the active policies to eligible and active alpha evidence
        -> produces composition and weight candidates

    Deployment follows the separately approved activation policy
        -> publishes an active composition and its weights


LIVE DECISION AND EXECUTION

    Active alpha models + market state
        -> alpha scores
        -> standardized scores and decision contributions
        -> composite score

    Portfolio construction under the active portfolio model
        -> desired target

    Position-sizing and risk overlay under the active Risk Researcher model
        -> allowed target

    Execution policy under the active Execution Researcher model
        -> primary-order intent

    Nautilus
        -> validates and submits orders
        -> owns execution-algorithm timing and slicing
        -> owns orders, fills, positions, accounts, and reconciliation


LIVE RISK

    Active risk policy + live portfolio, execution, data, process,
    and alpha-health evidence
        -> automatic normal, degraded, reducing, flatten, or shutdown action
        -> alerts to the owning researchers


FEEDBACK AND RECALIBRATION

    Daily evidence
        -> profit-and-loss attribution, alpha health, and research records

    Weekly evidence
        -> Execution Researcher slippage and cost-model review
        -> Portfolio Researcher weight-refit review

    Monthly evidence
        -> Quantitative Researcher alpha and parameter-stability review
        -> Portfolio Researcher pool-health and retirement review

    Quarterly evidence
        -> Risk Researcher risk-budget and sizing-model review
        -> Portfolio Researcher orthogonalization review
        -> Quantitative Researcher harness review

    Cross-functional post-mortems
        -> researcher-proposed and validated model or policy revisions
        -> accepted versions become inputs to the next operating loop
```

## 7. Resolution Condition

Resolved by owner approval of DEC-021 on 2026-09-03. DEC-021 replaces the method-shaped operating model with actor, activity, artifact, capability, and ownership boundaries; preserves the canon component semantics and automatic runtime-risk boundary; and supersedes DEC-020 as the implementation-planning guide.

## Related Notes

- [DEC-019](../decisions/DEC-019-systematic-trading-lifecycle-operating-model.md) - original operating-model draft that introduced the method-shaped lifecycle sketch.
- [DEC-020](../decisions/DEC-020-systematic-trading-operating-model-correction.md) - runtime-ownership correction superseded after this observation exposed its contract leakage.
- [DEC-021](../decisions/DEC-021-actor-artifact-capability-operating-model.md) - approved self-contained actor-, artifact-, and capability-level operating model resolving this observation.
- [framework lifecycle](../../enhanced/framework-lifecycle.md) - frozen distinction among components, build phases, and the continuous runtime loop.
- [alpha mining](../../enhanced/stages/stage-0-alpha-mining.md) - frozen human-seed and machine-search boundary.
- [risk overlay and monitoring](../../enhanced/stages/stage-7-risk-overlay-monitoring.md) - frozen independent runtime-risk boundary.
