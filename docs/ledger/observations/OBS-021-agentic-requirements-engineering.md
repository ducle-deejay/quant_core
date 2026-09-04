---
doc_id: OBS-021
title: Agentic requirements engineering method for the operating backbone
type: observation
owner: research
status: open
version: 1.0
components: [0, 1, 2, 3, 4, 5, 6, 7]
tags: [agentic-engineering, requirements, testing, evaluation, vertical-slices]
source: "owner discussion 2026-09-04: choose an agent-based development method for deriving the operating backbone from DEC-025; current OpenAI agent and evaluation guidance reviewed"
design: [OV-LIFECYCLE, STG-0-ALPHA-MINING, STG-1-CANONICAL-SIM, STG-2-EVALUATION, STG-3-ORTHOGONALIZATION, STG-4-COMBINATION, STG-5-POSITION-CONSTRUCTION, STG-6-TRADE-SCHEDULING, STG-7-RISK-OVERLAY]
code: [AGENTS.md, docs/ledger/decisions/DEC-025-required-operating-supporting-artifacts.md]
test: []
---

# OBS-021 - Agentic Requirements Engineering for the Operating Backbone

## 1. Finding and Recommendation

Traditional Development, Test-Driven Development, and Specification-Driven Development are each insufficient as the sole method for converting DEC-025 into an agent-implemented operating backbone. The recommended approach is a hybrid: outcome-first behavioral contracts, incremental vertical slices, selective Test-Driven Development, continuous evaluation, risk-based assurance, and independent evidence-based verification.

There is no single universally established agentic-engineering methodology that replaces all three development methods. The recommendation combines their useful properties while separating intent, implementation freedom, verification, and decision authority.

At system level, specify observable outcomes and hard boundaries. At work-package level, deliver thin end-to-end slices. Use Test-Driven Development for stable deterministic behavior, broader evaluation and adversarial verification for system behavior, and an independent review pass before completion.

## 2. Corrections to the Three Development Models

2.1 Traditional Development. Traditional Development does not inherently mean that one agent writes code and then tests its own work. The relevant failure mode is a closed single-agent loop in which the same reasoning process chooses the design, implementation, tests, and completion verdict. That correlated self-review can preserve one mistaken assumption across every artifact.

Traditional exploration remains useful when the solution or dependency behavior is not yet understood. Read-only investigation and disposable technical spikes can discover constraints before a stable behavior contract is written. They must not silently become production design.

2.2 Test-Driven Development. Test-Driven Development provides executable examples and strong regression protection for behavior that is already understood. It does not prove that the examples are complete, that their expected result is correct, or that the implementation satisfies unobserved properties. An agent can write tests first and still encode the same mistaken model into both tests and code.

Test-Driven Development should therefore be one verification layer rather than the system-level method. Property, metamorphic, boundary, state-machine, integration, replay, fault-injection, differential, mutation, and paper-runtime evidence are needed to challenge what example-based tests omit.

2.3 Specification-Driven Development. Specification-Driven Development does not need to prescribe technical implementation. A good behavioral specification defines what must be observable, the invariant boundaries, inputs, outputs, ownership, failure behavior, evidence, and non-goals. It explicitly leaves internal architecture, classes, methods, storage, serialization, and algorithms open where the solution path is not itself a contract.

The bias risk appears when a specification embeds an unverified technical design. That is the failure seen when business activities in DEC-019 and DEC-020 were written as method calls and then treated as implementation commitments.

## 3. Risks the Method Must Control

The owner identified three primary risks: a builder agent self-certifying its own code, Test-Driven Development failing to cover unknown cases, and an over-detailed specification narrowing agent reasoning to a possibly wrong technical design.

The engineering method must also control the following risks.

- Specification gaming, where an implementation passes stated checks while violating intent.
- A wrong specification producing internally consistent but wrong code and tests.
- Mocks passing while real dependency integration fails.
- Premature abstractions and duplicate capabilities already owned by Rust or Nautilus.
- Treating every noun in the operating model as a class, method, registry, or database.
- Hidden defaults turning a missing Required Operating Artifact into apparently valid behavior.
- Context and terminology drift across requirements, implementation, tests, and handoffs.
- Happy-path coverage without boundary, temporal, failure, recovery, and reconciliation cases.
- Backtest leakage, look-ahead behavior, timestamp mismatch, or unrealistic fill assumptions.
- Paper runtime producing orders and fills without enough attribution evidence to close the four researcher feedback loops.
- A test suite that passes the current implementation but cannot reject plausible wrong implementations.
- Unbounded agent autonomy, side effects, or scope expansion without explicit authority.

