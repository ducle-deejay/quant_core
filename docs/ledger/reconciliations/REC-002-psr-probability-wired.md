---
doc_id: REC-002
title: Full PSR-style spurious probability wired into the admission gate
type: reconciliation
owner: research
status: resolved
version: 1.0
components: [2]
tags: [evaluation, deflated-sharpe, amendment]
source: "verdict on OBS-004; owner approved wiring the full probability over removing the fields"
design: [STG-2-EVALUATION, CON-EV-TRIALS-THRESHOLDS]
code: [crates/alpha-core/src/evaluation/gates.rs]
test: [clean_candidate_passes_all_seven_checks, negative_skew_and_excess_kurtosis_raise_spurious_probability, shape_poisoned_candidate_clears_trial_threshold_but_fails_distribution_check]
---

# REC-002 - Full PSR-Style Spurious Probability Wired Into the Admission Gate

## 1. Verdict

Option A accepted. `evaluate_gate` now runs a seventh check computing `deflated_sharpe_probability` from the previously inert inputs. A candidate must satisfy `P(spurious) <= max_spurious_probability` (new `GateCriteria` field, default 0.05) alongside every earlier requirement. This completes plan item T013 in full.

## 2. Rationale

The expected-max threshold and the shape correction answer different questions - how high could the best of many luck trials climb versus how likely this specific result is fake given its own return distribution. Intraday futures returns routinely carry fat tails and skew, so skipping the shape layer would leave a known blind spot on the exact asset class the system trades. Cost of wiring was three lines of arithmetic over inputs already carried by every call site.

## 3. Semantics recorded

The observed Sharpe enters the probability function divided by the square root of the cross-trial variance (unit-variance convention documented on the function). For positive observed Sharpe, negative skew and kurtosis above normal raise the estimated spurious probability; the check compares against the significance ceiling with inclusive semantics.

## 4. Consequence

OBS-004 moves to resolved. Test mappings in [TST-002](../tests/TST-002-gate-contract-tests.md) extended with the three new tests. Interpretation note for the ledger: observation, reconciliation, and decision notes are immutable once resolved under rule M2; test-mapping notes act as living indexes and may be updated as their mapped test set grows.

## Related notes

- [OBS-004](../observations/OBS-004-gate-dead-inputs.md) - finding this verdict closes
