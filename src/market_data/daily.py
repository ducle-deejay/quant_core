"""Daily extract, transform, and load (ETL) orchestration for market data.

Runs DNSE first, then uses Mirae candlesticks to backfill days where DNSE
left bars missing. Final coverage is judged after both sources, the catalog is then consolidated,
and the result or failure is sent as a Discord alert.
"""

from __future__ import annotations

import json
import os
import sys
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from datetime import datetime
from datetime import time
from datetime import timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
from nautilus_trader.persistence import ParquetDataCatalog

from market_data.notify import GREEN
from market_data.notify import RED
from market_data.notify import YELLOW
from market_data.notify import Alert
from market_data.notify import DiscordWebhook
from market_data.notify import code_block
from market_data.notify import notify_or_log
from market_data.sources import ETLStageError
from market_data.sources.dnse.client import create_dnse_rest_client
from market_data.sources.dnse.extract import WORKING_DATES_FILE
from market_data.sources.dnse.extract import ClientFactory
from market_data.sources.dnse.extract import get_working_dates
from market_data.sources.dnse.extract import read_working_dates
from market_data.sources.dnse.extract import recorded_trading_day
from market_data.sources.dnse.pipeline import run_daily as run_dnse_daily
from market_data.sources.mirae.extract import request_mirae_history
from market_data.sources.mirae.load import FULL_DAY_BARS
from market_data.sources.mirae.pipeline import run_daily as run_mirae_daily
from market_data.sources.mirae.transform import BAR_TYPE
from market_data.sources.mirae.transform import LOCAL_TIMEZONE
from nautilus_bridge.instruments.derivatives.futures.vn30f1m import vn30f1m_contract


SourceRunner = Callable[[date], dict[str, object]]

CONSOLIDATION_PERIOD_NS = 100 * 365 * 86_400_000_000_000  # longer than any catalog's history
# Blank inline field (zero-width space as name and value) that ends a row of inline fields early
EMPTY_INLINE_FIELD = ("\u200b", "\u200b", True)


class DailyDataPipelineError(RuntimeError):
    """DNSE failed, or bars remain missing after the Mirae backfill."""

    def __init__(
        self,
        message: str,
        *,
        source_errors: dict[str, Exception | None] | None = None,
        missing_timestamps: list[int] | None = None,
    ) -> None:
        self.source_errors = {
            source: error
            for source, error in (source_errors or {}).items()
            if error is not None
        }
        self.missing_timestamps = missing_timestamps or []
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
    failed outright or when timestamps remain missing after both sources, and
    ETLStageError when consolidation fails.
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
            missing_timestamps=remaining,
        )

    try:
        consolidate()
    except Exception as error:
        raise ETLStageError(source="Catalog", stage="consolidate", cause=error) from error

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


def dnse_client_factory(api_key: str, api_secret: str) -> ClientFactory:
    """A factory of DNSE REST clients that also returns the rate-limit observations of each client."""

    def factory() -> tuple[Any, list[Any]]:
        observed: list[Any] = []
        client = create_dnse_rest_client(
            api_key=api_key,
            api_secret=api_secret,
            rate_limit_observer=observed.append,
        )
        return client, observed

    return factory


def record_working_dates(raw_root: Path, client_factory: ClientFactory) -> set[date]:
    """Merge DNSE's working dates into ``raw_root``'s record and return every recorded date.

    DNSE's working-dates response starts at the current day (observed), so past trading days
    are known only from earlier runs' records. When the request fails, the record alone is used.
    """
    path = raw_root / WORKING_DATES_FILE
    recorded = read_working_dates(raw_root)
    try:
        fetched = get_working_dates(client_factory)
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


def dnse_runner(
    client_factory: ClientFactory,
    raw_root: Path,
    catalog_path: Path,
    symbol: str,
    request_delay_seconds: float,
) -> SourceRunner:
    def run(day: date) -> dict[str, object]:
        return run_dnse_daily(
            client_factory=client_factory,
            raw_root=raw_root,
            catalog_path=catalog_path,
            continuous_symbol=symbol,
            day=day,
            request_delay_seconds=request_delay_seconds,
        )

    return run


