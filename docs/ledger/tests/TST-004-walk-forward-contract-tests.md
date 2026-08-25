---
doc_id: TST-004
title: Walk-forward stability guarded by regime-shift tests
type: case-study
owner: research
status: resolved
version: 1.0
components: [2]
tags: [test-mapping, walk-forward, stability]
source: "B3-P2a contract-test pass"
design: [STG-2-EVALUATION]
code: [crates/alpha-core/src/evaluation/walk_forward.rs]
test: [hand_computed_two_block_known_answer, stationary_positive_edge_reports_all_blocks_profitable, regime_shift_is_detected_as_collapsing_stability, trailing_remainder_days_are_excluded_not_partial_blocks, insufficient_input_returns_neutral_empty_result, zero_variance_block_scores_zero_not_infinity]
---

# TST-004 - Walk-Forward Contract Tests

## 1. Mapping

Six tests encode the stability contract: a hand-computed two-block answer pins the arithmetic; a stationary edge must report every block profitable while a mid-series regime break must collapse positive share to half and poison the worst block Sharpe; trailing days never form partial blocks; degenerate inputs return neutral values with zero-variance blocks reported as Sharpe zero rather than infinity. No observation provoked this batch - intent came straight from the canon.

## Related notes

- [STG-2-EVALUATION](../../enhanced/stages/stage-2-evaluation-screening.md) - protected contract owner
