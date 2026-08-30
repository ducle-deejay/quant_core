"""Daily fallback semantics tests (governing note DEC-009).

The critical regression: a run where Mirae RESOLVED every DNSE-missing
timestamp must SUCCEED - the replaced nox implementation failed the whole
run in that case.

Alert-format and alert-coverage tests (governing note DEC-012): unified
HTML template, bootstrap failure alert, and fail-loud alert sending.
"""

from __future__ import annotations

import os
import subprocess
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from market_data.daily import DailyDataPipelineError  # noqa: E402
from market_data.daily import _remaining_missing  # noqa: E402
from market_data.daily import alert_bootstrap_failure  # noqa: E402
from market_data.daily import alert_failure  # noqa: E402
from market_data.daily import alert_success  # noqa: E402
from market_data.daily import format_run_missing  # noqa: E402
from market_data.daily import run_and_alert  # noqa: E402
from market_data.daily import run_daily  # noqa: E402


DAY = date(2026, 8, 30)
FULL_DNSE = {"records": {"Bar": 240}, "missing_bar_timestamps": []}
DNSE_WITH_GAPS = {"records": {"Bar": 230}, "missing_bar_timestamps": [100, 101, 102]}
MIRAE_ADDED_ALL = {"records": {"Bar": 3, "SkippedBar": 0, "added_bar_timestamps": [100, 101, 102]}}
MIRAE_ADDED_PARTIAL = {"records": {"Bar": 1, "SkippedBar": 0, "added_bar_timestamps": [100]}}
MIRAE_ADDED_NONE = {"records": {"Bar": 0, "SkippedBar": 3, "added_bar_timestamps": []}}


class RecordingNotifier:
    def __init__(self):
        self.messages: list[str] = []

    def send_message(self, text: str):
        self.messages.append(text)


class RaisingNotifier:
    def __init__(self, error: Exception):
        self.error = error

    def send_message(self, text: str):
        raise self.error


def test_dnse_ok_mirae_ok():
    report = run_daily(
        day=DAY,
        run_dnse=lambda d: dict(FULL_DNSE),
        run_mirae=lambda d: dict(MIRAE_ADDED_ALL),
    )
    assert report["day"] == DAY.isoformat()
    assert report["dnse"]["records"]["Bar"] == 240


def test_mirae_resolves_dnse_gaps_succeeds():
    # THE regression: nox failed here; we must succeed.
    report = run_daily(
        day=DAY,
        run_dnse=lambda d: dict(DNSE_WITH_GAPS),
        run_mirae=lambda d: dict(MIRAE_ADDED_ALL),
    )
    assert report["mirae"]["records"]["Bar"] == 3


def test_remaining_gaps_after_both_sources_fails():
    try:
        run_daily(
            day=DAY,
            run_dnse=lambda d: dict(DNSE_WITH_GAPS),
            run_mirae=lambda d: dict(MIRAE_ADDED_PARTIAL),
        )
    except DailyDataPipelineError as error:
        assert "remain missing" in str(error)
    else:
        raise AssertionError("expected DailyDataPipelineError")


def test_dnse_failed_raises_even_if_mirae_ok():
    try:
        run_daily(
            day=DAY,
            run_dnse=lambda d: (_ for _ in ()).throw(RuntimeError("dnse down")),
            run_mirae=lambda d: dict(MIRAE_ADDED_ALL),
        )
    except DailyDataPipelineError as error:
        assert "DNSE" in str(error)
    else:
        raise AssertionError("expected DailyDataPipelineError")


def test_mirae_failure_covered_by_dnse_is_warning_not_failure():
    report = run_daily(
        day=DAY,
        run_dnse=lambda d: dict(FULL_DNSE),
        run_mirae=lambda d: (_ for _ in ()).throw(RuntimeError("mirae down")),
    )
    assert report["mirae_error"] == "mirae down"
    assert report["dnse"]["records"]["Bar"] == 240


def test_remaining_missing_math():
    assert _remaining_missing(dict(FULL_DNSE), None) == []
    assert _remaining_missing(dict(DNSE_WITH_GAPS), dict(MIRAE_ADDED_ALL)) == []
    assert _remaining_missing(dict(DNSE_WITH_GAPS), dict(MIRAE_ADDED_PARTIAL)) == [101, 102]
    assert _remaining_missing(dict(DNSE_WITH_GAPS), dict(MIRAE_ADDED_NONE)) == [100, 101, 102]
    assert _remaining_missing(None, None) == []


# --------------------------------------------------------------------------- #
# Alert formatting (DEC-012 unified template)
# --------------------------------------------------------------------------- #

SUCCESS_REPORT = {
    "dnse": {"records": {"Bar": 241, "TradeTick": 89565, "OrderBookDepth10": 593874}},
    "mirae": {"records": {"Bar": 0, "SkippedBar": 473773}},
}


def test_alert_success_format():
    message = alert_success(DAY, dict(SUCCESS_REPORT))
    assert "✅ QC-DATA ETL | 30-08-2026 | OK" in message
    assert "DNSE ✅" in message
    assert "• bars: 241" in message
    assert "• trades: 89,565" in message
    assert "• book: 593,874" in message
    assert "Mirae ✅" in message
    assert "• added: 0" in message
    assert "• skipped: 473,773" in message
    assert "gaps 0 · catalog updated" in message


