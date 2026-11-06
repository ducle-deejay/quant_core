"""Test daily ETL runs: source failures, alerts, catalog consolidation, day completeness,
the exchange comparison, the working-dates record and day selection."""

from __future__ import annotations

from datetime import date
from datetime import datetime
from datetime import time
from zoneinfo import ZoneInfo

import pandas as pd
import pytest
from nautilus_trader.model import Bar
from nautilus_trader.model import BarType
from nautilus_trader.persistence import ParquetDataCatalog

from market_data.daily import FULL_DAY_BARS
from market_data.daily import DailyDataPipelineError
from market_data.daily import alert_ingested
from market_data.daily import catalog_consolidator
from market_data.daily import day_is_complete
from market_data.daily import exchange_gaps
from market_data.daily import run_and_alert
from market_data.daily import RunAttempt
from market_data.daily import run_attempt
from market_data.daily import recent_trading_days
from market_data.daily import record_working_dates
from market_data.daily import run_daily
from market_data.notify import GREEN
from market_data.notify import RED
from market_data.notify import Alert
from market_data.sources.dnse.load import load_day
from market_data.sources.hnx.extract import ExchangeDay
from market_data.sources.dnse.transform import BAR_TYPE
from market_data.tests.test_dnse_load import INSTRUMENT
from market_data.tests.test_dnse_load import day_batches
from nautilus_bridge.instruments.derivatives.futures.vn30f1m import build_continuous_futures_contract


DAY = date(2026, 8, 30)
RUN_TIMES = tuple(time(hour, 0) for hour in range(16, 21))
INGEST_AFTER = time(16, 0)
FACTORY = lambda: (None, [])  # noqa: E731 - never called; get_working_dates is replaced
AT_16 = datetime(2026, 8, 31, 16, 0, tzinfo=ZoneInfo("Asia/Ho_Chi_Minh"))
FULL_DNSE = {"records": {"Bar": 241}, "missing_bar_timestamps": []}
# 2026-08-30 10:15 and 10:16 local time, in epoch seconds as DNSE reports them
DNSE_WITH_GAPS = {"records": {"Bar": 239}, "missing_bar_timestamps": [1788059700, 1788059760]}
BROKERS_OK = lambda d: {"Vietcap": pd.DataFrame(), "HSC": pd.DataFrame(), "VPS": pd.DataFrame()}  # noqa: E731


class RecordingNotifier:
    def __init__(self):
        self.alerts: list[Alert] = []

    def send(self, alert: Alert):
        self.alerts.append(alert)


def test_bars_missing_in_dnse_do_not_fail_the_day():
    report = run_daily(
        day=DAY,
        run_brokers=BROKERS_OK,
        run_dnse=lambda d, broker_bars: dict(DNSE_WITH_GAPS),
        consolidate=lambda: None,
    )
    alert = alert_ingested(DAY, report, (), run_attempt(AT_16, RUN_TIMES), "ingest.log")
    bars = next(value for name, value, _ in alert.fields if name == "Bars")
    assert bars == f"239/{FULL_DAY_BARS}"


def test_dnse_failed_raises_even_if_brokers_ok():
    try:
        run_daily(
            day=DAY,
            run_brokers=BROKERS_OK,
            run_dnse=lambda d, broker_bars: (_ for _ in ()).throw(RuntimeError("dnse down")),
            consolidate=lambda: None,
        )
    except DailyDataPipelineError as error:
        assert "DNSE" in str(error)
    else:
        raise AssertionError("expected DailyDataPipelineError")


def test_a_broker_failure_is_a_warning_not_a_failure():
    report = run_daily(
        day=DAY,
        run_brokers=lambda d: {"Vietcap": pd.DataFrame(), "HSC": RuntimeError("hsc down"), "VPS": pd.DataFrame()},
        run_dnse=lambda d, broker_bars: dict(FULL_DNSE),
        consolidate=lambda: None,
    )
    alert = alert_ingested(DAY, report, (), run_attempt(AT_16, RUN_TIMES), "ingest.log")
    assert "hsc down" in report["brokers"]["HSC"]
    assert alert.summary == f"⚠️ Data {DAY} ingested — HSC down"


