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
test: [single_trial_ledger_leaves_only_fixed_limits, threshold_rises_strictly_with_effective_trials, marginal_alpha_survives_fresh_registry_dies_in_crowded_one, every_fixed_limit_enforced_independently, sharpe_comparison_uses_geq_semantics_at_boundary]
---

# TST-002 - Admission Gate Contract Tests

## 1. Mapping

Five tests pin the gate's two-layer promise. The deflation layer: thresholds rise strictly with effective trial count, and a marginal candidate passes a fresh registry yet dies in a crowded one - the canon's core anti-overfitting rule made executable. The engineering layer: each fixed limit fails the candidate independently with exactly one failing check reported. Provoked in part by [OBS-004](../observations/OBS-004-gate-dead-inputs.md), whose dead-input seam remains open for decision.

## Related notes

- [OBS-004](../observations/OBS-004-gate-dead-inputs.md) - unwired PSR probability inputs, decision open
