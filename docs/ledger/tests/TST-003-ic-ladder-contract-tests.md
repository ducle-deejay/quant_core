---
doc_id: TST-003
title: IC horizon ladder guarded by lead-lag world tests
type: case-study
owner: research
status: resolved
version: 1.0
components: [2]
tags: [test-mapping, ic-ladder]
source: "B3-P1c contract-test pass"
design: [CON-MIN-IC-LADDER]
code: [crates/alpha-core/src/evaluation/ic_ladder.rs]
test: [perfect_lead_lag_scores_near_one_with_strong_tstat, mirrored_score_mirrors_mean_ic_and_tstat_sign, horizon_ladder_reports_each_requested_horizon_in_order, short_series_yields_zero_blocks_and_neutral_output, constant_score_within_every_block_is_reported_neutral]
---

# TST-003 - IC Ladder Contract Tests

## 1. Mapping

A deterministic lead-lag world (return at t+1 built from score at t plus a slow wobble) pins mean IC near one with a strong block t-statistic, sign mirroring, correct horizon attachment across ladder rungs, and neutral output for degenerate inputs. Provoked by [OBS-005](../observations/OBS-005-duplicate-rank-ic-name.md), resolved by [REC-003](../reconciliations/REC-003-spearman-upgrade.md): the block statistic is now genuine Spearman, and the fact that all five tests pass unchanged across that upgrade is itself evidence the switch preserved screening semantics.

## Related notes

- [REC-003](../reconciliations/REC-003-spearman-upgrade.md) - verdict that upgraded the statistic
