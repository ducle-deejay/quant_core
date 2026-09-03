---
doc_id: OBS-020
title: Required and supporting artifact criticality taxonomy
type: observation
owner: research
status: open
version: 1.0
components: [0, 1, 2, 3, 4, 5, 6, 7]
tags: [operating-model, artifacts, ownership, governance, runtime-state]
source: "owner discussion 2026-09-03: clarify required and optional artifacts in the systematic-trading operating model"
design: [OV-LIFECYCLE, STG-0-ALPHA-MINING, STG-1-CANONICAL-SIM, STG-2-EVALUATION, STG-3-ORTHOGONALIZATION, STG-4-COMBINATION, STG-5-POSITION-CONSTRUCTION, STG-6-TRADE-SCHEDULING, STG-7-RISK-OVERLAY]
code: [docs/ledger/decisions/DEC-024-continuous-research-replenishment-operating-model.md, docs/ledger/decisions/DEC-025-required-operating-supporting-artifacts.md]
test: []
---

# OBS-020 - Required and Supporting Artifact Criticality Taxonomy

## 1. Finding

The operating model needs an explicit artifact-criticality taxonomy. A two-class distinction is directionally correct, but `Required Artifacts` must contain separate operating and governance subtypes, and `Supporting Artifacts` is a safer name than `Optional Artifacts`. "Optional" can be misread as unimportant, ungoverned, or freely disposable even when an artifact remains useful for interpretation, diagnosis, or reproducibility.

Artifact criticality is scoped to a consumer and activity. An artifact is required when its absence prevents a downstream activity from running correctly, forbids a lifecycle transition, or makes a decision impossible to reproduce or audit. Classification is based on dependency and consequence, not file format or whether an artifact is human-readable.

The proposed taxonomy is:

```text
Artifacts
    |-- Required Artifacts
    |       |-- Required Operating Artifacts
    |       `-- Required Governance Artifacts
    |
    `-- Supporting Artifacts
```

Mutable authoritative runtime state remains outside this artifact taxonomy.

## 2. Required Artifacts

An artifact is required if a named system capability or business actor cannot correctly complete a dependent activity without it, if it authorizes a lifecycle or deployment transition, or if it provides mandatory evidence for reproduction or audit.

Every required artifact must declare its owner, producer, consumers, schema or contract, version and provenance, validation rules, activation status where applicable, retention policy, and failure behavior.

## 3. Required Operating Artifacts

Required Operating Artifacts are directly consumed by the research or production system to perform research, evaluate candidates, deploy an accepted version, trade, control risk, or recalibrate the operating model.

Examples within the current operating model include:

- Research hypotheses and seed expressions required to begin an alpha-mining activity.
- Dataset, research-harness, and cost-model versions required to reproduce a standardized backtest.
- Candidate specification required to identify what was evaluated.
- Backtest and evaluation results required by admission gates.
- Residual and incrementality evidence required by pool admission.
- Eligible and active alpha composition required by portfolio construction.
- Portfolio weights required by score combination.
- Position-sizing model required to transform a composite score into desired exposure.
- Risk budget and intervention policy required to produce permitted exposure and live risk action.
- Execution policy required to transform a permitted target into primary-order intent.
- Live monitoring baseline required to evaluate live alpha health.
- Deployment configuration required to start the intended runtime.
- Decision attribution and execution evidence required by feedback and recalibration.

The default failure rule is:

```text
missing or invalid Required Operating Artifact
    -> fail closed
    -> do not continue the dependent activity
```

"Fail closed" is scoped to the dependent activity. A missing research input may block a mining run without stopping live trading, while a missing active risk policy may block runtime startup or new exposure.

## 4. Required Governance Artifacts

Required Governance Artifacts need not sit on the live runtime path, but governance cannot complete without them. They provide the evidence or authorization required to review, approve, promote, disable, retire, override, or audit a model or policy.

Examples include:

- Approval or rejection evidence.
- Alpha lifecycle-transition records.
- Model-validation records.
- Promotion and retirement rationale.
- Policy-change decisions.
- Incident records and mandatory post-mortems.
- Evidence supporting a manual override.
- Human review records required by an active deployment policy.

The governing boundary is:

```text
runtime may not consume this artifact
but governance cannot complete without it
```

A report may therefore be a Required Governance Artifact. Human-readable format does not make an artifact optional.

## 5. Supporting Artifacts

Supporting Artifacts improve human interpretation, visualization, diagnosis, debugging, exploratory analysis, communication, presentation, convenience, or reproduction support. Their absence may reduce convenience or observability, but it does not change a system decision or block the operating lifecycle.

Examples include:

- Charts and dashboards derived from authoritative evidence.
- Notebook outputs.
- Ad hoc research reports.
- Presentation decks.
- Convenience data exports.
- Temporary comparison grids.
- Human-readable summaries derived from required source artifacts.

The default failure rule is:

```text
missing Supporting Artifact
    -> may reduce convenience or observability
    -> must not change the system's decision
    -> must not block the operating lifecycle
```

A Supporting Artifact must not become a shadow source of truth. When it is regenerable, it must identify the authoritative inputs and versions from which it was derived. If it contains unique human judgment, approval, or rationale that cannot be regenerated, that unique content is a Required Governance Artifact and must be stored accordingly.

## 6. Classification Is Not Determined by Format

Do not classify artifacts by storage or presentation format.

```text
JSON or database record -> required
PDF, chart, or report   -> supporting
```

The mapping above is invalid. Classification depends on the consumer and the consequence of absence.

For example, a tear sheet used only as an additional research view is supporting. The same tear sheet becomes required governance evidence if an active approval policy requires it before alpha promotion. A dashboard that only visualizes metrics stored elsewhere is supporting. If the dashboard is the sole place where a manual risk approval is recorded, the approval record is a Required Governance Artifact and must move to an authoritative store.

## 7. Classification Decision Rule

Classify each artifact by answering four questions.

1. Which capability or actor consumes it?
2. Which activity must stop when it is missing or invalid?
3. Does it authorize a lifecycle transition, deployment, trading action, intervention, or model replacement?
4. Is it mandatory evidence for reproducing or auditing a decision?

If the answer to question 2, 3, or 4 is yes, the artifact is required for the named scope. If all three answers are no, it is a Supporting Artifact.

The classification record should qualify the scope rather than label an artifact globally. An artifact may be supporting for one consumer and required for another. Where that occurs, the strictest active dependency governs retention and validation.

## 8. Runtime State Boundary

Authoritative mutable runtime state must remain distinct from artifacts. Nautilus orders, fills, positions, accounts, trading state, reconciliation state, and current Cache state are live state owned by Nautilus. Project components may consume that state and create immutable or versioned evidence from it, but they must not relabel, copy, or persist a second authoritative runtime state as an artifact.

This gives the complete ownership distinction:

```text
mutable authoritative runtime state
    -> current operational truth owned by its runtime system

Required Operating Artifact
    -> required input or evidence for a named operating activity

Required Governance Artifact
    -> required evidence or authorization for a governance activity

Supporting Artifact
    -> non-blocking derived aid for interpretation or convenience
```

## 9. Owner Scope Clarification and Proposed Correction

The owner approved a narrower artifact correction for the current operating-model and backbone scope. DEC-025 must classify only Required Operating Artifacts and Supporting Artifacts, while keeping authoritative data sources and authoritative mutable runtime state separate. The governance-artifact subtype explored earlier in this observation is outside the approved DEC-025 correction and does not produce current implementation requirements.

The `Data and Artifact Ownership` section is renamed `Data, Artifact, and Runtime-State Ownership`. Every listed operating artifact identifies its owner, producer, consumer, required-for scope, authoritative source, provenance, retention or regenerability, and missing or invalid behavior. Supporting artifacts identify their authoritative sources and remain non-blocking.

The same taxonomy is applied consistently to scope, vocabulary, business users, capability ownership, lifecycle transitions, operating-algorithm dependencies, capability coverage rules, implementation boundaries, and acceptance. No API, database schema, serialization format, storage technology, or report renderer is implied by this observation.

## 10. Resolution Condition

This observation remains open until the owner approves DEC-025's complete classification of Required Operating Artifacts, Supporting Artifacts, authoritative data sources, and authoritative mutable runtime state. Resolution requires cross-section coverage, non-blocking supporting outputs, shadow-source-of-truth prevention, scoped missing behavior, and the Nautilus runtime-state boundary.

## Related Notes

- [DEC-024](../decisions/DEC-024-continuous-research-replenishment-operating-model.md) - triaged operating model whose Data and Artifact Ownership section requires this taxonomy.
- [DEC-025](../decisions/DEC-025-required-operating-supporting-artifacts.md) - proposed complete DEC-024 copy-patch applying the owner-approved artifact scope.
- [DEC-021](../decisions/DEC-021-actor-artifact-capability-operating-model.md) - resolved predecessor that first separated project artifacts from Nautilus runtime state.
- [OBS-019](OBS-019-continuous-research-replenishment.md) - open operating-model extension defining candidate model and policy artifacts across researcher roles.
- [framework lifecycle](../../enhanced/framework-lifecycle.md) - frozen component input/output and operating-cadence model.
- [risk overlay and monitoring](../../enhanced/stages/stage-7-risk-overlay-monitoring.md) - frozen automatic runtime intervention and human-alert boundary.
