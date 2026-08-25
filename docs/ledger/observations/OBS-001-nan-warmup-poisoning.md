---
doc_id: OBS-001
title: Warmup NaN silently flattened every time-series alpha
type: observation
owner: research
status: resolved
version: 1.0
components: [1]
tags: [simulation, nan, silent-failure]
source: "batch verification session on real VN30F1M data; discovered via survivor table showing Sharpe 0.00"
design: [STG-1-CANONICAL-SIM]
code: [crates/alpha-core/src/canonical/mapping.rs, crates/alpha-core/src/strategies/mining/operators.rs]
test: [metamorphic_warmup_nan_prefix_is_behaviorally_neutral, canonical_map_survives_warmup_nan_and_trades]
---

# OBS-001 - Warmup NaN Silently Flattened Every Time-Series Alpha

## 1. Summary

Rolling operators emit `f64::NAN` during their warmup window by documented contract. That single leading NaN block poisoned the EWMA recursion, then the running z-score accumulators, and finally forced the position to stay flat at zero for the entire sample. Every alpha whose expression contained a time-series operator measured Net Sharpe exactly 0.00 with zero cost drag and no error message of any kind.

## 2. Finding

The propagation chain had three silent stages. First, `ewma_smooth` seeded its recursion with `score[0]`, which was NaN through warmup, so the whole smoothed series became NaN. Second, `rolling_zscore` accumulated NaN into its running sums; because Rust's `f64::max` ignores NaN, `(NaN).max(0.0)` clamped the poisoned variance to a clean-looking 0.0, so every z-score evaluated to 0 without any signal. Third, the no-trade band never triggered and the position stayed flat forever.

The bug surfaced only after batch verification ranked survivors honestly: candidates that traded at all were pure-arithmetic drift artifacts such as linear terms in `close`, while every genuine operator-bearing alpha was inert. Cost drag of exactly 0.0 percent across an entire candidate set is the tell-tale signature worth remembering.

## 3. Consequence and resolution

Canonical mapping now sanitises its input before Step A; see [REC-001](../reconciliations/REC-001-sanitize-scores-amendment.md) for the accepted amendment to the Step A input contract. The regression guards are the warmup-NaN metamorphic test and the end-to-end trading test named in front matter.

## Related notes

- [STG-1-CANONICAL-SIM](../../enhanced/stages/stage-1-canonical-simulation.md) - frozen specification of the four-step canonical mapping
- [REC-001](../reconciliations/REC-001-sanitize-scores-amendment.md) - amendment this finding provoked
