---
doc_id: DEC-023
title: Prompt-neutral consistent and unambiguous notation policy
type: decision
owner: research
status: resolved
version: 1.0
components: []
tags: [agents, notation, naming, prompt-neutrality, governance]
source: "owner approval 2026-09-03: remove project-specific examples from the always-loaded notation policy"
design: [REF-STYLE]
code: [AGENTS.md]
test: []
---

# DEC-023 - Prompt-Neutral Notation Policy

## 1. Decision

Replace the detailed notation policy introduced by DEC-022 with a compact, domain-neutral correctness rule in AGENTS.md. Remove project-specific state, artifact, module, and dependency examples from the always-loaded agent context. Apply the same neutral wording to the mandatory subagent handoff preamble.

This decision supersedes the normative policy wording of DEC-022. DEC-022 remains unchanged as the historical record of the initial proposal and the project-specific evidence that motivated the principle.

## 2. Approved Policy

The always-loaded policy is:

```text
Treat notation as a correctness boundary. Within a defined scope, use one
stable name for one concept and one meaning for one name. Define non-obvious
symbols, units, conventions, and namespaces before use; qualify collisions by
owner, layer, or namespace. When established vocabularies differ, state their
mapping and authority rather than silently renaming them. Resolve any plausible
ambiguity before designing, implementing, or testing.
```

The compact subagent rule is:

```text
Notation discipline: within a defined scope, one concept has one stable name
and one name has one meaning; define or qualify ambiguity before use.
```

## 3. Rationale

AGENTS.md is loaded into agent context as policy. Project-specific examples in that layer can anchor reasoning to the current architecture, make examples look exhaustive, or cause an agent to introduce irrelevant domain concepts into unrelated work. A policy should state the invariant and decision rule while leaving task-specific terminology to the relevant canon, ledger, code, and dependency documentation.

The phrase "within a defined scope" is deliberate. Different systems and dependencies may have established vocabularies, so global renaming is neither required nor always correct. The rule requires explicit mapping and qualification at boundaries instead of forcing unrelated scopes to share identifiers.

## 4. Application Boundary

Keep examples, incidents, and architecture-specific mappings in task-relevant documentation rather than the always-loaded policy. Read those details only when the current task depends on them. Do not treat the absence of examples in AGENTS.md as permission to ignore the notation rule; ambiguity still blocks design, implementation, or testing until it is resolved.

## Related Notes

- [DEC-022](DEC-022-consistent-unambiguous-notation.md) - initial detailed notation policy whose normative wording is superseded here.
- [DEC-021](DEC-021-actor-artifact-capability-operating-model.md) - task-specific operating-model boundaries that remain in the ledger rather than the always-loaded policy.
- [OBS-018](../observations/OBS-018-operating-model-contract-leakage.md) - project-specific evidence retained outside AGENTS.md.
- [documentation style guide](../../enhanced/style-guide.md) - frozen presentation and notation conventions for the design canon.