def mirae_runner(raw_root: Path, dnse_raw_root: Path, catalog_path: Path, symbol: str) -> SourceRunner:
    """Mirae fallback runner; a current-day run requests the VN30F1M monthly contract."""

    def run(day: date) -> dict[str, object]:
        today = datetime.now(ZoneInfo(LOCAL_TIMEZONE)).date()
        active_contract = vn30f1m_contract(day, recorded_trading_day(dnse_raw_root))[0] if day == today else None
        return run_mirae_daily(
            request_history=request_mirae_history,
            active_contract=active_contract,
            raw_root=raw_root,
            catalog_path=catalog_path,
            continuous_symbol=symbol,
            day=day,
        )

    return run


def catalog_consolidator(catalog_path: Path) -> Callable[[], None]:
    """Merge each data directory into one ts_init-ordered file; a catalog-served warmup returns no bars across several files."""

    def consolidate() -> None:
        directories = sorted(
            {
                path.parent
                for path in (catalog_path / "data").glob("*/*/*.parquet")
                if path.parent.parent.name != "instruments"
            },
        )
        appends = {directory: _time_ordered_files(directory) for directory in directories}
        appends = {directory: files for directory, files in appends.items() if files is None or len(files) > 1}
        if all(files is not None for files in appends.values()):
            for directory, files in appends.items():
                _append_files(directory, files)
            return
        ParquetDataCatalog(str(catalog_path)).consolidate_catalog_by_period(
            period_nanos=CONSOLIDATION_PERIOD_NS,
            ensure_contiguous_files=False,
        )

    return consolidate


def _time_ordered_files(directory: Path) -> list[Path] | None:
    """Files sorted by time, or None when they cannot be joined without re-sorting."""
    files = sorted(directory.glob("*.parquet"), key=lambda path: _file_interval(path)[0])
    intervals = [_file_interval(path) for path in files]
    if any(previous[1] >= current[0] for previous, current in zip(intervals, intervals[1:])):
        return None
    schema = pq.read_schema(files[0])
    if any(not pq.read_schema(path).equals(schema, check_metadata=True) for path in files[1:]):
        return None
    return files


def _append_files(directory: Path, files: list[Path]) -> None:
    """Join time-ordered files into one; the first file's rows are copied without re-sorting."""
    first = pq.ParquetFile(files[0])
    target = directory / f"{_file_timestamp(_file_interval(files[0])[0])}_{_file_timestamp(_file_interval(files[-1])[1])}.parquet"
    temporary = directory / f".{target.name}.tmp"
    compression = first.metadata.row_group(0).column(0).compression.lower()
    with pq.ParquetWriter(temporary, first.schema_arrow, compression=compression) as writer:
        for index in range(first.num_row_groups):
            row_group = first.read_row_group(index)
            writer.write_table(row_group, row_group_size=row_group.num_rows)
        appended = pa.concat_tables(pq.read_table(path, schema=first.schema_arrow) for path in files[1:])
        writer.write_table(appended, row_group_size=appended.num_rows)
    # Rename before deleting: a failure in between leaves duplicate rows, not missing ones
    os.replace(temporary, target)
    for path in files:
        if path != target:
            path.unlink()


def _file_interval(path: Path) -> tuple[int, int]:
    """First and last ts_init from a file name such as 2026-10-16T01-45-00-683000000Z_2026-10-30T07-45-00-750000000Z.parquet."""
    start, end = path.stem.split("_")
    return _parse_file_timestamp(start), _parse_file_timestamp(end)


def _parse_file_timestamp(value: str) -> int:
    day, clock = value.rstrip("Z").split("T")
    hour, minute, second, nanosecond = clock.split("-")
    return pd.Timestamp(f"{day}T{hour}:{minute}:{second}", tz="UTC").value + int(nanosecond)


def _file_timestamp(value: int) -> str:
    return f"{pd.Timestamp(value, tz='UTC'):%Y-%m-%dT%H-%M-%S}-{value % 1_000_000_000:09d}Z"


