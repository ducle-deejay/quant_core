---
doc_id: STG-5-POSITION-CONSTRUCTION
title: Component 5 - Position Construction
type: specification
owner: research
status: approved
version: 2.0
components: [5]
tags: [sizing, stage-hub]
source: "docs/original/pipeline_stages/05_position_construction.md + follow-up discussions (sizing taxonomy, cap derivation, exposure semantics, China sizing stack, meta-labeling). Reformatted per REF-STYLE."
---

# 5. Position Construction

## 1. Component contract

    INPUT : composite_score(t) from Component 4
            plus risk configuration: vol_target, leverage cap L, capital
    OUTPUT: target_position(t), a real number in multiples of capital notional

## 2. Summary

Component 5 is the border where risk starts to exist. It converts the composite
score - a dimensionless statement of direction and confidence - into a target
position measured against real capital. Every drawdown this system will ever
suffer passes through this gate, and the conversion must follow one uniform rule,
never day-by-day intuition.

Convention: p = 1.4 means exposure worth 1.4 times capital (fixed-notional
research convention; no compounding).

## 3. Specification

3.1 Core rule, volatility targeting:

    p(t) = z(t) * (vol_target / vol_est(t))
    z(t)        composite score at t (Component 4 output)
    vol_target  declared volatility target, converted to bar frequency
    vol_est(t)  estimated volatility at t; estimation procedure in 3.4

Position scales with forecast confidence z(t) and inversely with measured asset
volatility vol_est(t). Three justifications: PnL stays flat across volatility
regimes; performance statistics stay comparable across periods; risk is managed
proactively by declaration ("the account moves about fifteen percent per year")
rather than reactively.

3.2 Leverage cap:

    p(t) = clip(p(t), -L, +L)
    L           leverage cap policy in multiples of capital
                (derivation of L_max: [[concepts/sizing/leverage-cap.md]])

Here L reflects physical constraints: VN30F1M margin requirements around 15 to 18
percent, per-account position limits, and overnight gap risk.
[[concepts/sizing/leverage-cap.md]] derives L_max as the minimum of margin feasibility, gap stress,
and regulatory limits, less a safety factor.

3.3 Whole-contract conversion. Positions are real numbers in research; the
exchange accepts integers. Rounding residual handling belongs to Component 6;
this component only marks the boundary.

3.4 Estimation of vol_est. Blend short-window and long-window EWMA (weights near
one half); apply a volatility floor; upgrade to minute-bar realized volatility or
Yang-Zhang / bipower estimators in production; adjust caps for historical
overnight gaps, which volatility targeting does not cover.

3.5 Family multiplier integration. The drawdown-overlay multiplier m in [0, 1]
multiplies the vol-targeted position: p_final = p_vol_targeted * m. The two
layers meet here but keep separate owners.

## 4. Worked example

    Capital 500 million VND; VN30F1M at 1200 points; contract notional 120 million
    vol_target 15 percent annualized, about 0.95 percent daily
    vol_est measured 0.80 percent daily -> scale 0.95/0.80 = 1.19
    Composite z = +1.2 -> p_target = 1.43 x capital notional
    Contracts = 1.43 * 500 / 120 = 5.9 -> long 5 contracts
    Margin check: 5 x 120M x 18 percent = 108 million VND (21 percent of capital)

Next day vol_est jumps to 1.3 percent: scale drops to 0.73, p falls to 0.88, hold
three contracts. The system disarms itself without anyone pressing anything.

## 5. Failure modes

5.1 Volatility estimator lag after crashes - size stays large exactly when danger
peaks; defend with short-window blending and a stress buffer.
5.2 Tuning vol_target for prettier backtests - planned suicide; the target comes
from real drawdown tolerance.
5.3 Believing vol targeting protects against overnight gaps or limit moves - it
does not; caps and kill switches cover those.
5.4 Ignoring integer rounding on small accounts - at one to three contracts the
rounding error is a meaningful share of exposure; include it in backtests.
5.5 Stacking volatility scaling across three layers - then no single knob controls
risk and effective leverage is undeclared ([[concepts/sizing/scaling-layer-separation.md]]).

## 6. Production practice notes

The Chinese multiplicative sizing stack (HF volatility estimator, independent
drawdown multiplier team, regime/event multipliers, cost-aware hysteresis,
learned sizing at top firms, ramp-up ladder) lives in [[concepts/sizing/china-sizing-stack.md]];
method taxonomy incl. Kelly and ATR variants in [[concepts/sizing/position-sizing-methods.md]]; where
meta-labeling slots in as a learned sizing multiplier in [[concepts/combination/meta-labeling.md]];
exposure semantics and the alpha-vs-portfolio scaling separation in
[[concepts/sizing/scaling-layer-separation.md]].

---
## Related notes
- [[stages/stage-4-combination.md]], [[stages/stage-6-trade-scheduling.md]]
- [[concepts/sizing/vol-targeting.md]], [[concepts/sizing/leverage-cap.md]], [[concepts/sizing/china-sizing-stack.md]],
  [[concepts/sizing/position-sizing-methods.md]], [[concepts/sizing/scaling-layer-separation.md]], [[concepts/combination/meta-labeling.md]]
