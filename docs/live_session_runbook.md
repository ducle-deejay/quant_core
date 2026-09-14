# Live Session Runbook

Step-by-step guide for validating the DNSE/Entrade adapters and then running
the live node on the Entrade demo (papertrade) account.

All commands run from the repository root with the rc5 environment:

```
.venv-v2/bin/python ...
```

## Prerequisites

- `.env` at the repository root contains: `API_KEY`, `API_SECRET`
  (DNSE OpenAPI), `ENTRADE_USERNAME`, `ENTRADE_PASSWORD`, and optionally
  `ENTRADE_INVESTOR_ID` (auto-resolved from the auth token when absent).
- Run inside a Vietnamese trading session (Mon–Fri, 09:00–11:30 and
  13:00–14:45 ICT). Outside a session, quote/bar streams stay silent and the
  data-adapter checks are inconclusive.
- Every process stops with Ctrl+C; shutdown is graceful.

## Terminology

Two independent axes (see `src/trading/adapters/entrade_template/README.md`):

- **Nautilus `Environment`** — the node runtime context. All runners here use
  `Environment.LIVE` (real-time data, real venue connections).
- **Entrade account** — demo (papertrade, virtual money) vs real money.
  Selected by `EntradeAccount` / `EntradeExecClientConfig.account`. Everything
  in this runbook trades the demo account.

## Step 1 — DNSE data adapter

```
.venv-v2/bin/python apps/trading/entrade_template/data_tester.py
```

Duration: 10–15 minutes.

Pass criteria:

- Quotes stream continuously within the first minutes.
- At least one or two 1-minute bars close.
- Instrument and historical bar requests return data.
- No reconnect loops or exceptions in the log.

Fail criteria (fix before continuing): missing quotes/bars during a session,
authentication errors, subscription errors.

No orders are placed at this step.

## Step 2 — Entrade execution adapter

Dry run first (no orders are sent):

```
.venv-v2/bin/python apps/trading/entrade_template/exec_tester.py
```

Duration: ~5 minutes. Pass criteria: authentication OK, resolved account id
matches, startup reconciliation completes without errors, no orders sent.

Then submit real orders on the demo account:

```
.venv-v2/bin/python apps/trading/entrade_template/exec_tester.py --live-orders
```

Duration: 10–15 minutes. Expected flow: LIMIT orders submitted → accepted →
possibly filled → Ctrl+C cancels remaining orders (`cancel_orders_on_stop`).

After stopping, check the Entrade demo portal: no orphan open orders, and the
position matches the log.

## Step 3 — Live node on the demo account

Requires steps 1 and 2 to have passed.

```
.venv-v2/bin/python apps/trading/live/live.py
```

Before starting, confirm in `apps/trading/live/live.py`:

- `ENTRADE_ACCOUNT = EntradeAccount.DEMO` (demo account; switching this to
  `EntradeAccount.LIVE` trades real money — do not change it during a demo run).

Settings (resolution, trade size, EMA periods) are the module constants in
the same file.

Expected behaviour: startup reconciliation runs, quotes and 1-minute bars
flow, and the strategy may run for hours without submitting any order while
it waits for an EMA cross. Absence of orders is normal; absence of data is
not.

Stop with Ctrl+C; the strategy closes open positions on stop.

## Safety gates

- Never skip step 2 dry run before `--live-orders`.
- Step 3 requires both adapter checks (steps 1 and 2) to have passed.
- Real-money trading is gated by changing `ENTRADE_ACCOUNT` to
  `EntradeAccount.LIVE` in `apps/trading/live/live.py` — treat that edit as a
  separate, reviewed change.