def count_day_records(catalog_path: Path, day: date) -> tuple[int, int, int]:
    """One-minute bars, trades and order book depth rows stored for the local trading day ``day``."""
    catalog = ParquetDataCatalog(str(catalog_path))
    start, end = _local_day_bounds(day)
    return (
        len(catalog.query_bars([BAR_TYPE], start=start, end=end)),
        len(catalog.query_trade_ticks(start=start, end=end)),
        len(catalog.query_order_book_depths(start=start, end=end)),
    )


def day_is_complete(catalog_path: Path, day: date) -> bool:
    """A full session of bars plus trades and order book depth for ``day``."""
    bars, trades, depth = count_day_records(catalog_path, day)
    return bars >= FULL_DAY_BARS and trades > 0 and depth > 0


def recent_trading_days(working_dates: set[date], now: datetime, ingest_after: time, count: int) -> list[date]:
    """The latest ``count`` trading days; the current day counts only from ``ingest_after``.

    Raises when no recorded working date reaches today, since whether today trades is unknown.
    """
    if not working_dates or max(working_dates) < now.date():
        raise ValueError(f"No recorded DNSE working dates reach {now.date()}")
    last = now.date() if now.time() >= ingest_after else now.date() - timedelta(days=1)
    return sorted(day for day in working_dates if day <= last)[-count:]


def days_to_ingest(
    *,
    catalog_path: Path,
    working_dates: set[date],
    now: datetime,
    ingest_after: time,
    count: int,
) -> list[date]:
    recent = recent_trading_days(working_dates, now, ingest_after, count)
    return [day for day in recent if not day_is_complete(catalog_path, day)]


def _local_day_bounds(day: date) -> tuple[int, int]:
    start = pd.Timestamp(day, tz=LOCAL_TIMEZONE).value
    return start, pd.Timestamp(day + timedelta(days=1), tz=LOCAL_TIMEZONE).value - 1


@dataclass(frozen=True)
class RunAttempt:
    label: str  # attempt number out of the scheduled runs with the run time, or "manual" for a run started by hand
    next_run: str | None  # the next scheduled run that retries, None after the last one


def run_attempt(now: datetime | None, run_times: tuple[time, ...]) -> RunAttempt:
    """Place a run among the day's scheduled ``run_times``; ``None`` marks a manual run."""
    if now is None:
        return RunAttempt("manual", None)
    done = [at for at in run_times if at <= now.time()]
    later = [at for at in run_times if at > now.time()]
    label = f"{len(done)}/{len(run_times)} ({now:%H:%M})" if done else f"outside schedule ({now:%H:%M})"
    return RunAttempt(label, f"{later[0]:%H:%M}" if later else None)


def alert_ingested(
    day: date,
    report: dict[str, object],
    run: tuple[tuple[str, str, bool], ...],
    attempt: RunAttempt,
) -> Alert:
    dnse = _records(report.get("dnse"))
    mirae_added = _count(_records(report.get("mirae")), "Bar")
    mirae_error = report.get("mirae_error")
    bars = f"{FULL_DAY_BARS}/{FULL_DAY_BARS}" + (f" (Mirae added {mirae_added})" if mirae_added else "")
    if mirae_error:
        mirae = code_block(mirae_error)
    else:
        mirae = f"added {mirae_added} bars" if mirae_added else "not needed"
    return Alert(
        summary=f"⚠️ Data {day} ingested — Mirae backup down" if mirae_error else f"✅ Data {day} ingested",
        color=YELLOW if mirae_error else GREEN,
        fields=(
            ("Day", str(day), True),
            ("Attempt", attempt.label, True),
            EMPTY_INLINE_FIELD,
            *run,
            ("Bars", bars, True),
            ("Trades", f"{_count(dnse, 'TradeTick'):,}", True),
            ("Order book", f"{_count(dnse, 'OrderBookDepth10'):,}", True),
            ("Mirae", mirae, False),
        ),
    )