def test_consolidation_leaves_one_ordered_file_per_directory(tmp_path):
    for day in ("2026-09-28", "2026-09-30", "2026-10-01"):  # one load per day leaves one file per day
        load_day(catalog_path=tmp_path, transformed=day_batches(day, 100.0))
    catalog = ParquetDataCatalog(str(tmp_path))
    intervals = catalog.get_intervals("trades", str(INSTRUMENT.id))
    assert len(intervals) > 1

    catalog_consolidator(tmp_path)()

    assert catalog.get_intervals("trades", str(INSTRUMENT.id)) == [(intervals[0][0], intervals[-1][1])]
    for records in (catalog.query_bars([BAR_TYPE]), catalog.query_trade_ticks(), catalog.query_order_book_depths()):
        ts_init = [record.ts_init for record in records]
        assert len(ts_init) == 12 and ts_init == sorted(ts_init)


@pytest.mark.parametrize(("n_bars", "complete"), [(FULL_DAY_BARS - 3, True), (0, False)])
def test_a_day_is_complete_once_dnse_bars_are_loaded_even_with_minutes_without_a_trade(tmp_path, n_bars, complete):
    instrument = build_continuous_futures_contract()
    price = instrument.make_price(100.0)
    catalog = ParquetDataCatalog(str(tmp_path))
    catalog.write_instruments([instrument])
    opens = pd.date_range("2026-09-29 09:00", periods=n_bars, freq="min", tz="Asia/Ho_Chi_Minh")
    if n_bars:
        catalog.write_bars([
            Bar(BarType.from_str(BAR_TYPE), price, price, price, price, instrument.make_qty(1), t.value, t.value + 60_000_000_000)
            for t in opens
        ])
    _, _, trades, more_trades, depth = day_batches("2026-09-29", 100.0)
    catalog.write_trade_ticks(trades + more_trades)
    catalog.write_order_book_depths(depth)
    assert day_is_complete(tmp_path, date(2026, 9, 29)) is complete


def test_exchange_gaps_keep_only_fields_beyond_tolerance():
    exchange = ExchangeDay(symbol="VN30F2611", open=1800.0, high=1810.0, low=1790.0, close=1805.0, volume=200_000)
    catalog = {"bars": 241, "open": 1800.4, "high": 1808.5, "low": 1790.0, "close": 1805.0, "volume": 200_001}
    assert exchange_gaps(catalog, exchange) == {"volume": 1, "high": -1.5}


# --------------------------------------------------------------------------- #
# run_and_alert alert coverage
# --------------------------------------------------------------------------- #


def test_run_and_alert_success_sends_one_green_alert():
    notifier = RecordingNotifier()
    run_and_alert(
        day=DAY,
        run_brokers=BROKERS_OK,
        run_dnse=lambda d, broker_bars: dict(FULL_DNSE),
        consolidate=lambda: None,
        notifier=notifier,
        attempt=run_attempt(AT_16, RUN_TIMES),
        log_path="daily-etl.err.log",
    )
    assert [alert.color for alert in notifier.alerts] == [GREEN]
    assert notifier.alerts[0].summary == f"✅ Data {DAY} ingested"


