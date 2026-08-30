---
doc_id: TST-010
title: Milestone-1 live corrections contract tests (DEC-013)
type: test-mapping
owner: research
status: resolved
version: 1.0
components: [5, 6, 7]
tags: [expiry, warmup, decision-log, transition-log, milestone-1]
source: "implemented with DEC-013, 2026-08-30"
design: [STG-5-POSITION-CONSTRUCTION, STG-6-TRADE-SCHEDULING, STG-7-RISK-OVERLAY]
code: [src/trading/tests/test_bridge.py, src/trading/tests/test_dnse_data.py, src/trading/tests/test_risk_overlay_log.py]
test: []
---

# TST-010 - Milestone-1 Live Corrections Contract Tests

Maps the DEC-013 contracts to their protecting tests (all plain-runner, no
pytest; full suite 127 tests green on 2026-08-30).

## Test mapping

| Contract (DEC-013) | Tests | File |
|---|---|---|
| Force-close day gating (dates, tz, empty=never) | `test_is_force_close_day_*` (in-list, not-in-list, empty-list, multiple, UTC boundary, naive rejected) | `src/trading/tests/test_bridge.py` |
| Expiry-day reduce-only entry rule | `test_is_expiry_day_entry_blocked_*` (flat->entry blocked, reduce allowed, increase blocked, flip-through-zero, no-op) | `src/trading/tests/test_bridge.py` |
| Session windows (morning/afternoon/lunch/before-open/after-close, half-open) | `test_in_session_window_*` | `src/trading/tests/test_bridge.py` |
| Decision log schema + best-effort writer | `test_format_decision_*`, `test_append_decision_*` | `src/trading/tests/test_bridge.py` |
| Config validation (windows, dates, defaults 7200/8000) | `test_bridge_config_*` additions | `src/trading/tests/test_bridge.py` |
| Catalog warmup source: config, catalog serving, API fallback, old behavior | `test_historical_source_*`, `test_catalog_source_serves_catalog_bars`, `test_catalog_empty_window_falls_back_to_api`, `test_api_source_keeps_old_behavior`, `test_load_catalog_bars_window_filtering` | `src/trading/tests/test_dnse_data.py` |
| Risk transition log: format, append, detection, startup anchor | `test_risk_overlay_log.py` (9 tests) | `src/trading/tests/test_risk_overlay_log.py` |

## Notes

- Bridge suite grew 23 -> 54; dnse data client suite new (7); risk overlay log
  suite new (9). Risk state-machine suite (24) untouched and green.
