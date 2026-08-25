---
doc_id: TST-005
title: Orthogonalization and generator invariants guarded by property tests
type: case-study
owner: research
status: resolved
version: 1.0
components: [3, 0]
tags: [test-mapping, orthogonalization, grammar]
source: "B3-P2b contract-test pass"
design: [STG-3-ORTHOGONALIZATION, STG-0-ALPHA-MINING]
code: [crates/alpha-core/src/orthogonalization.rs, crates/alpha-core/src/strategies/mining/alpha_generator.rs]
test: [residual_is_orthogonal_to_every_pool_column, candidate_inside_pool_span_is_fully_absorbed, exactly_anticorrelated_candidate_passes_through, empty_pool_returns_candidate_verbatim, same_seed_reproduces_identical_sequence, serialisation_is_idempotent_through_parser]
---

# TST-005 - Pool Admission and Mining Grammar Contract Tests

## 1. Mapping

For Component 3 the protected invariant is the normal-equations guarantee itself: the residual is orthogonal to every pool column, candidates inside the pool span vanish entirely, and an empty pool passes the candidate through verbatim - admission may only ever be earned by incremental value. For Component 0 mining reproducibility rests on two generator properties: identical seeds reproduce identical expression sequences, and serialisation is a fixed point of the parser so trial entries stay stable across re-serialisation.

## Related notes

- [STG-3-ORTHOGONALIZATION](../../enhanced/stages/stage-3-orthogonalization.md) - residual-only admission contract
- [STG-0-ALPHA-MINING](../../enhanced/stages/stage-0-alpha-mining.md) - grammar-guided generation contract
