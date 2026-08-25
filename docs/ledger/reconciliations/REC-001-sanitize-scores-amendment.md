---
doc_id: REC-001
title: Step A input contract amended to require finite scores
type: reconciliation
owner: research
status: resolved
version: 1.0
components: [1]
tags: [simulation, amendment, contract]
source: "verdict on OBS-001; accepted as an evolution of the canon rather than a code defect"
design: [STG-1-CANONICAL-SIM]
code: [crates/alpha-core/src/canonical/mapping.rs]
test: [sanitize_leading_nan_seeded_from_first_finite, sanitize_interior_nan_carries_forward, sanitize_all_nan_maps_to_zeros, sanitize_clean_input_unchanged]
---

# REC-001 - Step A Input Contract Amended to Require Finite Scores

## 1. Summary

The frozen canon specifies the canonical mapping over score series without stating how non-finite values are handled. Operator warmup makes leading NaN unavoidable for any expression containing a rolling operator, so the omission left the harness one interpretation away from silent flattening - which is exactly what happened (see [OBS-001](../observations/OBS-001-nan-warmup-poisoning.md)).

## 2. Verdict

The code behaviour after the fix is declared an ACCEPTED AMENDMENT to the canon input contract, not a deviation to be reverted. The amended contract reads:

```text
    Step A input   score series must be finite; canonical_map sanitises
                   first with the following semantics:
    leading NaN    replaced by the first finite value, keeping the alpha
                   flat through its own operator warmup
    interior NaN   carry the last finite value forward
    all-NaN        maps to an all-zero flat position
```

## 3. Rationale

Two alternatives were rejected. Dropping the warmup region from evaluation would change every metric window and silently shorten history per candidate. Emitting zeros during warmup would distort the trailing statistics of Step B once windows overlap the warmup zone. Forward-fill keeps the alpha genuinely flat while preserving window integrity, and matches the backfill convention already available among the mining operators.

## 4. Consequence

The frozen canon text stays untouched; this note and its tests are the authoritative record of the amendment. Any future change to sanitisation semantics supersedes this note under rule M2.

## Related notes

- [OBS-001](../observations/OBS-001-nan-warmup-poisoning.md) - the finding that provoked this verdict
- [STG-1-CANONICAL-SIM](../../enhanced/stages/stage-1-canonical-simulation.md) - frozen specification of Steps A through D
