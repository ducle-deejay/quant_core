"""Daily extract, transform, and load (ETL) orchestration for market data.

Runs DNSE first, then uses Mirae candlesticks to backfill days where DNSE
left bars missing. Final coverage is judged after both sources, the catalog is then consolidated,
and the aggregated result or failure is sent through the Telegram notifier.

Source settings are loaded from a JSON object. The DNSE runner reads
``API_KEY`` and ``API_SECRET`` from the environment, while the notifier is
supplied by the caller.
"""

from __future__ import annotations

import json
import os
import sys
from collections.abc import Callable
from datetime import date
from datetime import datetime
from datetime import time
from datetime import timedelta
from pathlib import Path
from time import monotonic
from typing import Any

import pandas as pd
from nautilus_trader.persistence import ParquetDataCatalog

from market_data.notify import TelegramNotifier
from market_data.notify import esc
from market_data.notify import notify_or_log
from market_data.sources import ETLStageError
from market_data.sources.dnse.client import create_dnse_rest_client
from market_data.sources.dnse.extract import get_working_dates
from market_data.sources.dnse.pipeline import retained_contract_symbol
from market_data.sources.dnse.pipeline import run_daily as run_dnse_daily
from market_data.sources.mirae.extract import request_mirae_history
from market_data.sources.mirae.load import FULL_DAY_BARS
from market_data.sources.mirae.pipeline import run_daily as run_mirae_daily
from market_data.sources.mirae.transform import BAR_TYPE
from market_data.sources.mirae.transform import LOCAL_TIMEZONE


SourceRunner = Callable[[date], dict[str, object]]

CONSOLIDATION_PERIOD_NS = 100 * 365 * 86_400_000_000_000  # longer than any catalog's history
CATCH_UP_TRADING_DAYS = 5
INGEST_AFTER = time(16, 0)
WORKING_DATES_FILE = "working_dates.json"


class DailyDataPipelineError(RuntimeError):
    """DNSE failed, or bars remain missing after the Mirae backfill."""

    def __init__(
        self,
        message: str,
        *,
        source_errors: dict[str, Exception | None] | None = None,
    ) -> None:
        self.source_errors = {
            source: error
            for source, error in (source_errors or {}).items()
            if error is not None
        }
        super().__init__(message)


def run_daily(
    *,
    day: date,
    run_dnse: SourceRunner,
    run_mirae: SourceRunner,
    consolidate: Callable[[], None],
) -> dict[str, object]:
    """Run DNSE first, then Mirae; judge final coverage after both sources,
    then consolidate the catalog.

    Returns the aggregated report. Raises DailyDataPipelineError when DNSE
    failed outright or when timestamps remain missing after both sources; an
    error from ``consolidate`` propagates unchanged.
    """
    dnse_report: dict[str, object] | None = None
    dnse_error: Exception | None = None
    try:
        dnse_report = run_dnse(day)
    except Exception as error:
        dnse_error = error

    mirae_report: dict[str, object] | None = None
    mirae_error: Exception | None = None
    try:
        mirae_report = run_mirae(day)
    except Exception as error:
        mirae_error = error

    if dnse_error is not None:
        raise DailyDataPipelineError(
            "DNSE daily pipeline failed; Mirae backup "
            f"{'also failed' if mirae_error is not None else 'attempted'}",
            source_errors={"DNSE": dnse_error, "Mirae": mirae_error},
        ) from dnse_error

    remaining = _remaining_missing(dnse_report, mirae_report)
    if remaining:
        raise DailyDataPipelineError(
            f"{len(remaining)} one-minute bars remain missing after both sources",
            source_errors={"DNSE": dnse_error, "Mirae": mirae_error},
        )

    consolidate()

    report: dict[str, object] = {
        "day": day.isoformat(),
        "dnse": dnse_report,
        "mirae": mirae_report,
    }
    if mirae_error is not None:
        # DNSE fully covered the day; a broken fallback is a warning, not a
        # failed run - surface it in the report/alert instead of failing.
        report["mirae_error"] = _format_exception(mirae_error)
    return report


def _remaining_missing(
    dnse_report: dict[str, object] | None,
    mirae_report: dict[str, object] | None,
) -> list[int]:
    """Timestamps DNSE missed that Mirae did not add."""
    missing = _missing_timestamps(dnse_report)
    if not missing:
        return []
    added = _mirae_added_timestamps(mirae_report)
    return [timestamp for timestamp in missing if timestamp not in added]


def _missing_timestamps(report: dict[str, object] | None) -> list[int]:
    if report is None:
        return []
    value = report.get("missing_bar_timestamps", [])
    return [int(timestamp) for timestamp in value] if isinstance(value, list) else []


def _mirae_added_timestamps(report: dict[str, object] | None) -> set[int]:
    if report is None:
        return set()
    records = report.get("records")
    value = records.get("added_bar_timestamps") if isinstance(records, dict) else None
    return {int(timestamp) for timestamp in value} if isinstance(value, list) else set()


