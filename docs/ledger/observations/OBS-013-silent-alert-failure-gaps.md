---
doc_id: OBS-013
title: Data pipeline alerting had two silent-failure gaps: bootstrap crashes and undeliverable alerts
type: observation
owner: research
status: resolved
version: 1.0
components: [6]
tags: [data, etl, alerts, monitoring, silent-failure, milestone-1]
source: "milestone-1 daily ETL first-run test, 2026-08-30"
design: [STG-1-CANONICAL-SIM]
code: [apps/data/daily/pipeline.py, src/market_data/notify.py, src/market_data/daily.py]
test: [src/market_data/tests/test_daily.py, src/market_data/tests/test_notify.py]
---

# OBS-013 - Two Silent-Failure Gaps in Data Pipeline Alerting

## 1. Finding

Two failure modes produced NO operator-visible alert during the 2026-08-30
first-run test; both were caught only because a human was watching the console:

1. **Bootstrap crashes are silent.** `apps/data/daily/pipeline.py` loaded its
   configs BEFORE building the Telegram notifier, and `run_and_alert` only
   guards the two source runners. A `FileNotFoundError` on the top-level
   config (stale `applications/` paths, OBS-012) crashed the process with no
   alert at all - the LaunchAgent 16:00 run would have failed identically,
   invisibly.
2. **Undeliverable alerts are silent.** The alert transport is failure-safe
   by contract (`notify_or_log` swallows, logs to stderr). When
   `DATA_TELEGRAM_CHAT_ID` held a bot username instead of a numeric chat id,
   Telegram returned HTTP 400 "chat not found", the error was swallowed, and
   the pipeline exited 0 - an operator seeing exit 0 would believe the alert
   had been delivered.

## 2. Resolution

Recorded decision DEC-012, implemented in the same change:
- bootstrap-phase failures send a STARTUP FAILED alert and exit non-zero;
- the ETL entrypoint sends alerts with `raise_on_error=True` - an
  undeliverable alert now fails the run loudly (the trading loop keeps the
  failure-safe contract);
- a heartbeat status file + watcher LaunchAgent detects runs that never
  happened (RUN MISSING), the one case a pipeline cannot self-report;
- unified alert format (HTML parse-mode) so every alert is scannable.

## 3. Impact

- No data-outage mode remains fully invisible: run missing, run failed,
  bootstrap failure, and dead alert channel each produce a distinct alert.
- The failure-safe contract in `market_data.notify` is preserved for the
  trading hot path; only the ETL entrypoint opts out (DEC-012).
