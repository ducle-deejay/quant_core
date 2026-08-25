---
doc_id: CON-MIN-IC-LADDER
title: IC Metrics and the Horizon Ladder
type: specification
owner: research
status: approved
version: 1.1
components: [0, 2]
tags: [mining, evaluation, ic]
source: "discussion: IC computation; horizon selection principles"
---

# IC Metrics and the Horizon Ladder

## 1. Summary

Mining measures forecast quality directly as correlation between score and future return - no order simulation. The horizon ladder reveals how long an edge lives; its shape sets holding period, gate metric, turnover budget, and monitoring windows.

## 2. Specification

2.1 Computation. IC(h) = correlation of score at t with cumulative return from t+1 through t+h. Rolling window (for example 480 bars), aggregated into daily blocks, reported as mean with block t-statistic. Rank IC (Spearman) preferred for outlier robustness. No backtest at this layer - stateless scores make it fully vectorized.

2.2 Ladder selection. One-minute data uses horizons {1, 2, 3, 5, 10, 15, 30, 60}; five-minute data {1, 2, 3, 6, 12, 24, 48}. Geometric spacing because edge lifetimes span orders of magnitude.

2.3 Three principles behind the ladder. First, the purpose is locating where IC(h) crosses zero - that decay horizon is the maximum sensible holding period. Second, statistical power decays with h: independent observations shrink linearly (one-minute data at h=60 leaves about five independent blocks per session), so the upper cap comes from statistics, rarely beyond one session. Third, h=1 stays in even when untradeable: it is the information ceiling and decay reference.

2.4 Cross-frequency comparisons use time units, never bar counts (h=60 on one-minute data equals h=12 on five-minute). Overlapping forward returns inflate naive t-statistics; use daily blocks or Newey-West correction.

2.5 Shape reading. IC rising with horizon (0.022 to 0.055 to 0.085) means a persistent, cost-survivable signal. IC spiking at h=1 then dying means ultra-short edge that costs will murder. Both shapes appear in [seed-alpha-demo](../../case-studies/seed-alpha-demo.md).

---
## Related notes
- Up: [stage-0-alpha-mining](../../stages/stage-0-alpha-mining.md), [stage-2-evaluation-screening](../../stages/stage-2-evaluation-screening.md)
- Related: [ga-machinery](ga-machinery.md), [trial-count-and-thresholds](../evaluation/trial-count-and-thresholds.md)