def alert_failed(
    subject: str,
    error: Exception,
    attempt: RunAttempt,
    log_path: str,
    run: tuple[tuple[str, str, bool], ...] = (),
    day: date | None = None,
) -> Alert:
    if attempt.next_run:
        outlook = f"retry at {attempt.next_run}"
    else:
        outlook = "manual run" if attempt.label == "manual" else "no retry left"
    fields = [
        ("Day", str(day), True) if day else EMPTY_INLINE_FIELD,
        ("Attempt", attempt.label, True),
        ("Next retry", attempt.next_run or "none", True),
        *run,
    ]
    fields += [(f"Step: {step}", code_block(detail), False) for step, detail in _failed_steps(error)]
    fields.append(("Log", f"`{log_path}`", False))
    return Alert(summary=f"❌ {subject} failed — {outlook}", color=RED, fields=tuple(fields))


def alert_startup_failed(error: Exception, log_path: str) -> Alert:
    return Alert(
        summary="❌ Data pipeline could not start",
        color=RED,
        fields=(
            ("Step: startup", code_block(_format_exception(error)), False),
            ("Log", f"`{log_path}`", False),
        ),
    )


def alert_data_missing(
    day: date,
    counts: tuple[int, int, int] | None,
    error: Exception | None,
    run_count: int,
    fix_command: str,
    log_path: str,
) -> Alert:
    """``counts`` are the day's bars, trades and depth rows; None when they could not be read."""
    if counts is None:
        stored = (("Error", code_block(_format_exception(error)) if error else "unknown", False),)
    else:
        bars, trades, depth = counts
        stored = (
            ("Bars", f"{bars}/{FULL_DAY_BARS}", True),
            ("Trades", f"{trades:,}" if trades else "missing", True),
            ("Order book", f"{depth:,}" if depth else "missing", True),
        )
    return Alert(
        summary=f"❌ Data {day} missing after all retries",
        color=RED,
        fields=(
            *stored,
            ("Attempts", f"{run_count}/{run_count} finished", True),
            ("Fix", fix_command, False),
            ("Log", f"`{log_path}`", False),
        ),
    )


def _failed_steps(error: Exception) -> list[tuple[str, str]]:
    if isinstance(error, ETLStageError):
        return [(f"{error.source} {error.stage}", _format_exception(error.cause))]
    if isinstance(error, DailyDataPipelineError):
        steps = [
            (f"{source} {source_error.stage}", _format_exception(source_error.cause))
            if isinstance(source_error, ETLStageError)
            else (source, _format_exception(source_error))
            for source, source_error in error.source_errors.items()
        ]
        if error.missing_timestamps:
            minutes = [
                pd.Timestamp(ts, tz="UTC").tz_convert(LOCAL_TIMEZONE).strftime("%H:%M")
                for ts in sorted(error.missing_timestamps)
            ]
            shown = ", ".join(minutes[:20]) + (" …" if len(minutes) > 20 else "")
            steps.append(("coverage check", f"{len(minutes)} bars missing after both sources: {shown}"))
        return steps or [("unknown", _format_exception(error))]
    return [("unknown", _format_exception(error))]


def _format_exception(error: Exception) -> str:
    return f"{type(error).__name__}: {error}"


def _run_fields(started: datetime, finished: datetime) -> tuple[tuple[str, str, bool], ...]:
    """Local start and end times of a run, and its length."""
    minutes, seconds = divmod(round((finished - started).total_seconds()), 60)
    return (
        ("Started", f"{started:%H:%M:%S}", True),
        ("Finished", f"{finished:%H:%M:%S}", True),
        ("Duration", f"{minutes}m{seconds:02d}s", True),
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
    notifier: DiscordWebhook | None,
    attempt: RunAttempt,
    log_path: str,
    raise_on_error: bool = False,
) -> dict[str, object]:
    """Run the daily pipeline for ``day`` and send its alert.

    ``raise_on_error=True`` propagates alert delivery errors instead of
    logging and suppressing them.
    """
    started = datetime.now(ZoneInfo(LOCAL_TIMEZONE))
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
            alert_failed(f"Data {day}", error, attempt, log_path, _run_fields(started, datetime.now(started.tzinfo)), day),
            raise_on_error=raise_on_error,
        )
        raise
    notify_or_log(
        notifier,
        alert_ingested(day, report, _run_fields(started, datetime.now(started.tzinfo)), attempt),
        raise_on_error=raise_on_error,
    )
    return report
