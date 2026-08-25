---
doc_id: OBS-004
title: Gate input carries skewness, kurtosis, sample length that the gate ignores
type: observation
owner: research
status: resolved
version: 1.0
components: [2]
tags: [evaluation, deflated-sharpe, unfinished-wiring]
source: "contract-test pass over evaluation/gates.rs during B3-P1b; cross-checked deflated_sharpe.rs API"
design: [STG-2-EVALUATION, CON-EV-TRIALS-THRESHOLDS]
code: [crates/alpha-core/src/evaluation/gates.rs]
test: []
---

# OBS-004 - Gate Input Carries Skewness, Kurtosis, Sample Length That the Gate Ignores

## 1. Summary

`evaluate_gate` applies the expected-maximum-under-null deflation (`deflated_threshold(n_eff, variance)`), which matches the canon's rule that admission thresholds rise with trial count. However, `GateInput` declares three fields the evaluation never reads: `skewness`, `kurtosis`, and `sample_length_bars`. The full PSR-style correction implemented in `deflated_sharpe_probability(observed_sharpe, n_trials, skewness, kurtosis, sample_length)` is not wired into the gate.

## 2. Finding

The two deflation mechanisms answer different questions. The wired threshold asks "how high could the best of N zero-skill trials climb". The unwired probability asks "how likely is this observed Sharpe spurious once its own return distribution shape (skewness inflates it, heavy kurtosis deflates it) and sample length are accounted for". A candidate with heavily skewed daily returns can clear the first check while failing the second - and today nothing would notice.

This corresponds to pending plan item T013 in docs/plan-v2.md. The wiring is half done: threshold variant integrated, probability variant not. The dead fields are the visible seam of that half-finish.

## 3. Proposed verdicts (triaged, decision open)

- Option A: wire `deflated_sharpe_probability` as a seventh gate check using the already-carried inputs, making T013 genuinely complete.
- Option B: remove the three dead fields from `GateInput` if the shop decision is that expected-max deflation suffices for this replication stage.

Either resolution closes the note under M2. Until then the fields remain documented as inert at every call site by the source comment added in gates.rs.

## Related notes

- [REC-002](../reconciliations/REC-002-psr-probability-wired.md) - RESOLVED by this verdict: probability wired as seventh gate check
- [STG-2-EVALUATION](../../enhanced/stages/stage-2-evaluation-screening.md) - frozen specification of admission gates
- [trial-count-and-thresholds](../../enhanced/concepts/evaluation/trial-count-and-thresholds.md) - canon description of dynamic thresholds