## 4. Outcome-First Behavioral Contracts

DEC-025 must not be translated directly into a list of methods. Each implementation work package begins with a behavioral requirement containing the following fields.

```text
Outcome
Actor or consumer
Required Operating Artifacts
Supporting Artifacts
Authoritative runtime state consumed
Observable output
Invariants
Failure behavior
Acceptance evidence
Non-goals
Open implementation decisions
Dependencies
```

Hard constraints include canon semantics, capability ownership, artifact inputs and outputs, state boundaries, safety invariants, failure behavior, acceptance evidence, and prohibitions against duplicating existing Rust or Nautilus capabilities.

Open implementation decisions include internal module structure, classes, methods, storage representation, serialization, concurrency, and algorithms where DEC-025 establishes only an extension point or observable behavior. Requirements state what must be true without pre-selecting how the agent must code it.

## 5. Incremental Vertical Slices

Work should not be divided first into all Alpha methods, all Portfolio methods, all Risk methods, and all Execution methods. That horizontal split can produce individually implemented modules without a working operating loop.

The first slice should cross the complete operating and feedback path using the smallest valid accepted artifacts.

```text
market event
    -> active alpha score
    -> portfolio desired target
    -> risk allowed target
    -> primary-order intent
    -> Nautilus order and broker-confirmed fill
    -> attributed decision and execution evidence
    -> inputs visible to all four researcher feedback loops
```

Later slices extend one observable behavior, add one failure path, or replace a baseline or manually provided artifact with a fuller capability. A vertical slice is complete only when the forward operating path and its feedback evidence are both observable.

## 6. Selective Test-Driven Development

Use Test-Driven Development for small, deterministic, stable behavior such as mathematical calculations, artifact validation, state transitions, position and risk boundaries, idempotency, timestamp and session rules, serialization round trips, and regressions for known defects.

Do not require production tests before dependency behavior or architecture boundaries are understood. Where uncertainty is material, perform focused investigation or a disposable spike, record the discovered contract, then write the production behavior and tests. Exploration establishes evidence; it does not authorize unrelated scope or become the final implementation by accident.

## 7. Assurance Portfolio

Example-based unit tests are necessary but not sufficient. Verification should draw from the smallest relevant combination of the following evidence types.

- Known-answer tests for exact formulas and established examples.
- Property tests for classes of valid inputs.
- Metamorphic tests for scale, sign, ordering, and transformation invariants.
- Boundary tests for thresholds, sessions, timestamps, quantities, and numerical limits.
- State-machine tests for alpha lifecycle, risk state, order state, and recovery transitions.
- Contract tests for artifact producers, consumers, and failure behavior.
- Differential and parity tests between Python boundaries and Rust source capabilities.
- Real integration tests for Nautilus, adapters, persistence, and reconciliation boundaries.
- Historical replay for temporal behavior and look-ahead prevention.
- Fault injection for stale data, disconnects, duplicate events, rejection, partial fills, and restart.
- Paper-runtime acceptance using broker-confirmed evidence.
- Mutation testing to determine whether the suite rejects plausible wrong implementations.
- Independent exploratory review to challenge assumptions not encoded in automated checks.

Verification depth is risk-based. Order, exposure, risk, execution, reconciliation, and feedback-attribution boundaries require stronger evidence than a non-blocking Supporting Artifact renderer.

## 8. Independent Verification

The builder agent is not the final authority for its own work package. Verification starts from the behavioral requirement rather than from tests written by the builder.

```text
Requirement owner
    defines outcome and hard boundaries

Builder agent
    explores the repository and dependencies
    proposes or selects an implementation path
    implements the bounded slice

Independent verification pass
    attempts to falsify the implementation
    derives additional cases from the requirement
    checks missing and unintended scope

Deterministic harness
    runs relevant tests, integration checks, static checks,
    artifact validation, and smoke or replay evidence

Human owner
    decides unresolved intent, authority, and architecture questions
```

The independent pass asks which incorrect implementation could pass the current tests, which inputs or transitions remain unobserved, whether the builder added anything without a consumer, whether every required consumer has a producer, and whether mocks conceal a failed real boundary.

Independent verification may be performed by a separate agent, a separately prompted review pass with no reliance on the builder's conclusion, a deterministic evaluator, a human reviewer, or a combination. Separation of evidence and authority matters more than the number of agents.

## 9. Evidence Gate

"All tests pass" is necessary where tests exist but is not sufficient for completion. Each slice produces a reviewable evidence bundle.

