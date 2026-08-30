---
doc_id: DEC-012
title: Alert coverage wave A - unified alert format, bootstrap alerts, fail-loud entrypoint, heartbeat watcher
type: decision
owner: research
status: resolved
version: 1.0
components: [6, 7]
tags: [alerts, telegram, format, heartbeat, monitoring, milestone-1]
source: "owner-approved wave A, 2026-08-30, after OBS-013"
design: [STG-1-CANONICAL-SIM]
code: [src/market_data/notify.py, src/market_data/daily.py, src/market_data/heartbeat.py, src/trading/notify.py, apps/data/daily/pipeline.py, apps/data/daily/check_heartbeat.py, apps/smoke_alerts.py]
test: [src/market_data/tests/test_daily.py, src/market_data/tests/test_notify.py, src/market_data/tests/test_heartbeat.py, src/trading/tests/test_notify.py]
---

# DEC-012 - Alert Coverage Wave A: Format, Bootstrap Alerts, Fail-Loud, Heartbeat

## 1. Decision

Four changes close the silent-failure gaps found in OBS-013 and unify alert
presentation across both channels:

1. **Unified alert format.** Every alert follows one template:
   `<icon> QC-<DOMAIN> <EVENT> | <date> [<time VN>] | <verdict>` header,
   inline monospace `<code>` body grouped by source with thousands
   separators, and a footer only when actionable. The transport sends
   `parse_mode=HTML`; dynamic values are HTML-escaped via
   `market_data.notify.esc`. Icons lead each line for instant recognition
   (success, failure, warning, force-close, risk state, heartbeat miss).
   Revision (owner review, 2026-08-30): `<pre>` blocks were replaced by
   per-line `<code>` spans - monospace alignment is kept while Telegram
   renders inline instead of a boxed code block, so a message reads as one
   layer instead of mixing normal text with a code box. Second revision
   (owner review, same day): the ETL success body became a bullet list
   (one metric per line, e.g. "- bars: 241") - easier to scan than a
   single dot-separated line; single-line bodies elsewhere keep `<code>`.
2. **Bootstrap alerts.** `apps/data/daily/pipeline.py` builds the notifier
   first and wraps config resolution; any pre-run failure sends a
   STARTUP FAILED alert and exits non-zero.
3. **Fail-loud entrypoint.** The ETL entrypoint passes
   `raise_on_error=True` to alert sends: an undeliverable alert now fails the
   run loudly (exit non-zero) instead of pretending success. The failure-safe
   contract in `market_data.notify` stays for the trading hot path.
4. **Heartbeat watcher.** Every run writes `data/state/daily-etl-status.json`
   (`market_data.heartbeat`: result running/ok/failed); the
   `io.quant-core.daily-etl-watch` LaunchAgent (16:10 Mon-Fri) checks it and
   alerts RUN MISSING only when no record exists for the day (or a stale
   "running" record suggests a hard kill). Failed runs are not re-alerted -
   the pipeline's own failure alert covers them.

Plus `apps/smoke_alerts.py`: sends every template through the real channels
with `raise_on_error=True` to prove delivery end-to-end.

Deferred to wave B (with the acceptance layers): rolling volume baselines,
cross-source divergence checks, and wrong-contract guards.

## 2. Rationale

- A pipeline that never starts cannot alert by itself; the heartbeat watcher
  makes "absence of the expected alert" the alert (the standard practitioner
  pattern for scheduled jobs).
- Alert fatigue kills alerts: the unified template keeps the alert set small
  and scannable, and every alert maps to one operator decision.
- The trading loop keeps failure-safe alerting because a Telegram outage must
  never block order processing; the ETL entrypoint is not latency-critical,
  so loud failure there is the right trade.

## 3. Impact

- Alert coverage matrix (data channel): run missing (watcher), run failed
  (failure alert), bootstrap failure (new), incomplete bars (failure alert via
  existing coverage validation), dead alert channel (fail-loud, exit non-zero).
- All alert formatters changed signature-compatibly; callers (bridge strategy,
  risk overlay) are untouched.
