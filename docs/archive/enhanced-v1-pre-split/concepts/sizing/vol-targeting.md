---
doc_id: CON-SZ-VOL-TARGETING
title: Vol Targeting
type: specification
owner: research
status: approved
version: 1.1
components: [5]
tags: [sizing, risk]
aliases: ["Volatility Scaling", "Blended Forecast"]
source: "original stage-5 content + follow-up discussions (blended forecast, stress buffer, estimator lag)"
---

# Vol Targeting

## 1. Summary

p(t) = z(t) * (vol_target / vol_est). Confidence-scaled exposure inversely
proportional to measured volatility, holding realized account volatility near the
declared target. The industry-standard sizing rule for time-series strategies.

## 2. Why it is standard

Three justifications. PnL stays flat across volatility regimes - quiet markets
auto-lever, wild markets auto-delever. Statistics stay comparable across periods -
one unit for Sharpe and drawdown across eras. Risk managed proactively by
declaration rather than reaction.

## 3. Estimating vol_est properly

3.1 Blended forecast: short-window plus long-window EWMA with weight near one half.
Short alone whipsaws; long alone lags - and lag in risk estimation means size stays
large right after crashes.

3.2 Stress buffer: multiply the blend by one-plus-buffer after shocks, or take the
max against a historical high percentile - pre-paying the price of estimator lag.

3.3 High-frequency estimators in production: realized volatility from minute bars,
Yang-Zhang, bipower variation - robust to microstructure noise and jumps, reflecting
intraday reality instead of close-to-close.

3.4 Volatility floor: vol_est = max(vol_est, vol_min), preventing explosion as
vol_est approaches zero.

3.5 Gap adjustment: caps sized against historical overnight gaps. Vol targeting only
scales with continuous moves; overnight gaps and limit moves are outside its
jurisdiction - caps and kill switches cover those.

## 4. Worked example

Capital 500 million VND; contract notional 120 million at index 1200; target 15
percent annualized about 0.95 percent daily; measured 0.80 percent gives scale 1.19;
z = +1.2 gives p = 1.43, long five contracts, margin 108 million. Next day vol_est
1.3 percent: scale 0.73, p = 0.88, hold three contracts. The system disarms itself
with no human input.

## 5. Traps

Estimator lag after crashes (fix: blend plus buffer); tuning vol_target for prettier
backtests (target derives from real drawdown tolerance); believing vol targeting
protects against gaps (it does not); ignoring integer rounding on small accounts
where rounding error is a meaningful share of exposure.

---
## Links
- Up: [[stages/stage-5-position-construction.md]]
- Related: [[concepts/sizing/position-sizing-methods.md]], [[concepts/sizing/leverage-cap.md]], [[concepts/sizing/china-sizing-stack.md]],
  [[concepts/sizing/scaling-layer-separation.md]]
