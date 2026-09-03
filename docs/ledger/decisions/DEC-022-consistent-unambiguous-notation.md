---
doc_id: DEC-022
title: Consistent and unambiguous notation across engineering artifacts
type: decision
owner: research
status: resolved
version: 1.0
components: [0, 1, 2, 3, 4, 5, 6, 7]
tags: [agents, notation, naming, semantics, governance]
source: "owner approval 2026-09-03: apply the principle of consistent and unambiguous notation to engineering work"
design: [OV-LIFECYCLE, REF-STYLE]
code: [AGENTS.md]
test: []
---

# DEC-022 - Consistent and Unambiguous Notation

## 1. Decision

Apply the mathematical principle of consistent and unambiguous notation as a repository-wide engineering correctness rule. The rule governs design notes, ledger records, code, configuration, tests, and agent replies. Add the complete rule to AGENTS.md and include its compact form in the mandatory subagent handoff preamble so the same discipline applies across harnesses and delegated work.

```text
one concept -> one canonical name
one name    -> one meaning
```

The rule does not require frozen canon or external dependency names to be rewritten. When established vocabularies differ, record an explicit mapping and authority, preserve semantic boundaries, and qualify any collision by owner or namespace.

## 2. Applied Rule

2.1 One concept, one canonical name. Use the same term, symbol, field name, unit, and state qualifier for the same concept across design notes, ledger records, code, configuration, tests, and replies.

2.2 One name, one meaning. Never reuse an unqualified name for concepts owned by different domains. Qualify collisions by owner or namespace, for example `alpha.lifecycle_state`, `risk_engine.trading_state`, `node.environment`, and `account.environment`.

2.3 Declare before use. Define non-obvious symbols, units, sign conventions, time bases, reference frames, and domain-specific abbreviations at their first use. Meaning must not depend on unwritten context.

2.4 Preserve semantic boundaries. Do not collapse intended, permitted, and realized values into one term. Keep `desired_target`, `allowed_target`, and Nautilus `Position` distinct.

2.5 Reconcile legacy names explicitly. When canon, ledger, code, or an external dependency uses different names for the same concept, state the mapping and authority. Never silently rename frozen canon or treat incompatible concepts as equivalent.

2.6 Treat ambiguity as a correctness defect. If a notation can reasonably support more than one interpretation, disambiguate it before designing, implementing, or testing against it.

## 3. Rationale

Notation is part of the contract. A symbol, field, state, or method-shaped label that changes meaning across a flow causes the same class of defect as an inconsistent type: readers, implementers, and tests can each make a locally plausible but globally incompatible interpretation.

This project has already exposed three forms of that failure. The word `ACTIVE` referred to alpha lifecycle, Nautilus trading state, and component lifecycle without an owner qualifier. The word `position` blurred desired exposure, risk-permitted exposure, and broker-confirmed realized state. Method notation in DEC-019 and DEC-020 made business activities look like approved implementation contracts. Explicit names and namespace qualification prevent those meanings from collapsing again.

The rule also makes design-versus-code reconciliation auditable. When the frozen canon, living ledger, current code, or an external dependency uses different vocabulary, a written mapping shows whether the terms are true aliases, historical names, or distinct concepts.

## 4. Scope and Application

Apply the rule during design exploration, ledger writing, API design, configuration design, implementation, test derivation, code review, incident analysis, handoffs, and user-facing explanations. It governs both mathematical notation and engineering identifiers, including names, states, units, signs, timestamps, reference frames, data shapes, ownership qualifiers, and artifact labels.

The rule is semantic rather than cosmetic. Do not rename stable identifiers merely to make words uniform, and do not force two distinct concepts under one convenient name. Prefer an explicit mapping when compatibility or frozen history requires multiple established terms.

## 5. Consequences

- Ambiguous notation blocks design, implementation, or test work until its meaning is qualified.
- Tests must use the governing contract's meaning rather than infer semantics from current variable names.
- New API names must preserve existing semantic boundaries or document a deliberate reconciliation.
- Agent replies and subagent handoffs must carry enough qualification that another participant cannot reasonably interpret a state, quantity, unit, or artifact in two ways.
- Existing ambiguity discovered during implementation is recorded in the ledger and resolved through the normal observation and reconciliation process.

## Related Notes

- [DEC-015](DEC-015-agents-md-instruction-style-v2.md) - instruction structure and communication-style policy imported by every harness.
- [DEC-016](DEC-016-purpose-loop-vocabulary.md) - prior correction where inconsistent system-level vocabulary distorted the project goal.
- [DEC-021](DEC-021-actor-artifact-capability-operating-model.md) - operating model that separates actor, artifact, capability, and state ownership.
- [OBS-018](../observations/OBS-018-operating-model-contract-leakage.md) - finding where method notation created unintended implementation contracts.
- [documentation style guide](../../enhanced/style-guide.md) - frozen notation and presentation conventions for the design canon.
