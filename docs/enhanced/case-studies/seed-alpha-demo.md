---
doc_id: CASE-SEED-DEMO
title: Case Study - Seed Alpha Demo
type: case-study
owner: research
status: approved
version: 1.1
components: [0, 1, 2]
tags: [case-study, seed-alpha, demo]
source: "discussion: seed illustration with runnable script; script at research/seed_alpha_demo.py"
---

# Case Study - Seed Alpha Demo

## 1. Summary

Two hand-written seeds over OHLCV plus ten-level book depth ran through a canonical harness on synthetic data. One survived costs; the prettier IC died by turnover - demonstrating every Stage 1 and Stage 2 lesson in miniature.

## 2. Data contract

OHLCV plus book depth: ten bid and ask levels with size close and sum plus price close, sixty-five columns total; five thousand seven hundred one-minute bars across twenty sessions of two hundred eighty-five bars. Synthetic world: latent order-book imbalance following an AR(1) process with halflife about forty-five bars partially driving forward returns (continuation), plus a lag-one micro-bounce so a reversion seed has something to eat.

## 3. The two seeds

Seed A, book imbalance continuation. Hypothesis: heavy bid book means resting buying pressure, so price continues. Imbalance is the normalized difference of summed bid and ask sizes over fifteen bars; score is the rolling z-score of its EWMA smoothing.

Seed B, price bounce reversion. Hypothesis: fast deviation from the five-bar mean snaps back. Deviation is close over short mean minus one; score is the negated rolling z-score of its smoothed deviation.

Both pass through one canonical harness: EWMA eight, rolling z-score over four hundred eighty bars, no-trade band 0.35, cap plus-minus two, cost per side half-spread one basis point plus fee 0.2 basis points of notional.

## 4. Results

```text
    seed A book_imbalance_cont : IC@1 0.022 (t=4.5), IC@5 0.055, IC@15 0.085
                                 Sharpe gross 5.43, net 3.41, turnover 1668x per year
    seed B price_bounce_rev    : IC@1 0.061 (t=11.5), IC@5 0.043, IC@15 0.010
                                 Sharpe gross -1.43, net -11.9, turnover 7296x per year
```

## 5. Lessons

5.1 The IC profile tells character. Seed A's IC rises with horizon - persistent, information accumulates, cost-survivable. Seed B spikes at h=1 then dies - ultra-short edge.

5.2 Cost is the judge. Seed B had the better one-bar IC yet net Sharpe minus eleven point nine: turnover above seven thousand times per year eats everything. The harness catches this at compile time.

5.3 Positive IC with negative PnL happens. Harness smoothing plus band make positions stale relative to a one-bar edge - decision lag is part of the alpha, so IC must be measured through the deployment pipeline, never raw.

5.4 Pool preview. Daily-PnL correlation between seeds was minus 0.29 - perfect complementarity if B survived costs. It died at screening; the pool kept only A.

## 6. Caveat and reuse

Absolute Sharpe levels are artifacts of a single-factor synthetic world; read shapes, not magnitudes. With real VN30F1M data only the loader changes. Runnable: python3 research/seed_alpha_demo.py (numpy and pandas only; same conventions as research/alpha_ic_demo.py).

How GA consumes this: each seed is a set of subtrees (imb10, ewma-of-eight, ts_zscore-window-480). Crossover swaps subtrees between seeds; mutation changes operators or params; the results table above is the selection pressure.

---
## Related notes
- [stage-0-alpha-mining](../stages/stage-0-alpha-mining.md)
- [formulaic-alpha-and-seeds](../concepts/mining/formulaic-alpha-and-seeds.md), [ic-metrics-and-horizon-ladder](../concepts/mining/ic-metrics-and-horizon-ladder.md), [canonical-mapping](../concepts/simulation/canonical-mapping.md), [no-trade-band](../concepts/simulation/no-trade-band.md)
