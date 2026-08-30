---
doc_id: TST-009
title: Alert coverage wave A contract tests (DEC-012)
type: test-mapping
owner: research
status: resolved
version: 1.0
components: [6, 7]
tags: [alerts, format, heartbeat, bootstrap, milestone-1]
source: "implemented with DEC-012, 2026-08-30"
design: [STG-1-CANONICAL-SIM]
code: [src/market_data/tests/test_daily.py, src/market_data/tests/test_notify.py, src/market_data/tests/test_heartbeat.py, src/trading/tests/test_notify.py]
test: []
---

# TST-009 - Alert Coverage Wave A Contract Tests

Maps the DEC-012 alert contracts to their protecting tests.

## Test mapping

| Contract (DEC-012) | Test | File |
|---|---|---|
| Unified success template: icon header, per-source one-line counts, gaps/catalog footer | `test_alert_success_format`, `test_alert_success_mirae_down_warning` | `src/market_data/tests/test_daily.py` |
| Failure and bootstrap templates | `test_alert_failure_format`, `test_alert_bootstrap_failure_format`, `test_format_run_missing_format` | `src/market_data/tests/test_daily.py` |
| Fail-loud entrypoint (raise_on_error) vs failure-safe default | `test_run_and_alert_swallows_notify_error_by_default`, `test_run_and_alert_raise_on_error_propagates_notify_failure`, `test_run_and_alert_success_sends_alert`, `test_run_and_alert_failure_sends_alert` | `src/market_data/tests/test_daily.py` |
| Bootstrap guard in the real entrypoint: config failure alerts + exit 1 | `test_pipeline_bootstrap_failure_alerts_and_exits_nonzero` | `src/market_data/tests/test_daily.py` |
| HTML parse-mode transport | `test_send_message_uses_html_parse_mode` | `src/market_data/tests/test_notify.py` |
| Dynamic-value escaping | `test_esc_html_escapes_dynamic_values` | `src/market_data/tests/test_notify.py` |
| Heartbeat lifecycle: ok / failed / missing / stale-running | `test_heartbeat_ok_after_success`, `test_heartbeat_failed_keeps_watcher_quiet`, `test_heartbeat_missing_without_status_file`, `test_heartbeat_missing_for_other_day`, `test_heartbeat_running_not_yet_stale`, `test_heartbeat_stale_running_is_missing` | `src/market_data/tests/test_heartbeat.py` |
| Trading templates: session/order/force-close/risk/flatten with escaping | `test_format_session`, `test_format_order_outcome`, `test_format_order_outcome_without_reason`, `test_format_force_close`, `test_format_risk_state`, `test_format_flatten_failed` | `src/trading/tests/test_notify.py` |

## Notes

- The pipeline bootstrap test runs the real entrypoint as a subprocess with
  blanked Telegram env vars, so it never touches the network; exit code and
  stderr prove the guard fired.
- Test count delta vs the earlier suites: daily 6 -> 16, notify 4 -> 6,
  heartbeat 0 -> 6, trading notify 0 -> 6 (total 89 green, 2026-08-30).
