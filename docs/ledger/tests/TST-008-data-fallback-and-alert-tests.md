---
doc_id: TST-008
title: Data fallback and alert tests - daily orchestrator semantics and Telegram transport
type: test-mapping
owner: research
status: resolved
version: 1.0
components: [0, 1]
tags: [tests, data, fallback, telegram, milestone-1]
source: "test suites written with the DEC-009 data-source work, 2026-08-30"
design: [STG-1-CANONICAL-SIM]
code: [src/market_data/daily.py, src/market_data/notify.py]
test: [src/market_data/tests/test_daily.py, src/market_data/tests/test_notify.py]
---

# TST-008 - Data Fallback and Alert Tests

## 1. What is protected

| Suite | Count | Protects |
|---|---|---|
| `src/market_data/tests/test_daily.py` | 6 | DEC-009 fallback semantics: Mirae resolving all DNSE gaps SUCCEEDS (the regression the nox implementation got wrong); remaining gaps after both sources fail; DNSE failure raises; Mirae failure with full DNSE coverage is a warning (`mirae_error` in report), not a failure; `_remaining_missing` math |
| `src/market_data/tests/test_notify.py` | 4 | Telegram env parsing (both token and chat id required together), failure-safe `notify_or_log` (swallows, logs to stderr), explicit `raise_on_error`, None-notifier no-op |

Tests are plain assert runners (pytest not installed in the project venv):
`.venv/bin/python3 src/market_data/tests/test_<suite>.py`.

## 2. Governing notes

- DEC-009 (fallback semantics + alerting contract), canon STG-1 (bar data contract).
- Governing note ids cited in test source comments per ledger rule M4.

## Related notes

- [DEC-009](DEC-009-data-sources-and-telegram-alerts.md)