```text
requirements addressed
implementation paths
tests and evaluations mapped to requirements
validation commands and outcomes
real dependency evidence where required
artifact producer-consumer coverage
assumptions
uncovered risks
deferred behavior
```

A slice is complete only when its acceptance evidence supports the requirement, no material hard boundary remains unverified, and any residual uncertainty is explicit rather than hidden behind a passing test suite.

## 10. Continuous Evaluation Growth

The complete test and evaluation corpus cannot be known before implementation. It must grow through the same feedback principle used by the trading operating model.

```text
initial invariants and scenarios
    -> implementation
    -> independent challenge
    -> integration and paper evidence
    -> newly discovered failure or ambiguity
    -> new regression, property, or evaluation case
    -> stronger next implementation
```

Production and paper logs are evidence sources for new cases. Typical, boundary, edge, temporal, recovery, and adversarial cases should be added as they are discovered. Automated checks require periodic calibration against human judgment and actual operating outcomes.

## 11. Deriving Requirements From DEC-025

The derivation flow is:

```text
DEC-025 operating model
    -> extract behavioral requirements
    -> build artifact and capability coverage map
    -> identify the first complete vertical slice
    -> define acceptance evidence
    -> allow technical implementation exploration
    -> implement
    -> independently challenge
    -> run deterministic verification
    -> exercise broker paper runtime
    -> feed findings into requirements and evaluation cases
```

Required Operating Artifacts produce mandatory behavioral requirements. Supporting Artifacts produce non-blocking requirements. Authoritative Nautilus runtime state is consumed rather than reimplemented.

For each artifact, requirements answer:

```text
Who produces it?
Who consumes it?
What observable behavior depends on it?
How is validity demonstrated?
What happens when it is missing or invalid?
Which tests or evaluations could falsify the implementation?
```

The first backbone requirement set should preserve the end-to-end path from market data through one active alpha, portfolio target, risk permission, execution, broker-confirmed result, attribution, and evidence for Quantitative, Portfolio, Risk, and Execution Researcher feedback.

## 12. Recommended Operating Method

The proposed engineering method is:

```text
System level
    outcome-first behavioral contracts

Work-package level
    incremental vertical slices

Stable deterministic behavior
    selective Test-Driven Development

System and agent behavior
    continuous evaluation-driven development

High-risk boundaries
    property, metamorphic, boundary, state-machine,
    differential, integration, replay, fault-injection,
    mutation, and paper-runtime verification as applicable

Completion
    independent evidence-based verification
```

This method keeps DEC-025 strong enough to prevent ownership and scope drift without turning it into a technical design. Agents retain freedom to explore and select an implementation, but they do not define success unilaterally or certify their own work from self-authored tests alone.

## 13. Current External Guidance

Current official OpenAI guidance recommends outcome-first prompts that define success criteria, constraints, evidence, and output shape while avoiding detailed process instructions unless the path itself is required. It also recommends relevant targeted validation and traceable implementation plans rather than indiscriminate testing.

Official evaluation guidance recommends evaluating early and continuously, using task-specific distributions, growing cases from logs, combining automated metrics with human judgment, and including typical, edge, and adversarial cases. These recommendations support the hybrid above but do not establish one universally named software-development methodology.

## 14. Resolution Condition

This observation remains open until the owner selects the engineering method for converting DEC-025 into requirements and defines the first vertical slice, independent verification boundary, evidence bundle, and minimum assurance portfolio. A later decision may ratify the chosen method and become the implementation-governance anchor for Quant Developers and coding agents.

## Related Notes

- [DEC-025](../decisions/DEC-025-required-operating-supporting-artifacts.md) - triaged operating model to be converted into behavioral requirements.
- [DEC-024](../decisions/DEC-024-continuous-research-replenishment-operating-model.md) - predecessor establishing continuous researcher feedback and candidate-version promotion.
- [OBS-020](OBS-020-artifact-criticality-taxonomy.md) - artifact classification and coverage rules used during requirements derivation.
- [OBS-019](OBS-019-continuous-research-replenishment.md) - four researcher replenishment and recalibration loops.
- [OpenAI model guidance](https://developers.openai.com/api/docs/guides/latest-model?model=gpt-5.5) - current outcome-first prompting and coding-agent verification guidance reviewed for this observation.
- [OpenAI evaluation best practices](https://developers.openai.com/api/docs/guides/evaluation-best-practices) - current evaluation-driven development, dataset, continuous evaluation, and human-calibration guidance reviewed for this observation.