def _dnse_client_factory() -> tuple[Any, list[Any]]:
    api_key = os.getenv("API_KEY")
    api_secret = os.getenv("API_SECRET")
    if not api_key or not api_secret:
        raise RuntimeError("API_KEY and API_SECRET must be defined in .env")
    observed: list[Any] = []
    client = create_dnse_rest_client(
        api_key=api_key,
        api_secret=api_secret,
        rate_limit_observer=observed.append,
    )
    return client, observed


def record_working_dates(raw_root: Path) -> set[date]:
    """Merge DNSE's working dates into ``raw_root``'s record and return every recorded date.

    DNSE's working-dates response starts at the current day (observed: requested on a Saturday,
    it began with the next Monday), so past trading days are known only from earlier runs'
    records. When the request fails, the record alone is used.
    """
    path = raw_root / WORKING_DATES_FILE
    recorded = read_working_dates(raw_root)
    try:
        fetched = get_working_dates(_dnse_client_factory)
    except Exception as error:
        print(f"DNSE working dates unavailable, using the record: {_format_exception(error)}", file=sys.stderr)
        return recorded
    merged = recorded | fetched
    if merged != recorded:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(sorted(day.isoformat() for day in merged), indent=0) + "\n", encoding="utf-8")
        temporary.replace(path)
    return merged


def read_working_dates(raw_root: Path) -> set[date]:
    path = raw_root / WORKING_DATES_FILE
    if not path.exists():
        return set()
    return {date.fromisoformat(value) for value in json.loads(path.read_text(encoding="utf-8"))}


def dnse_runner(config: dict[str, Any]) -> SourceRunner:
    def run(day: date) -> dict[str, object]:
        return run_dnse_daily(
            client_factory=_dnse_client_factory,
            raw_root=_resolve_path(config["raw_root"]),
            catalog_path=_resolve_path(config["catalog_path"]),
            continuous_symbol=str(config["instrument"]),
            day=day,
            request_delay_seconds=float(config["request_delay_seconds"]),
        )

    return run


def mirae_runner(mirae_config: dict[str, Any], dnse_config: dict[str, Any]) -> SourceRunner:
    """Mirae fallback runner; reuses the DNSE-retained monthly contract."""

    def run(day: date) -> dict[str, object]:
        return run_mirae_daily(
            request_history=request_mirae_history,
            active_contract=retained_contract_symbol(
                _resolve_path(dnse_config["raw_root"]),
                day,
            ),
            raw_root=_resolve_path(mirae_config["raw_root"]),
            catalog_path=_resolve_path(mirae_config["catalog_path"]),
            continuous_symbol=str(mirae_config["instrument"]),
            day=day,
        )

    return run


def catalog_consolidator(config: dict[str, Any]) -> Callable[[], None]:
    """Merge the files of every catalog data directory into one file ordered by ts_init.

    Daily ingest adds one file per day; a backtest warmup request that spans the
    time between two files receives no bars. ``consolidate_catalog`` keeps rows in
    file order rather than ts_init order, which breaks later range deletes, so the
    merge uses one period that spans the whole catalog instead.
    """

    def consolidate() -> None:
        ParquetDataCatalog(str(_resolve_path(config["catalog_path"]))).consolidate_catalog_by_period(
            period_nanos=CONSOLIDATION_PERIOD_NS,
            ensure_contiguous_files=False,
        )

    return consolidate


def count_day_bars(catalog_path: Path, day: date) -> int:
    """One-minute bars stored for the local trading day ``day``."""
    start, end = _local_day_bounds(day)
    return len(ParquetDataCatalog(str(catalog_path)).query_bars([BAR_TYPE], start=start, end=end))


def day_is_complete(catalog_path: Path, day: date) -> bool:
    """A full session of bars plus trades and order book depth for ``day``."""
    if count_day_bars(catalog_path, day) < FULL_DAY_BARS:
        return False
    catalog = ParquetDataCatalog(str(catalog_path))
    start, end = _local_day_bounds(day)
    return bool(catalog.query_trade_ticks(start=start, end=end)) and bool(
        catalog.query_order_book_depths(start=start, end=end),
    )


def recent_trading_days(working_dates: set[date], now: datetime) -> list[date]:
    """The latest CATCH_UP_TRADING_DAYS trading days; today counts only from INGEST_AFTER.

    Raises when no recorded working date reaches today, since whether today trades is unknown.
    """
    if not working_dates or max(working_dates) < now.date():
        raise ValueError(f"No recorded DNSE working dates reach {now.date()}")
    last = now.date() if now.time() >= INGEST_AFTER else now.date() - timedelta(days=1)
    return sorted(day for day in working_dates if day <= last)[-CATCH_UP_TRADING_DAYS:]


def days_to_ingest(
    *,
    catalog_path: Path,
    working_dates: set[date],
    now: datetime,
) -> list[date]:
    return [day for day in recent_trading_days(working_dates, now) if not day_is_complete(catalog_path, day)]


def _local_day_bounds(day: date) -> tuple[int, int]:
    start = pd.Timestamp(day, tz=LOCAL_TIMEZONE).value
    return start, pd.Timestamp(day + timedelta(days=1), tz=LOCAL_TIMEZONE).value - 1


ROOT =Path(__file__).resolve().parents[2]


