---
doc_id: DEC-009
title: Data sources DNSE primary + Mirae fallback, and Telegram alerting for data ingest and live trading
type: decision
owner: research
status: resolved
version: 1.0
components: [0, 1, 6, 7]
tags: [data, fallback, mirae, telegram, alerts, milestone-1]
source: "owner request 2026-08-30: pull both nox data sources (DNSE + Mirae fallback) into the current system with fixes, and add Telegram alerts for data ingest and live trading"
design: [STG-1-CANONICAL-SIM]
code: [src/market_data/sources/mirae, src/market_data/daily.py, src/market_data/notify.py, src/trading/notify.py, apps/data/daily, apps/data/sources/mirae, src/trading/risk/overlay.py, src/trading/strategies/bridge.py]
test: [src/market_data/tests/test_daily.py, src/market_data/tests/test_notify.py]
---

# DEC-009 - DNSE Primary + Mirae Fallback Data Sources, Telegram Alerting

## 1. Decision

Both nox data sources are ported into `src/market_data`:

- **DNSE** (primary): existing port, unchanged behavior.
- **Mirae** (fallback): ported from nox (`src/market_data/sources/mirae/`, same Extract -> Transform -> Load lifecycle, TLS via the macOS trust store, raw retention under `data/raw/vietnam/mirae/<acquisition-date>/`), filling ONLY catalog-absent one-minute timestamps - never averaging or overwriting existing bars.

A single daily orchestrator (`src/market_data/daily.py`, entrypoint `apps/data/daily/pipeline.py`) runs DNSE first and Mirae second, then alerts Telegram. One env pair drives ALL alerts (`TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`) through the shared transport `src/market_data/notify.py`, re-exported by `src/trading/notify.py` with trading message formatters.

## 2. Fixes vs the nox implementation (the "ngao" items)

- **Coverage judged after BOTH sources**: the nox runner failed the whole run when DNSE had missing timestamps even when Mirae resolved every one of them. Here, a fully-resolved backfill SUCCEEDS (regression test `test_mirae_resolves_dnse_gaps_succeeds`); only bars still missing after both sources fail the run.
- **Mirae failure with full DNSE coverage is a warning, not a failure**: reported as `mirae_error` in the report and shown in the success alert, so a silently broken fallback cannot go unnoticed while the catalog is still complete.
- **Alerting is targeted, not a catch-all event stream**: the nox live monitor subscribed to `events.*` and formatted every Nautilus event; here the bridge and risk overlay call explicit notify points (order rejected/denied/expired, force-close, risk state transitions, flatten failure, session start). Less spam, no event-dedup machinery.
- **Single config file** for the daily run (`apps/data/daily/config/pipeline.json`) pointing at the two source configs, replacing the nox nested-closure/three-config layout.
- **Mirae load now reports `added_bar_timestamps`** so the orchestrator can verify the backfill resolved the exact missing timestamps, not just a count.

## 3. Alert surface

- Data ingest: success (per-source counts), failure (which source, error), partial coverage warning.
- Live trading: session start, order rejected/denied/expired, force-close at 14:00, risk state transitions (ACTIVE/HALTED/REDUCING), flatten complete/failed.
- Failure-safe by contract: alerting errors are logged to stderr, never raised into the pipeline or the trading loop.

## 4. Scheduling

`apps/data/daily/schedule.py` installs a macOS LaunchAgent (Mon-Fri 17:30 Asia/Ho_Chi_Minh, after the 14:45 close) running the daily DNSE+Mirae ETL.

## Related notes

- [DEC-008](DEC-008-live-wiring-architecture.md) - wiring phase this lands in
- [TST-008](TST-008-data-fallback-and-alert-tests.md) - test mapping for the new suites
