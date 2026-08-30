# Runbook - Paper Session 2026-09-03 (simulated expiry day)

Purpose: first full paper session on the entrade demo with the milestone-1
semantics (DEC-013): 30-session catalog warmup, session-window gating, expiry-
day force-close at 14:00 VN (2026-09-03 is DECLARED as the expiry day via
`force_close_dates`), per-bar decision log, risk transition log, Nautilus
streaming to feather, Redis state persistence.

## 1. Session configuration (wired in apps/trading/paper.py)

| Item | Value |
|---|---|
| Session date | 2026-09-03 (VN holiday 31-08..02-09; next trading day) |
| Instrument | VN30F1M (continuous) -> entrade monthly contract, DEMO |
| Order style | MAK (market IOC) |
| Force-close | `force_close_dates=["2026-09-03"]`, cutoff 14:00 VN, reduce-only entries on expiry day, same-day re-entry blocked |
| Session windows | 09:00-11:30 / 13:00-14:30 VN (no ATO/lunch/ATC orders) |
| Warmup | 7200 bars from research catalog (data/catalog), API fallback; buffer 8000 |
| Streaming | data/live/live/<instance_id>/ (bars + order/position/account events + config.json manifest) |
| Decision log | data/logs/sessions/2026-09-03/decisions.jsonl |
| Risk log | data/logs/sessions/2026-09-03/risk_transitions.jsonl |
| State | Redis 127.0.0.1:6379 (cache db + order/position snapshots + strategy save/load) |

## 2. Pre-flight (done 2026-08-30, re-run before session)

```sh
.venv/bin/python3 apps/trading/check_auth.py --env .env      # AUTH OK
.venv/bin/python3 apps/trading/paper.py --dry-run            # composition OK
.venv/bin/python3 apps/smoke_alerts.py                       # 9/9 delivered
redis-cli ping                                               # PONG
# warmup window: 7953 bars available in catalog (2026-07-15..08-28) >= 7200
```

## 3. Before market open (08:45 VN)

```sh
cd /Users/ducle/repos/quant_core
.venv/bin/python3 apps/trading/paper.py
```

Watch startup logs: warmup served from catalog ("Served N bars from catalog"),
then live bars. Expected `[QC-TRADING]` session alert.

## 4. During the session (monitor checklist)

- Bars arriving every minute (decision log growing).
- Orders only inside 09:00-11:30 / 13:00-14:30 (no ATO/lunch/ATC).
- 14:00 VN: expiry-day force-close fires -> `[QC-TRADING] FORCE CLOSE` alert,
  position flat; same-day no new entries.
- Risk alerts on any trigger (loss limit, exposure cap, stale feed).
- If anything looks wrong: stop with Ctrl-C (state saved to Redis), check
  data/logs/sessions/2026-09-03/, restart allowed (state restored).

## 5. After the session (14:45 VN stop)

Stop the process (Ctrl-C), then WAIT for the daily ETL (16:00) so the research
catalog contains 2026-09-03 data, then:

```sh
.venv/bin/python3 apps/trading/acceptance.py --session-dir data/logs/sessions/2026-09-03
```

Report: data/logs/sessions/2026-09-03/acceptance.md + acceptance.json.
Six checks: data parity (gated), signal parity (gated), execution (gated),
position (gated), cost (REPORT only - first calibration point), risk (gated).
Exit code non-zero if any gated check fails.

## 6. After-action

- Send acceptance.md to the owner; discuss per-check numbers.
- Update the session handoff (HANDOFF-002) with results.
