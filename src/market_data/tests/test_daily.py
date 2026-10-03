"""Test DNSE-first fallback, coverage, and alert behavior for daily ETL runs.

Covers Mirae backfills of DNSE gaps, source failures, final coverage checks,
alert delivery, bootstrap configuration failures, catalog consolidation, and the
daily data check.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import date
from pathlib import Path

import pandas as pd
from nautilus_trader.model import Bar
from nautilus_trader.model import BarType
from nautilus_trader.persistence import ParquetDataCatalog

from market_data.daily import DailyDataPipelineError
from market_data.daily import catalog_consolidator
from market_data.daily import run_and_alert
from market_data.daily import run_daily
from market_data.sources.mirae.load import FULL_DAY_BARS
from market_data.sources.dnse.load import load_day
from market_data.sources.mirae.transform import BAR_TYPE
from market_data.tests.test_dnse_load import INSTRUMENT
from market_data.tests.test_dnse_load import day_batches
from nautilus_bridge.instruments.derivatives.futures.vn30f1m import build_continuous_futures_contract


DAY = date(2026, 8, 30)
FULL_DNSE = {"records": {"Bar": 240}, "missing_bar_timestamps": []}
DNSE_WITH_GAPS = {"records": {"Bar": 230}, "missing_bar_timestamps": [100, 101, 102]}
MIRAE_ADDED_ALL = {"records": {"Bar": 3, "SkippedBar": 0, "added_bar_timestamps": [100, 101, 102]}}
MIRAE_ADDED_PARTIAL = {"records": {"Bar": 1, "SkippedBar": 0, "added_bar_timestamps": [100]}}


class RecordingNotifier:
    def __init__(self):
        self.messages: list[str] = []

    def send_message(self, text: str):
        self.messages.append(text)


def test_mirae_resolves_dnse_gaps_succeeds():
    report = run_daily(
        day=DAY,
        run_dnse=lambda d: dict(DNSE_WITH_GAPS),
        consolidate=lambda: None,
        run_mirae=lambda d: dict(MIRAE_ADDED_ALL),
    )
    assert report["mirae"]["records"]["Bar"] == 3


def test_remaining_gaps_after_both_sources_fails():
    try:
        run_daily(
            day=DAY,
            run_dnse=lambda d: dict(DNSE_WITH_GAPS),
            consolidate=lambda: None,
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
            consolidate=lambda: None,
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
        consolidate=lambda: None,
        run_mirae=lambda d: (_ for _ in ()).throw(RuntimeError("mirae down")),
    )
    assert "mirae down" in report["mirae_error"]


def test_consolidation_leaves_one_ordered_file_per_directory(tmp_path):
    for day in ("2026-09-28", "2026-09-30", "2026-10-01"):  # one load per day, as the daily ingest does
        load_day(catalog_path=tmp_path, transformed=day_batches(day, 100.0))
    catalog = ParquetDataCatalog(str(tmp_path))
    intervals = catalog.get_intervals("trades", str(INSTRUMENT.id))
    assert len(intervals) > 1

    catalog_consolidator({"catalog_path": str(tmp_path)})()

    assert catalog.get_intervals("trades", str(INSTRUMENT.id)) == [(intervals[0][0], intervals[-1][1])]
    for records in (catalog.query_bars([BAR_TYPE]), catalog.query_trade_ticks(), catalog.query_order_book_depths()):
        ts_init = [record.ts_init for record in records]
        assert len(ts_init) == 12 and ts_init == sorted(ts_init)


def _run_daily_data_check(tmp_path, n_bars):
    instrument = build_continuous_futures_contract()
    price = instrument.make_price(100.0)
    (tmp_path / "catalog").mkdir()
    catalog = ParquetDataCatalog(str(tmp_path / "catalog"))
    catalog.write_instruments([instrument])
    opens = pd.date_range("2026-09-29 09:00", periods=n_bars, freq="min", tz="Asia/Ho_Chi_Minh")
    catalog.write_bars([
        Bar(BarType.from_str(BAR_TYPE), price, price, price, price, instrument.make_qty(1), t.value, t.value + 60_000_000_000)
        for t in opens
    ])
    (tmp_path / "dnse.json").write_text(json.dumps({"catalog_path": str(tmp_path / "catalog")}))
    (tmp_path / "pipeline.json").write_text(json.dumps({"dnse_config": str(tmp_path / "dnse.json")}))
    env = {**os.environ, "DATA_TELEGRAM_BOT_TOKEN": "", "DATA_TELEGRAM_CHAT_ID": ""}
    script = Path(__file__).resolve().parents[3] / "apps" / "data" / "daily" / "check_daily_data.py"
    return subprocess.run(
        [sys.executable, str(script), "--config", str(tmp_path / "pipeline.json"), "--date", "2026-09-29"],
        capture_output=True, text=True, env=env, timeout=60,
    )


def test_daily_data_check_passes_on_a_full_session(tmp_path):
    assert _run_daily_data_check(tmp_path, FULL_DAY_BARS).returncode == 0


def test_daily_data_check_fails_when_bars_are_missing(tmp_path):
    result = _run_daily_data_check(tmp_path, FULL_DAY_BARS - 1)
    assert result.returncode == 1
    assert "DATA MISSING" in result.stderr


# --------------------------------------------------------------------------- #
# run_and_alert alert coverage
# --------------------------------------------------------------------------- #


def test_run_and_alert_success_sends_alert():
    notifier = RecordingNotifier()
    run_and_alert(
        day=DAY,
        run_dnse=lambda d: dict(FULL_DNSE),
        consolidate=lambda: None,
        run_mirae=lambda d: dict(MIRAE_ADDED_ALL),
        notifier=notifier,
    )
    assert len(notifier.messages) == 1
    assert "SUCCESS" in notifier.messages[0]


def test_run_and_alert_failure_sends_alert():
    notifier = RecordingNotifier()
    try:
        run_and_alert(
            day=DAY,
            run_dnse=lambda d: (_ for _ in ()).throw(RuntimeError("dnse down")),
            consolidate=lambda: None,
            run_mirae=lambda d: dict(MIRAE_ADDED_ALL),
            notifier=notifier,
        )
    except DailyDataPipelineError:
        pass
    else:
        raise AssertionError("expected DailyDataPipelineError")
    assert len(notifier.messages) == 1
    assert "FAIL" in notifier.messages[0]


# --------------------------------------------------------------------------- #
# Pipeline bootstrap guard: config failures alert + exit non-zero
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
