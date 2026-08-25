---
doc_id: CON-SZ-CHINA-STACK
title: China Sizing Stack
type: specification
owner: research
status: approved
version: 1.1
components: [5]
tags: [sizing, china-practice]
aliases: ["Multiplicative Sizing Stack", "Ramp-Up Ladder"]
source: "follow-up discussion: what Chinese practitioners actually run for sizing"
---

# China Sizing Stack

## 1. Summary

Production sizing is a multiplicative stack, each factor owned by a different subsystem - not one algorithm. The complexity lies in operational discipline: independent ownership, pre-committed rules, calibration from live fills.

## 2. Specification

2.1 Stack anatomy:

```text
    p_final = clip( z * (vol_target / vol_est_HF)
    z           composite score
    vol_est_HF  high-frequency volatility estimate (see [[reference/notation.md]])
    m_drawdown / m_regime / m_rampup : overlay multipliers, each owned
                 by a separate subsystem (sections 2.3-2.7)
                    * m_drawdown * m_regime * m_rampup , -L , +L )
```


2.2 vol_est_HF: minute-bar realized volatility, or Yang-Zhang and bipower estimators robust to microstructure noise and jumps - never close-to-close daily EWMA; floored, horizons blended.

2.3 m_drawdown: the pre-committed multiplier table, owned by an independent risk team - alpha engineers cannot edit it. Organizational separation is the design decision keeping the mechanism alive mid-drawdown.

2.4 m_regime and event multipliers: small frozen lookup tables around known events - data releases, contract expiry, abnormal sessions - for moments estimators cannot react fast enough.

2.5 Cost-aware hysteresis: resizing fires only when expected gain exceeds round- trip cost - a no-trade zone around target. Garleanu-Pedersen logic bleeding into sizing; critical where costs eat basis points.

2.6 Learned sizing exists at top firms: models output trade intensity trained with cost penalties, supervised or reinforcement learning. Requires years of live fills and a trustworthy cost model - premature below institutional scale.

2.7 Ramp-up trust ladder after go-live: weeks one to four at twenty percent of target size verifying fill and slippage assumptions; month two at fifty percent if live-versus-backtest divergence holds; month three onward at full size; violations step back down. Bugs detonate at twenty percent size, not at full size.

2.8 Deliberately avoided: full Kelly (nobody trusts edge estimates that much; fractional Kelly survives only as sanity anchor for choosing vol_target); martingale families (retail trap, banned on every serious desk); naked fixed-fractional compounding (equity path fully hostage to market mood).

Minimal stack for this project: clip of z times vol ratio inside plus-minus L, plus no-trade zone, plus drawdown table, plus ramp-up ladder from go-live.

---
## Links
- Up: [[stages/stage-5-position-construction.md]]
- Related: [[concepts/sizing/vol-targeting.md]], [[concepts/combination/drawdown-overlay.md]], [[concepts/combination/meta-labeling.md]], [[concepts/sizing/position-sizing-methods.md]]