def test_alert_success_mirae_down_warning():
    report = dict(SUCCESS_REPORT)
    report["mirae_error"] = "mirae down <boom>"
    message = alert_success(DAY, report)
    assert "| OK (mirae down)" in message
    assert "Mirae ❌" in message
    assert "• mirae down &lt;boom&gt;" in message  # HTML-escaped
    assert "gaps 0 · catalog updated" in message


def test_alert_failure_format():
    error = DailyDataPipelineError("DNSE daily pipeline failed; Mirae backup also failed")
    message = alert_failure(DAY, error, None)
    assert "❌ QC-DATA ETL | 30-08-2026 | FAILED" in message
    assert "DNSE daily pipeline failed" in message
    assert "catalog NOT updated" in message


def test_alert_bootstrap_failure_format():
    message = alert_bootstrap_failure(DAY, FileNotFoundError("config/pipeline.json"))
    assert "❌ QC-DATA ETL | 30-08-2026 | STARTUP FAILED" in message
    assert "config/pipeline.json" in message
    assert "check data/logs/daily-etl.err.log" in message


def test_format_run_missing_format():
    message = format_run_missing(DAY)
    assert "🚨 QC-DATA ETL | 30-08-2026 | RUN MISSING" in message
    assert "expected 16:00 run not detected" in message


# --------------------------------------------------------------------------- #
# run_and_alert alert coverage (DEC-012)
# --------------------------------------------------------------------------- #


def test_run_and_alert_success_sends_alert():
    notifier = RecordingNotifier()
    run_and_alert(
        day=DAY,
        run_dnse=lambda d: dict(FULL_DNSE),
        run_mirae=lambda d: dict(MIRAE_ADDED_ALL),
        notifier=notifier,
    )
    assert len(notifier.messages) == 1
    assert "✅ QC-DATA ETL" in notifier.messages[0]


def test_run_and_alert_failure_sends_alert():
    notifier = RecordingNotifier()
    try:
        run_and_alert(
            day=DAY,
            run_dnse=lambda d: (_ for _ in ()).throw(RuntimeError("dnse down")),
            run_mirae=lambda d: dict(MIRAE_ADDED_ALL),
            notifier=notifier,
        )
    except DailyDataPipelineError:
        pass
    else:
        raise AssertionError("expected DailyDataPipelineError")
    assert len(notifier.messages) == 1
    assert "❌ QC-DATA ETL" in notifier.messages[0]
    assert "FAILED" in notifier.messages[0]


def test_run_and_alert_swallows_notify_error_by_default():
    import contextlib
    import io

    buffer = io.StringIO()
    with contextlib.redirect_stderr(buffer):
        try:
            run_and_alert(
                day=DAY,
                run_dnse=lambda d: (_ for _ in ()).throw(RuntimeError("dnse down")),
                run_mirae=lambda d: dict(MIRAE_ADDED_ALL),
                notifier=RaisingNotifier(RuntimeError("telegram down")),
            )
        except DailyDataPipelineError:
            pass
        else:
            raise AssertionError("expected DailyDataPipelineError")
    assert "Telegram notification failed" in buffer.getvalue()


def test_run_and_alert_raise_on_error_propagates_notify_failure():
    try:
        run_and_alert(
            day=DAY,
            run_dnse=lambda d: (_ for _ in ()).throw(RuntimeError("dnse down")),
            run_mirae=lambda d: dict(MIRAE_ADDED_ALL),
            notifier=RaisingNotifier(RuntimeError("telegram down")),
            raise_on_error=True,
        )
    except RuntimeError as error:
        assert str(error) == "telegram down"
    else:
        raise AssertionError("expected the notify failure to propagate")


# --------------------------------------------------------------------------- #
# Pipeline bootstrap guard (DEC-012): config failures alert + exit non-zero
# --------------------------------------------------------------------------- #


def test_pipeline_bootstrap_failure_alerts_and_exits_nonzero():
    repo_root = Path(__file__).resolve().parents[3]
    pipeline = repo_root / "apps" / "data" / "daily" / "pipeline.py"
    env = dict(os.environ)
    # Blank the Telegram vars so the test never touches the network; the
    # notifier becomes None and the bootstrap alert is a no-op, while the
    # exit code and stderr still prove the guard fired.
    env["DATA_TELEGRAM_BOT_TOKEN"] = ""
    env["DATA_TELEGRAM_CHAT_ID"] = ""
    env["TRADING_TELEGRAM_BOT_TOKEN"] = ""
    env["TRADING_TELEGRAM_CHAT_ID"] = ""
    result = subprocess.run(
        [
            sys.executable,
            str(pipeline),
            "--config",
            "/nonexistent/pipeline.json",
            "--date",
            "2026-08-28",
        ],
        capture_output=True,
        text=True,
        env=env,
        cwd=repo_root,
        timeout=60,
    )
    assert result.returncode == 1
    assert "STARTUP FAILED" in result.stderr


def _run_all() -> int:
    failures = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"PASS {name}")
            except AssertionError as error:
                failures += 1
                print(f"FAIL {name}: {error}")
            except Exception as error:  # noqa: BLE001
                failures += 1
                print(f"FAIL {name}: {type(error).__name__}: {error}")
    return failures


if __name__ == "__main__":
    raise SystemExit(1 if _run_all() else 0)
