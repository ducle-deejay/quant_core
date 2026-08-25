---
doc_id: REC-003
title: IC ladder upgraded to true Spearman, name kept
type: reconciliation
owner: research
status: resolved
version: 1.0
components: [2]
tags: [evaluation, rank-ic, spearman, amendment]
source: "verdict on OBS-005; owner approved implementing the canon preference over renaming"
design: [STG-2-EVALUATION, CON-MIN-IC-LADDER]
code: [crates/alpha-core/src/evaluation/ic_ladder.rs]
test: [perfect_lead_lag_scores_near_one_with_strong_tstat, mirrored_score_mirrors_mean_ic_and_tstat_sign, horizon_ladder_reports_each_requested_horizon_in_order, short_series_yields_zero_blocks_and_neutral_output, constant_score_within_every_block_is_reported_neutral]
---

# REC-003 - IC Ladder Upgraded to True Spearman, Name Kept

## 1. Verdict

Option B accepted. `ic_ladder::rank_ic_block` now rank-transforms score and forward return within each block before correlating - genuine Spearman - so the function name and its doc comment finally describe what the code computes. The canon preference for Rank IC on outlier-robustness grounds is now honoured in behaviour, not just prose.

## 2. Rationale

Renaming would have frozen an outlier-sensitive Pearson statistic into the screening funnel permanently. Financial minute data contains enough extreme bars for a single session to dominate a raw-moment correlation; the rank transform costs one sort per block (about 239 bars each) against the batch executor's seconds-scale budget. Both functions named `rank_ic_block` are now rank-based, restoring one-name-one-meaning across the codebase.

## 3. Semantics recorded

Blocks where either side has no dispersion are skipped entirely: ranking a constant series would invent arbitrary order out of sort stability, so the degenerate block yields no information rather than a fake statistic. Ties keep the position-order convention already used by `canonical::metrics`, so both rank transforms behave identically.

## 4. Consequence

OBS-005 moves to resolved. The five contract tests from B3-P1c pass unchanged after the upgrade - the lead-lag world is monotone-dominant, so value correlation and rank correlation agree there - which doubles as evidence the switch did not disturb screening semantics.

## Related notes

- [OBS-005](../observations/OBS-005-duplicate-rank-ic-name.md) - finding this verdict closes
