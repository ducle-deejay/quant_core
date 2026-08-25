---
doc_id: TST-001
title: Canonical metrics guarded by known-answer and metamorphic tests
type: case-study
owner: research
status: resolved
version: 1.0
components: [1]
tags: [test-mapping, metrics]
source: "B3-P1a contract-test pass"
design: [STG-1-CANONICAL-SIM]
code: [crates/alpha-core/src/canonical/metrics.rs]
test: [sharpe_known_answer_hand_computed, sharpe_scale_invariant_and_sign_mirror, max_drawdown_known_answer, max_drawdown_never_positive_and_zero_when_monotone_rising, rank_ic_perfect_monotone_relation_scores_one, rank_ic_anti_monotone_relation_scores_minus_one]
---

# TST-001 - Canonical Metrics Contract Tests

## 1. Mapping

The stage-1 dossier statistics are protected by eight tests in `canonical::metrics::tests`. Sharpe is pinned to a hand-computed value and to scale/sign metamorphic relations; maximum drawdown to an exact peak-to-trough answer plus a non-positivity invariant; the rank IC block to perfect and anti-monotone Spearman extremes. No observation provoked this batch - the tests encode formulas straight from the frozen canon.

## Related notes

- [STG-1-CANONICAL-SIM](../../enhanced/stages/stage-1-canonical-simulation.md) - protected contract owner
