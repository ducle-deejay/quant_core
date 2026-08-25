# Stage 7 — Risk Overlay & Monitoring

> Provenance: faithful English rendering of the first full presentation of
> Stage 7 (defense layers, divergence monitoring, kill switch design, the bad
> morning timeline, and the full-pipeline recap). Follow-up Q&A is not included
> here.

Stage 7 — the final layer, and the only one designed under the assumption that
*everything above it will eventually fail* — bad data, bugs, dead alphas,
exchange outages, or a human pressing the wrong button. If earlier stages are
the money-making machinery, this is the immune system: its job is not to optimize
anything, but to **guarantee that no failure above can kill the account**.

Principle number one of this stage, stated upfront: **the risk layer must be
independent of the strategy layer** — different process, different codebase,
ideally different owners. At Chinese firms the 风控 (risk control) team is
organizationally separate from the alpha team, and the risk subsystem has the
authority to switch alphas off, never the reverse. A guardian that can be
switched off by the patient it guards is not a guardian.

## Contract

```
INPUT : real-time position/exposure, PnL stream, order telemetry (from Stage 6),
        infrastructure/feed state, expectation dossiers from spec sheets
        (backtest benchmarks)
OUTPUT: interventions (block orders, reduce multipliers, flatten everything),
        alerts to humans on an escalation ladder
```

## Mechanics — four defense layers, ordered by depth

### Layer 1 — Pre-trade checks (static, once per order)

Already installed in Stage 6's OMS but owned by risk: margin sufficient? price/
size sane (fat-finger)? duplicate order? position limit respected? exchange rate
limit headroom left? Cheapest layer, blocks the most.

### Layer 2 — Exposure caps (static, continuous)

Hard-coded notional/contract ceilings living inside the risk process, not
referenceable from strategy configuration. This is the physical embodiment of
the `L_max` computed at Stage 5 — placed where strategy cannot edit it.

### Layer 3 — Drawdown-based circuit breakers (dynamic, real-time)

Three distinct levels — never conflate them:

```
Soft halt     : no new positions, still manage existing ones        ← suspicion
Flatten       : close all positions in the market                   ← lost control
Shutdown      : disconnect, lock the system                         ← last resort
```

Automatic triggers: intraday loss limit (derived from the volatility target —
e.g., 0.95%/day target ⇒ 3-sigma ≈ 2.9% of capital = 14.5M VND on 500M capital
⇒ kill line placed around there), total drawdown breaching the kill line of the
rule table, or severe divergence (below).

### Layer 4 — Live-vs-backtest divergence monitor: the promised clock

This repays the debt of the Stage 2 spec sheet. Principle: compare live against
expectations **on statistically sound quantities**, never on this-week's-PnL
noise. Four standard gauges:

| Gauge | Compared against | Meaning when off |
|---|---|---|
| Rolling Information Coefficient (window ≥ multiple of holding period) | Spec sheet | Edge dying or just bad luck — distinguishable via statistical bands |
| Implementation shortfall measured from fills | Stage 1 cost model | Execution broken or cost assumption wrong |
| Position tracking error: avg \|current − target\| | Design threshold | Stage 6 sick |
| Fill rate, reject rate, latency, feed gaps | Operational baseline | Infrastructure sick |

Reading numbers the way we practiced: spec says rolling IC ≈ 0.05, live shows
0.008 for ten sessions → **warning**; combined with measured slippage at 2× the
model → **escalate**: drop m_drawdown to 0.5, manual review within 24 hours.
Each type of deviation leads to a different action — that is what separates
professional monitoring from alarm spam.

### Supplementary layer — Dead man's switch

The life-saving detail everyone skips: if the strategy process's heartbeat goes
silent for more than X seconds (crash, network loss, deadlock), the risk layer
**defaults to worst case** — soft halt or flatten, per configuration. Never
defaults to "hope it comes back". Paired with a stale-feed detector: price data
frozen too long is an emergency, because a blind strategy still sending orders
is the worst scenario available.

## Worked example — one bad morning, end to end

```
09:31  Feed heartbeat miss #1 (2s)              → logged, watched
09:47  Intraday loss −1.8% of capital           → m_drawdown auto-lowered to 0.75 (rule table)
10:12  Composite reverses, gap 6 contracts      → Stage 6 TWAP handles normally
10:40  Loss touches −3.0% (intraday kill line)  → FLATTEN everything, soft halt
10:41  Telegram alert Critical → must acknowledge within 5 minutes,
       unacked escalates to SMS + phone call
11:00  Preliminary post-mortem: slippage 09:47–10:40 at 3× model after a news spike
       → event logged into registry, cost buffer temporarily raised for the afternoon
```

The entire chain runs without a human pressing anything — humans are informed so
they can decide what comes next.

## What practitioners add

- **Pre-committed runbooks** for every failure scenario (WebSocket loss, mass
  broker rejects, limit-up without exit...) — who does what, in which order,
  written while calm;
- **Chaos drills on a schedule**: deliberately pull the network cable / kill the
  process in the paper environment to test recovery — a kill switch never
  rehearsed is a kill switch that has never worked;
- **Escalation ladder with acknowledgment**: unacknowledged critical alerts
  escalate to louder channels (SMS, phone) — the antidote to alert fatigue;
- **Automated daily report**: today's PnL decomposed into three pieces — alpha
  component, execution slippage, noise — so divergence is measured, not guessed;
- **Immutable post-trade logging**: every manual intervention recorded — a
  post-mortem that cannot see human decisions learns nothing.

## Traps characteristic of this stage

1. **Risk code in the same process as strategy** — a strategy crash takes its
   guardian down, exactly when needed most;
2. **Divergence metric too noisy** — comparing day-by-day PnL is noise against
   noise; it manufactures false alarms until everyone learns to ignore them;
3. **Relying on broker-side protection** — a margin call is a slow mechanism; in
   live markets the only fast responder for your account is your own system;
4. **Alerts without an owner** — a message flying into a 20-person channel is
   nobody's responsibility;
5. **Manual interventions without logging** — the post-mortem lesson is lost.

## The loop closes — the whole pipeline in one view

```
Stage 0  Mining        → thousands of score functions
Stage 1  Canonical sim → comparable net-of-cost profiles
Stage 2  Evaluation    → gate passed with deflated thresholds
Stage 3  Orthogonalization → only true incremental value kept
Stage 4  Combination   → composite score through governance
Stage 5  Sizing        → target position through the vol-targeting stack
Stage 6  Scheduling    → child orders + telemetry
Stage 7  Risk overlay  → protects everything above, and pumps fills/divergence
                         back into Stage 1 (cost model), Stage 2 (kill criteria),
                         and the registry (trial log)
```

The feedback loop from Stage 7 back to the front is what makes this a **living
system** rather than a backtest project: the cost model recalibrates itself from
real fills, dead alphas are retired by criteria promised in advance, and every
failure becomes input for the next generation of the mining machine.

One-sentence summary of the whole pipeline: **Stages 0→4 decide whether you have
an edge; Stages 5→6 decide how much of it survives costs; Stage 7 decides whether
you stay alive to collect it.**

With this, the modern pipeline from mining to monitoring was complete, covering
all eight stages in the order established at the start of the discussion.