@pytest.mark.parametrize(
    ("run_dnse", "consolidate", "step"),
    [
        (lambda d, broker_bars: (_ for _ in ()).throw(RuntimeError("dnse down")), lambda: None, "Step: DNSE"),
        (lambda d, broker_bars: dict(FULL_DNSE), lambda: (_ for _ in ()).throw(OSError("disk full")), "Step: Catalog consolidate"),
    ],
)
def test_run_and_alert_failure_names_the_failed_step_and_the_next_retry(run_dnse, consolidate, step):
    notifier = RecordingNotifier()
    with pytest.raises(Exception):
        run_and_alert(
            day=DAY,
            run_brokers=BROKERS_OK,
            run_dnse=run_dnse,
            consolidate=consolidate,
            notifier=notifier,
            attempt=run_attempt(AT_16, RUN_TIMES),
            log_path="daily-etl.err.log",
        )
    [alert] = notifier.alerts
    assert alert.color == RED
    assert alert.summary == f"❌ Data {DAY} failed — retry at 17:00"
    assert any(name == step for name, _, _ in alert.fields)


def test_run_attempt_places_a_run_in_the_schedule():
    assert run_attempt(AT_16, RUN_TIMES) == RunAttempt("1/5 (16:00)", "17:00")
    assert run_attempt(AT_16.replace(hour=20), RUN_TIMES) == RunAttempt("5/5 (20:00)", None)
    assert run_attempt(None, RUN_TIMES) == RunAttempt("manual", None)


def test_working_dates_record_grows_and_survives_a_failed_request(tmp_path, monkeypatch):
    import market_data.daily as daily

    monkeypatch.setattr(daily, "get_working_dates", lambda _: {date(2026, 10, 5), date(2026, 10, 6)})
    record_working_dates(tmp_path, FACTORY)
    monkeypatch.setattr(daily, "get_working_dates", lambda _: {date(2026, 10, 6), date(2026, 10, 7)})
    assert record_working_dates(tmp_path, FACTORY) == {date(2026, 10, 5), date(2026, 10, 6), date(2026, 10, 7)}

    monkeypatch.setattr(daily, "get_working_dates", lambda _: (_ for _ in ()).throw(ConnectionError("down")))
    assert record_working_dates(tmp_path, FACTORY) == {date(2026, 10, 5), date(2026, 10, 6), date(2026, 10, 7)}


def test_recent_trading_days_follow_the_record_and_the_ingest_time():
    tz = ZoneInfo("Asia/Ho_Chi_Minh")
    working = {date(2026, 8, 28), date(2026, 9, 3), date(2026, 9, 4), date(2026, 9, 7)}  # 31/08-02/09 holiday
    assert recent_trading_days(working, datetime(2026, 9, 7, 15, 0, tzinfo=tz), INGEST_AFTER, 5) == [
        date(2026, 8, 28), date(2026, 9, 3), date(2026, 9, 4),
    ]
    assert recent_trading_days(working, datetime(2026, 9, 7, 16, 0, tzinfo=tz), INGEST_AFTER, 5)[-1] == date(2026, 9, 7)
    with pytest.raises(ValueError, match="No recorded DNSE working dates"):
        recent_trading_days(working, datetime(2026, 9, 8, 16, 0, tzinfo=tz), INGEST_AFTER, 5)


def test_a_cleaned_day_shows_counts_and_an_unresolved_day_shows_the_gap():
    def alert(clean):
        report = {"dnse": {**FULL_DNSE, "clean": clean}, "brokers": {"Vietcap": 241, "HSC": 241, "VPS": 241}}
        return alert_ingested(DAY, report, (), run_attempt(AT_16, RUN_TIMES), "ingest.log")

    cleaned = alert({"outcome": "corrected", "filled": ["09:35"], "corrected": ["09:36"]})
    assert cleaned.summary == f"✅ Data {DAY} ingested — bars cleaned"
    assert ("Clean", "1 filled, 1 corrected", False) in cleaned.fields

    unresolved = alert({
        "outcome": "unresolved", "filled": [], "corrected": [], "reason": "no match",
        "dnse": {"volume": 168_045.0}, "broker_summary": {"volume": 168_648.0}, "gaps": {"volume": -603},
    })
    assert unresolved.summary == f"⚠️ Data {DAY} ingested — bars not cleaned"
    clean = next(value for name, value, _ in unresolved.fields if name == "Clean")
    assert "-603" in clean and "168,648" in clean