def _resolve_path(value: object) -> Path:
    path = Path(str(value))
    return path if path.is_absolute() else ROOT / path


def load_json_config(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Expected a JSON object in {path}")
    return payload


def alert_success(
    day: date,
    report: dict[str, object],
    run_duration: str | None = None,
) -> str:
    """[QC-DATA] success alert: DNSE record counts, and Mirae added/skipped counts or its error.

    QC-DATA is the job label printed in data ETL alerts.
    """
    dnse = report.get("dnse")
    mirae = report.get("mirae")
    dnse_counts = _records(dnse)
    mirae_counts = _records(mirae)
    dnse_block = (
        "DNSE \u2705\n"
        f"\u2022 bars: {_count(dnse_counts, 'Bar'):,}\n"
        f"\u2022 trades: {_count(dnse_counts, 'TradeTick'):,}\n"
        f"\u2022 book: {_count(dnse_counts, 'OrderBookDepth10'):,}"
    )
    mirae_error = report.get("mirae_error")
    if mirae_error:
        mirae_block = f"Mirae \u274C\n\u2022 {esc(mirae_error)}"
    else:
        mirae_block = (
            "Mirae \u2705\n"
            f"\u2022 added: {_count(mirae_counts, 'Bar'):,}\n"
            f"\u2022 skipped: {_count(mirae_counts, 'SkippedBar'):,}"
        )
    duration_line = f"Run duration: {run_duration}\n" if run_duration else ""
    return (
        "Job: QC-DATA ETL\n"
        f"Run date: {day:%d-%m-%Y}\n"
        f"{duration_line}"
        "Status: \u2705 SUCCESS\n\n"
        f"{dnse_block}\n{mirae_block}"
    )


def alert_failure(
    day: date,
    error: Exception,
    report: dict[str, object] | None,
    run_duration: str | None = None,
) -> str:
    """[QC-DATA] failure alert; lists each failed source's stage and exception."""
    source_errors = getattr(error, "source_errors", None)
    if isinstance(source_errors, dict) and source_errors:
        details = "\n\n".join(
            _format_source_error(source, source_error)
            for source, source_error in source_errors.items()
        )
    else:
        details = _format_exception(error)
    duration_line = f"Run duration: {run_duration}\n" if run_duration else ""
    return (
        "Job: QC-DATA ETL\n"
        f"Run date: {day:%d-%m-%Y}\n"
        f"{duration_line}"
        "Status: \u274C FAIL\n\n"
        f"<code>{esc(details)}</code>"
    )


def _format_source_error(source: str, error: Exception) -> str:
    if isinstance(error, ETLStageError):
        return f"{source}\nstage: {error.stage}\nexception: {_format_exception(error.cause)}"
    return f"{source}\nstage: unknown\nexception: {_format_exception(error)}"


def _format_exception(error: Exception) -> str:
    return f"{type(error).__name__}: {error}"


def _elapsed_text(elapsed_seconds: float) -> str:
    minutes, seconds = divmod(round(elapsed_seconds), 60)
    return f"{minutes}m{seconds:02d}s"


def alert_bootstrap_failure(day: date, error: Exception) -> str:
    """[QC-DATA] startup alert: any failure before the run starts."""
    return (
        "Job: QC-DATA ETL\n"
        f"Run date: {day:%d-%m-%Y}\n"
        "Status: \u274C FAIL\n\n"
        f"<code>{esc(error)}</code>\n\n"
        "check data/logs/daily-etl.err.log"
    )


def format_run_missing(day: date) -> str:
    """[QC-DATA] heartbeat alert: the scheduled run never happened."""
    return (
        "Job: QC-DATA ETL\n"
        f"Run date: {day:%d-%m-%Y}\n"
        "Status: \U0001F6A8 Run Missing\n\n"
        "expected 16:00 run not detected\n\n"
        "check: launchctl list · data/logs/daily-etl.err.log"
    )


def _records(report: object) -> dict[str, object]:
    if not isinstance(report, dict):
        return {}
    records = report.get("records")
    return records if isinstance(records, dict) else {}


def _count(records: dict[str, object], key: str) -> int:
    value = records.get(key, 0)
    return value if isinstance(value, int) else 0


def run_and_alert(
    *,
    day: date,
    run_dnse: SourceRunner,
    run_mirae: SourceRunner,
    consolidate: Callable[[], None],
    notifier: TelegramNotifier | None,
    raise_on_error: bool = False,
) -> dict[str, object]:
    """Run the daily pipeline and send the corresponding Telegram alert.

    ``raise_on_error=True`` propagates alert delivery errors instead of
    logging and suppressing them.
    """
    started_at = monotonic()
    try:
        report = run_daily(
            day=day,
            run_dnse=run_dnse,
            run_mirae=run_mirae,
            consolidate=consolidate,
        )
    except Exception as error:
        notify_or_log(
            notifier,
            alert_failure(day, error, None, _elapsed_text(monotonic() - started_at)),
            raise_on_error=raise_on_error,
        )
        raise
    notify_or_log(
        notifier,
        alert_success(day, report, _elapsed_text(monotonic() - started_at)),
        raise_on_error=raise_on_error,
    )
    return report
