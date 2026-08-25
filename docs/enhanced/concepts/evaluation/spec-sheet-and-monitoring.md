---
doc_id: CON-EV-SPEC-SHEET
title: Spec Sheet and Live Monitoring
type: specification
owner: research
status: approved
version: 1.1
components: [2]
tags: [evaluation, monitoring]
aliases: ["Spec Sheet", "Holding Period Estimation", "Expected Sharpe Shrinkage"]
source: "follow-up discussions: spec-sheet purposes; divergence example; holding-period estimation"
---

# Spec Sheet and Live Monitoring

## 1. Summary

The spec sheet is the contract between research and operations written before pool admission: expected holding period h_star, expected net Sharpe, capacity, regime dependence, kill criteria. It converts live divergence from a feeling into a measurement.

## 2. Specification

2.1 Four purposes. Baseline for live monitoring - without written expectations, normal bad luck and dead edge are indistinguishable. Kill criteria pre-committed before emotions exist, same mechanism as a stop-loss placed at entry. Input to Stage 4 allocation. Reference for post-mortems.

2.2 Holding period, two independent views taken jointly. Information view: signal-autocorrelation halflife, where correlation of score with its own lagged self crosses one half (Seed A: about 32 bars). Operational view: measured cadence of canonical position changes (Seed A: about 17 bars). A mismatch is itself a finding - information said 32 while the harness traded every 17, so the band was too tight; widening it from 0.35 to 0.50 cut turnover from about 1670 to about 1100 per year while raising net Sharpe.

h_star then feeds five consumers: which horizon's IC is the gate metric; target trade cadence (bars per day over h_star); annual turnover budget; live monitoring window lengths; Stage 4 diversification classes.

2.3 Expected Sharpe is never the raw walk-forward number. Take the lower bound of a block-bootstrap confidence interval; shrink toward the surviving-family mean (stronger shrinkage for short samples and high trial counts); subtract ten to thirty percent for impact and crowding at real size.

2.4 Divergence reading example. Spec: Sharpe 1.2, IC about 0.05, c = 0.6 basis points, kill line as above. After sixty live sessions: cumulative PnL plus 0.05 percent against expected plus 0.9 percent - inside luck range given dispersion about 1.5 percent. But rolling IC at +0.008 with eight negative days in ten is a genuine alarm, and measured slippage at 1.8 times model means part of the shortfall is self-inflicted mis-calibration. Three causes, three responses: noise means wait; cost drift means fix the model; IC collapse means the kill criteria fire.

---
## Links
- Up: [stage-2-evaluation-screening](../../stages/stage-2-evaluation-screening.md)
- Related: [post-mortem](post-mortem.md), [trial-count-and-thresholds](trial-count-and-thresholds.md), [divergence-monitoring](../risk/divergence-monitoring.md)
