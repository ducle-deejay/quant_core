# Stage 6 — Trade Scheduling

> Provenance: faithful English rendering of the first full presentation of
> Stage 6. Follow-up Q&A is not included here.

Stage 6 — the stage where the system finally touches the real market. Everything
from Stage 0 to here produces only one sentence: *"what exposure should be"*.
This stage answers *"how do I get there at the cheapest price"* — and it is the
only layer where a single line of buggy code loses money in the present moment,
not through some backtest.

## The problem this stage solves

Between `target_position` and `current_position` there is always a gap, and
bridging it costs three kinds of money at once:

- **Explicit cost**: fees + spread when crossing the bid–ask;
- **Impact cost**: your own order pushing price against you on a thin book;
- **Risk of waiting**: while slicing orders and waiting for fills, the alpha is
  decaying and price is drifting away.

Trade scheduling = the problem of balancing those three, moment by moment.
Too fast is expensive; too slow and you drift.

## Contract

```
INPUT : target_position(t) [from Stage 5], current_position(t) [reconciled ledger],
        order book state (depth, spread), cost model
OUTPUT: stream of child orders — each with: side, price, size, send time
```

## Mechanics — four decision layers

### Layer 1 — Urgency: fast or slow?

For the same gap, execution speed follows one comparison:

```
cost of waiting ≈ |gap| × alpha_decay_speed × value_of_1bp
cost of acting  ≈ half_spread + impact(gap relative to current depth)
```

Strong signal (high z), fast-decaying alpha → act now. Weak signal or gap much
larger than available depth → slice it. This is the Gârleanu–Pedersen result in
operational form: each period move only *part* of the way toward target, with
speed inversely related to cost/signal-strength.

### Layer 2 — Execution algorithm: choosing the slicing pattern

| Algorithm | How it slices | When to use |
|---|---|---|
| **Immediate / marketable limit** | Cross the spread, fill now | Small gaps (a few contracts), urgent signal |
| **TWAP** | Even slices over time | Medium gap, want to average the price |
| **VWAP** | Slices follow the session's historical volume profile | Large gaps in sessions with clear volume rhythm |
| **POV (percentage of volume)** | Track the market's actual trade rate, stay under X% of volume | Large size, fear of self-impact |
| **Passive posting** | Rest limit orders in the queue, cancel/replace as the book moves | The non-urgent share of size, earning the half-spread |

For intraday VN30F1M context: most days need only two modes — marketable limit
for small gaps, TWAP over a few minutes for large ones. Do not build the full
algo collection before data proves the need.

### Layer 3 — Passive execution and its hidden price

A limit order saves the half-spread but carries two risks everyone underestimates:
**queue risk** (standing behind resting orders, never reaching the front) and
**adverse selection** — your passive order gets filled precisely when the market
trades *through* it, i.e., usually when moving against you. The backtest safety
rule stated at the start of this whole discussion applies verbatim here: assume
the most pessimistic fill (price must cross an extra tick before counting as
filled) until live fill data proves otherwise.

### Layer 4 — Order state machine and reconciliation

This layer is not glamorous but it is where desks kill themselves with bugs:

```
NEW → SENT → ACKED → PARTIALLY_FILLED → FILLED
                    ↘ CANCELLED / REJECTED / TIMEOUT ↗
```

Three survival laws: **(1)** `current_position` updates only from broker-
confirmed fills, never from expectations; **(2)** every order submission is
idempotent — losing connection and retrying must not spawn duplicate orders;
**(3)** periodically reconcile the internal ledger against the broker-reported
position — a mismatch is a red alert, not something to wait out.

## Worked example, continuing our world

Target just jumped from +3 to +5 contracts (composite rose after the new bar):

```
Gap = +2 contracts. Spread = 0.1 point (~0.008% notional).
Ask-side depth: 15 contracts within 1 tick.
Cost of acting  = 2 contracts × half_spread ≈ 0.0008% capital
Cost of waiting = z = 1.2, visible alpha decay → ~0.002% per minute idle
→ Verdict: marketable limit at the ask, filled within seconds. Done.
```

The opposite case: right after the open, target flips −5 → +8 (gap of 13
contracts) while depth is thin and spread widened to 2 ticks → switch to TWAP
over 12 minutes with POV capped at 10%, plus a cancellation condition if the
composite reverses before completion.

## What practitioners add at this layer

| Technique | Content |
|---|---|
| **Throttle & cooldown** | Target recomputes every bar but orders may not chase every bar: act only when \|gap\| exceeds threshold AND enough time passed since last submission — kills turnover caused by target jitter |
| **Pre-trade risk checks** | Margin check, fat-finger (absurd price/size), duplicate detection, session boundary — blocked at the OMS before the order leaves home |
| **Session awareness** | No passive orders left hanging across lunch break / into ATC; know the daily price bands (orders beyond limit-up/down are meaningless) |
| **Slippage attribution loop** | Per parent order measure implementation shortfall = (avg fill price − mid at decision) × side, broken down by session hour / vol regime / size — reviewed weekly, results pumped back into Stage 1's cost model and Stage 5's sizing |
| **Multi-broker routing** | Larger firms run parallel broker lines for redundancy and latency — unnecessary for this project stage, but design the interface so extra lines can be plugged in later |

## Traps characteristic of this stage

1. **Strategy seeing unconfirmed fills** — deciding on imagined positions,
   drifting further until explosion;
2. **Ignoring own impact** — your order on a thin book pushes price; flat-cost
   backtests never see this;
3. **Sending orders in toxic windows** — first seconds after open, final minutes
   before lunch: widest spreads, strongest adverse selection;
4. **Non-idempotent retries** — network drops for 3 seconds, comes back as two
   purchases of the same size;
5. **Chasing last tick** — mild target jitter makes the system reverse
   constantly, dying by fees; throttling is mandatory medicine.

## Handoff to Stage 7

This stage's output is not just orders — it is **full telemetry**: every order
event, every fill, measured slippage, reconciled position states. That data feed
feeds Stage 7 — risk overlay and monitoring: kill switches, exposure caps, and
the divergence clock between live and backtest promised back in every alpha's
spec sheet.

One-sentence summary: **Stage 6 does not make you rich — it only decides how
much you pay for becoming rich via the earlier stages.** But in intraday trading
where costs eat basis-point by basis-point, "paying little or much" is exactly
the border between positive and negative Sharpe.

The discussion therefore proceeded to Stage 7.
