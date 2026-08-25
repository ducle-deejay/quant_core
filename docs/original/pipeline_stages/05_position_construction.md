# Stage 5 — Position Construction

> Provenance: faithful English rendering of the first full presentation of
> Stage 5 (vol targeting, leverage cap, worked example). Follow-up Q&A
> (sizing-method taxonomy, exposure terminology, the Chinese multiplicative
> stack, meta-labeling placement) is not included here.

Stage 5 is where the composite score finally becomes a number that carries
money. If Stages 0→4 are the inference world, Stage 5 is **the border where risk
starts to be created** — every drawdown this system will ever suffer passes
through this gate.

## The problem this stage solves

The composite score from Stage 4 answers only *"which direction, and with what
confidence?"* — it has not answered the only question the market cares about:
**"how large a position?"**. The same score z = +1.2 is worth 1 contract or 50
depending on two things outside any alpha's scope: the asset's current
volatility and the risk budget you accept. Translating "confidence" into "bet
size" is the entire content of this stage — and it must be **one uniform rule**,
not day-by-day intuition.

## Contract

```
INPUT : composite_score(t)  [from Stage 4]
        + risk configuration: target volatility, leverage cap, capital
OUTPUT: target_position(t)  — a real number in units of "× notional of capital"
        (fixed-notional convention: p = 1.4 means exposure worth 1.4× capital)
```

## Mechanics — three transforms

### Step 1 — Vol targeting: the heart of this stage

```
p_t = z_t × (σ_target / σ̂_t)
```

Reading: position scales with confidence (`z_t`) and **inversely with the
asset's measured volatility** (`σ̂_t` = estimated volatility, typically EWMA over
a few weeks, or realized volatility computed from intraday bars).

Three reasons this is the industry-standard rule:

1. **PnL stays flat across volatility regimes** — quiet markets automatically
   get larger size, wild markets smaller, so the earnings stream does not lurch
   with the market's mood;
2. **Statistics stay comparable across periods** — Sharpe ratios and drawdowns
   of different eras share one unit of measure;
3. **Risk is managed proactively** — you declare "I want the account moving
   ~15%/year", and the system implements it.

### Step 2 — Leverage cap

```
p_t = clip(p_t, −L, +L)
```

But here the cap no longer guards against outlier scores (z is already clean
from the harness) — it reflects **physical constraints**: VN30F1M margin
requirements (~15–18%), per-account position limits, and overnight gap risk.
Quick check formula:

```
max_contracts = capital × L_max / (price × multiplier 100,000 × margin_rate)
```

### Step 3 — Conversion to whole contracts

Position is a real number in research, but the exchange accepts integers — the
rounding residual belongs to Stage 6; here we only mark the boundary.

## Worked example, end to end

```
Capital              = 500 million VND
VN30F1M              = 1,200 points → 1 contract = 120 million notional
Target volatility    = 15%/year     → ≈ 0.95%/day
Measured σ̂_t (EWMA)  = 0.80%/day    → scale = 0.95/0.80 = 1.19
Composite score      = z = +1.2

p_target = 1.2 × 1.19 = 1.43 × notional
Contracts = 1.43 × 500M / 120M = 5.9  → long 5 contracts
Margin check: 5 × 120M × 18% = 108 million ✓ (21% of capital, comfortable)
```

Next day, if σ̂ jumps to 1.3% (wild market): scale drops to 0.73,
`p = 0.88`, hold only 3 contracts — the system disarms itself **without anyone
pressing anything**. That is the entire value of vol targeting.

## What practitioners add at this layer

| Technique | Content | Why |
|---|---|---|
| **Blended volatility forecast** | Blend short-window + long-window EWMA, or realized volatility from high-frequency data | Pure EWMA reacts too slowly after shocks |
| **Volatility floor** | `σ̂_t = max(σ̂_t, σ_min)` | Prevents σ̂ ≈ 0 from exploding position size |
| **Gap-adjusted sizing** | Cap computed against historical overnight gaps, not just close-to-close volatility | An intraday strategy holding overnight: tomorrow's gap does not care about today's intraday vol |
| **Regime-aware target** | Lower target volatility when the regime is uncertain (transitions, widening spreads) | Vol targeting protects against *measured* volatility, not against *surprise* |
| **Family multiplier integration** | Multiply by `m ∈ [0, 1]` from the Stage 4 drawdown overlay | Where the two layers meet: `p_final = p_vol_targeted × m` |

A design warning: do not mix scaling layers. Alpha-level normalization (inside
the harness) makes alphas comparable to each other; portfolio-level vol targeting
(this stage) sets real exposure against capital. Both legitimately coexist
because they solve different problems — but if you find volatility scaling stacked
three layers deep, that is redundant code breeding bugs.

## Traps characteristic of this stage

1. **Volatility estimator lag** — after a crash, σ̂ needs days to fully reflect
   reality, so size stays large exactly when danger peaks. Fix: blend short +
   stress buffer;
2. **Tuning target volatility for a prettier backtest** — raising it to 25%/year
   to flatter the Sharpe ratio is planned suicide; the target must come from your
   real drawdown tolerance, never from paper performance;
3. **Forgetting vol targeting does not save you from gaps** — it scales with
   continuous volatility; overnight gaps and limit moves are natural disasters
   outside its jurisdiction — only caps and kill switches cover those;
4. **Ignored integer rounding** — with small capital (1–3 contracts), rounding
   error is a meaningful % of exposure; put it inside the backtest, don't leave
   it as an afterthought.

## Handoff to Stage 6

Output: the `target_position(t)` series — "what exposure should be". But between
target and reality there is always distance: filling costs money, slicing takes
time, markets move. **Stage 6 — trade scheduling** is the craft of traveling
from current position to target position at minimal cost — where the composite
score finally touches the exchange.

The discussion therefore proceeded to Stage 6.
