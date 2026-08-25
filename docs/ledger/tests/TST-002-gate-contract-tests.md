---
doc_id: TST-002
title: Admission gate guarded by deflation and fixed-limit tests
type: case-study
owner: research
status: resolved
version: 1.0
components: [2]
tags: [test-mapping, gates, deflated-sharpe]
source: "B3-P1b contract-test pass"
design: [STG-2-EVALUATION, CON-EV-TRIALS-THRESHOLDS]
code: [crates/alpha-core/src/evaluation/gates.rs]
test: [single_trial_ledger_leaves_only_fixed_limits, threshold_rises_strictly_with_effective_trials, marginal_alpha_survives_fresh_registry_dies_in_crowded_one, every_fixed_limit_enforced_independently, sharpe_comparison_uses_geq_semantics_at_boundary, clean_candidate_passes_all_seven_checks, negative_skew_and_excess_kurtosis_raise_spurious_probability, shape_poisoned_candidate_clears_trial_threshold_but_fails_distribution_check]
---

# TST-002 - Admission Gate Contract Tests

## 1. Mapping

Eight tests pin the gate's three-layer promise. The trial-count layer: thresholds rise strictly with effective trials, and a marginal candidate passes a fresh registry yet dies in a crowded one. The engineering layer: each fixed limit fails the candidate independently with exactly one failing check reported. The distribution-shape layer (added by [REC-002](../reconciliations/REC-002-psr-probability-wired.md)): a candidate whose returns carry hostile skew and kurtosis can clear the trial threshold yet fail the spurious-probability check, while negative skew and excess kurtosis demonstrably raise that probability. Provoked originally by [OBS-004](../observations/OBS-004-gate-dead-inputs.md), now resolved.

## Related notes

- [REC-002](../reconciliations/REC-002-psr-probability-wired.md) - verdict that added the seventh check
