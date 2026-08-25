---
doc_id: OBS-005
title: Duplicate rank_ic_block name with different statistics and a mislabeled doc comment
type: observation
owner: research
status: triaged
version: 1.0
components: [2]
tags: [evaluation, naming, rank-ic, pearson]
source: "contract-test pass over evaluation/ic_ladder.rs during B3-P1c; canon cross-check against the IC metrics concept note"
design: [CON-MIN-IC-LADDER]
code: [crates/alpha-core/src/evaluation/ic_ladder.rs, crates/alpha-core/src/canonical/metrics.rs]
test: []
---

# OBS-005 - Duplicate rank_ic_block Name With Different Statistics

## 1. Summary

Two public functions share the name `rank_ic_block` in different modules and compute different statistics. The canonical/metrics version is a whole-sample Spearman (rank-transformed Pearson) returning a pair count. The evaluation/ic_ladder version computes plain Pearson per daily block and returns mean IC plus block t-statistic. Its own doc comment says "Rank IC" while no rank transform exists in its body.

## 2. Finding

The frozen canon states Rank IC with Spearman is preferred for outlier robustness - preferred, not mandated - so the Pearson implementation does not violate the canon outright. Two genuine problems remain. First, one name carries two meanings across the codebase, which is exactly the confusion class the notation registry's Rule A exists to prevent, applied to function names. Second, the ic_ladder doc comment mislabels a Pearson statistic as Rank IC, so any reader trusting the comment inherits a wrong belief about outlier sensitivity.

## 3. Proposed verdicts (triaged, decision open)

- Option A: rename the ic_ladder function to `pearson_ic_block` and correct its doc comment; cheapest, fully honest, keeps both statistics available.
- Option B: implement the rank transform inside ic_ladder to honour the canon preference for Spearman; aligns behaviour with the stated preference at small CPU cost.

Either resolution closes this note under M2 together with a test-mapping note for the five contract tests added during B3-P1c.

## Related notes

- [CON-MIN-IC-LADDER](../../enhanced/concepts/mining/ic-metrics-and-horizon-ladder.md) - canon definition of IC computation and the ladder
