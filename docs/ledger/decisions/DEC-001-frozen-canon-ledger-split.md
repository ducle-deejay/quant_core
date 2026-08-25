---
doc_id: DEC-001
title: Frozen canon plus ledger as the single living layer
type: decision
owner: research
status: resolved
version: 1.0
components: []
tags: [governance, documentation, drift-control]
source: "discussion: docs reorganization for drift prevention, anchored on the enhanced vault"
design: []
code: [docs/ledger]
test: []
---

# DEC-001 - Frozen Canon Plus Ledger as the Single Living Layer

## 1. Summary

Documentation drift is solved structurally, not by discipline. The design canon under docs/enhanced is frozen permanently and states intent. The ledger under docs/ledger is the only place where project knowledge continues to be written, linked to the canon by doc_id references in both directions of traceability.

## 2. Decision

Do not edit any file under docs/enhanced from this point forward. Record every disagreement between stated design and observed behaviour as an observation note, judge it in a reconciliation note, and map every protecting test in a test-mapping note. Follow rules M1 through M4 defined in the ledger [HOME](../HOME.md).

## 3. Consequences

The cost is one extra note per contract-touching change. The benefit is that drift becomes visible debt (the sweep script's open count) instead of silent divergence between what the documents promise and what the binary does. Tests are derived from canon intent, never from code behaviour; behaviour only nominates topics for reconciliation.

## Related notes

- [HOME](../HOME.md) - ledger charter and index
- [style-guide](../../enhanced/style-guide.md) - presentation standard both layers share
