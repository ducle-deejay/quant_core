"""Daily extract, transform, and load (ETL) orchestration for market data.

Retains the reference brokers' one-minute bars, loads DNSE into the catalog with its bars cleaned
against them, consolidates the catalog, and sends the result or failure as a Discord alert.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from datetime import datetime
from datetime import time
from datetime import timedelta
from pathlib import Path
from typing import Any

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
from nautilus_trader.persistence import ParquetDataCatalog

from market_data import LOCAL_TIMEZONE
from market_data.clean import FIELDS
from market_data.clean import FULL_DAY_BARS
from market_data.clean import summary_gaps
from market_data.clean import day_summary
from market_data.notify import GREEN
from market_data.notify import RED
from market_data.notify import YELLOW
from market_data.notify import Alert
from market_data.notify import DiscordWebhook
from market_data.notify import code_block
from market_data.logs import fields
from market_data.logs import stage
from market_data.notify import send_alert
from market_data.sources import ETLStageError
from market_data.sources.dnse.client import create_dnse_rest_client
from market_data.sources.dnse.extract import WORKING_DATES_FILE
from market_data.sources.dnse.extract import ClientFactory
from market_data.sources.dnse.extract import get_working_dates
from market_data.sources.dnse.extract import read_working_dates
from market_data.sources.dnse.pipeline import run_daily as run_dnse_daily
from market_data.sources.dnse.transform import BAR_TYPE
from market_data.sources.hnx.extract import ExchangeDay
from market_data.sources import bar_download
from market_data.sources.hsc import extract as hsc
from market_data.sources.vietcap import extract as vietcap
from market_data.sources.vps import extract as vps
from nautilus_bridge.instruments.derivatives.futures.vn30f1m import CONTINUOUS_SYMBOL
from nautilus_bridge.instruments.derivatives.futures.vn30f1m import VN30F1M_SESSIONS


DnseRunner = Callable[[date, list[pd.DataFrame]], dict[str, object]]
BrokerRunner = Callable[[date], dict[str, pd.DataFrame | Exception]]
logger = logging.getLogger("Pipeline")

BROKERS = {"Vietcap": vietcap, "HSC": hsc, "VPS": vps}
CONSOLIDATION_PERIOD_NS = 100 * 365 * 86_400_000_000_000  # longer than any catalog's history
# Blank inline field (zero-width space as name and value) that ends a row of inline fields early
EMPTY_INLINE_FIELD = ("\u200b", "\u200b", True)


class DailyDataPipelineError(RuntimeError):
    """DNSE failed."""

    def __init__(self, message: str, *, source_errors: dict[str, Exception | None] | None = None) -> None:
        self.source_errors = {
            source: error
            for source, error in (source_errors or {}).items()
            if error is not None
        }
        super().__init__(message)


def run_daily(
    *,
    day: date,
    run_brokers: BrokerRunner,
    run_dnse: DnseRunner,
    consolidate: Callable[[], None],
) -> dict[str, object]:
    """Retain the brokers' bars, run DNSE cleaned against them, then consolidate the catalog; return the aggregated report.

    Raises DailyDataPipelineError when DNSE fails, and ETLStageError when consolidation fails.
    """
    brokers = run_brokers(day)
    broker_bars = [bars for bars in brokers.values() if isinstance(bars, pd.DataFrame)]
    try:
        dnse_report = run_dnse(day, broker_bars)
    except Exception as error:
        raise DailyDataPipelineError(
            "DNSE daily pipeline failed",
            source_errors={"DNSE": error},
        ) from error

    missing_minutes = _missing_minutes(dnse_report)
    if missing_minutes:
        logger.info("minutes without a bar %s", fields(day=day, count=len(missing_minutes), minutes=",".join(missing_minutes)))

    with stage("Catalog", "consolidate", day):
        consolidate()

    return {
        "day": day.isoformat(),
        "dnse": dnse_report,
        # A broker failure is a warning: the clean step needs only a majority of the brokers
        "brokers": {
            name: _format_exception(bars) if isinstance(bars, Exception) else len(bars)
            for name, bars in brokers.items()
        },
    }


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
        logger.warning("DNSE working dates unavailable, using the record %s", fields(error=_format_exception(error)))
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
) -> DnseRunner:
    def run(day: date, broker_bars: list[pd.DataFrame]) -> dict[str, object]:
        return run_dnse_daily(
            client_factory=client_factory,
            raw_root=raw_root,
            catalog_path=catalog_path,
            continuous_symbol=symbol,
            day=day,
            broker_bars=broker_bars,
            request_delay_seconds=request_delay_seconds,
        )

    return run


def broker_runner(raw_root: Path) -> BrokerRunner:
    """Each broker's VN30F1M bars for the day, retained under ``raw_root/<broker>/VN30F1M``, or the error that prevented them."""

    def run(day: date) -> dict[str, pd.DataFrame | Exception]:
        result: dict[str, pd.DataFrame | Exception] = {}
        for name, source in BROKERS.items():
            try:
                with stage(name, "extract", day) as details:
                    path = bar_download.extract_day(
                        raw_root=raw_root / name.lower(),
                        symbol=CONTINUOUS_SYMBOL.value,
                        day=day,
                        sessions=VN30F1M_SESSIONS,
                        request=source.request_bars,
                        frame=source.bars_frame,
                    )
                    if path is None:
                        raise ValueError(f"{name} has no bar for {day}")
                    result[name] = bar_download.read_day(path, day, VN30F1M_SESSIONS, source.bars_frame)
                    details["bars"] = len(result[name])
            except ETLStageError as error:
                result[name] = error.cause
        return result

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


def publish_catalog(catalog_path: Path, published_root: Path) -> None:
    """Replace published_root/catalog with an APFS clone of catalog_path."""
    published = published_root / "catalog"
    staged = published_root / "catalog.new"
    retired = published_root / "catalog.old"
    published_root.mkdir(parents=True, exist_ok=True)
    # Left behind by a publish that was interrupted
    for leftover in (staged, retired):
        shutil.rmtree(leftover, ignore_errors=True)
    # -c clones instead of copying, so publishing does not double the catalog's disk use (man cp)
    result = subprocess.run(["cp", "-c", "-R", str(catalog_path), str(staged)], capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError(f"cp -c failed: {result.stderr.strip()}")
    if published.exists():
        published.rename(retired)
    staged.rename(published)
    if retired.exists():
        shutil.rmtree(retired)


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


def catalog_day_summary(catalog_path: Path, day: date) -> dict[str, float]:
    """Daily open, high, low, close and volume aggregated from the catalog's one-minute bars."""
    start, end = _local_day_bounds(day)
    bars = sorted(ParquetDataCatalog(str(catalog_path)).query_bars([BAR_TYPE], start=start, end=end), key=lambda bar: bar.ts_event)
    if not bars:
        raise ValueError(f"No bars in the catalog for {day}")
    return {
        "bars": len(bars),
        "open": bars[0].open.as_double(),
        "high": max(bar.high.as_double() for bar in bars),
        "low": min(bar.low.as_double() for bar in bars),
        "close": bars[-1].close.as_double(),
        "volume": sum(bar.volume.as_double() for bar in bars),
    }


def exchange_gaps(catalog: dict[str, float], exchange: ExchangeDay) -> dict[str, float]:
    """Catalog minus exchange for each field beyond its tolerance."""
    return summary_gaps(catalog, {name: getattr(exchange, name) for name in FIELDS})


def broker_exchange_gaps(raw_root: Path, day: date, exchange: ExchangeDay) -> dict[str, dict[str, float] | str]:
    """Each broker's daily summary minus the exchange beyond tolerance, or why it could not be compared; brokers that match are omitted."""
    result: dict[str, dict[str, float] | str] = {}
    for name, source in BROKERS.items():
        path = bar_download.raw_path(raw_root / name.lower(), CONTINUOUS_SYMBOL.value, day)
        if not path.exists():
            result[name] = "no raw data"
            continue
        bars = bar_download.read_day(path, day, VN30F1M_SESSIONS, source.bars_frame)
        gaps = exchange_gaps(day_summary(bars), exchange) if not bars.empty else {}
        if bars.empty:
            result[name] = "no bar"
        elif gaps:
            result[name] = gaps
    return result


def day_is_complete(catalog_path: Path, day: date) -> bool:
    """DNSE bars, trades and order book depth are loaded for ``day``; a minute without a trade has no bar."""
    bars, trades, depth = count_day_records(catalog_path, day)
    return bars > 0 and trades > 0 and depth > 0


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
    log_path: str,
) -> Alert:
    """A normal day shows the run and its counts; cleaned bars, unresolved bars and failed brokers add their own fields."""
    dnse = _records(report.get("dnse"))
    missing_trades = _missing_trade_contracts(report.get("dnse"))
    cleaned = report["dnse"].get("clean") if isinstance(report.get("dnse"), dict) else None
    outcome = cleaned.get("outcome") if isinstance(cleaned, dict) else None
    brokers = report.get("brokers") if isinstance(report.get("brokers"), dict) else {}
    down = {name: value for name, value in brokers.items() if not isinstance(value, int)}
    trades = f"{_count(dnse, 'TradeTick'):,}"
    if missing_trades:
        trades += f"\nINCOMPLETE, {missing_trades:,} contracts missing"
    warnings = [
        text
        for text, present in (
            ("trades incomplete", missing_trades),
            ("bars not cleaned", outcome == "unresolved"),
            (f"{', '.join(down)} down", down),
        )
        if present
    ]
    notes = warnings or (["bars cleaned"] if outcome in ("gaps_filled", "corrected") else [])
    details: list[tuple[str, str, bool]] = []
    if outcome in ("gaps_filled", "corrected"):
        details.append(("Clean", f"{len(cleaned['filled'])} filled, {len(cleaned['corrected'])} corrected", False))
    elif outcome == "unresolved":
        details.append(("Clean", _clean_gap_table(cleaned), False))
    if down:
        details.append(("Brokers", "\n".join(f"{name}\n{code_block(str(error))}" for name, error in down.items()), False))
    if details or missing_trades:
        details.append(("Log", f"`{log_path}`", False))
    return Alert(
        summary=f"{'⚠️' if warnings else '✅'} Data {day} ingested" + (f" — {', '.join(notes)}" if notes else ""),
        color=YELLOW if warnings else GREEN,
        fields=(
            ("Day", str(day), True),
            ("Attempt", attempt.label, True),
            EMPTY_INLINE_FIELD,
            *run,
            ("Bars", f"{_count(dnse, 'Bar')}/{FULL_DAY_BARS}", True),
            ("Trades", trades, True),
            ("Order book", f"{_count(dnse, 'OrderBookDepth10'):,}", True),
            *details,
        ),
    )


def _clean_gap_table(cleaned: dict[str, Any]) -> str:
    """DNSE against the brokers' daily summary for each field beyond tolerance."""
    gaps = cleaned.get("gaps") or {}
    dnse = cleaned.get("dnse") or {}
    broker_summary = cleaned.get("broker_summary") or {}
    if not gaps:
        return str(cleaned.get("reason"))
    rows = [
        f"{name:<7}{_format_number(name, dnse[name]):>12}{_format_number(name, broker_summary[name]):>12}{_format_number(name, gap, sign=True):>10}"
        for name, gap in gaps.items()
    ]
    return code_block("\n".join([f"{'':<7}{'DNSE':>12}{'brokers':>12}{'gap':>10}", *rows]))


def _format_number(name: str, value: float, *, sign: bool = False) -> str:
    """Volume as whole contracts, prices with one decimal."""
    return format(value, ("+" if sign else "") + (",.0f" if name == "volume" else ",.1f"))


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


def alert_exchange_mismatch(
    day: date,
    catalog: dict[str, float],
    exchange: ExchangeDay,
    gaps: dict[str, float],
    log_path: str,
) -> Alert:
    rows = [
        f"{field:<7}{catalog[field]:>12,.1f}{getattr(exchange, field):>12,.1f}{gaps[field]:>+12,.1f}"
        for field in ("open", "high", "low", "close", "volume")
        if field in gaps
    ]
    table = code_block("\n".join([f"{'':<7}{'catalog':>12}{'exchange':>12}{'gap':>12}", *rows]))
    return Alert(
        summary=f"⚠️ Data {day} differs from the exchange — {', '.join(gaps)}",
        color=YELLOW,
        fields=(
            ("Day", str(day), True),
            ("Contract", exchange.symbol, True),
            ("Bars", f"{int(catalog['bars'])}/{FULL_DAY_BARS}", True),
            ("Gap", table, False),
            ("Log", f"`{log_path}`", False),
        ),
    )


def alert_brokers_differ(day: date, brokers: dict[str, dict[str, float] | str], log_path: str) -> Alert:
    lines = [
        f"{name}: {value if isinstance(value, str) else ', '.join(f'{field} {_format_number(field, gap, sign=True)}' for field, gap in value.items())}"
        for name, value in brokers.items()
    ]
    return Alert(
        summary=f"⚠️ Data {day}: reference brokers differ from the exchange — {', '.join(brokers)}",
        color=YELLOW,
        fields=(("Day", str(day), True), ("Brokers", "\n".join(lines), False), ("Log", f"`{log_path}`", False)),
    )


def alert_exchange_unchecked(day: date, reason: str, log_path: str) -> Alert:
    return Alert(
        summary=f"⚠️ Data {day} not checked against the exchange — {reason}",
        color=YELLOW,
        fields=(("Day", str(day), True), ("Log", f"`{log_path}`", False)),
    )


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


def _missing_trade_contracts(report: object) -> int:
    missing = report.get("missing_trades", []) if isinstance(report, dict) else []
    return sum(int(entry["contracts"]) for entry in missing) if isinstance(missing, list) else 0


def _missing_minutes(report: object) -> list[str]:
    """Local HH:MM of the session minutes without a DNSE bar; DNSE reports them in epoch seconds."""
    value = report.get("missing_bar_timestamps", []) if isinstance(report, dict) else []
    if not isinstance(value, list):
        return []
    return [pd.Timestamp(int(ts), unit="s", tz="UTC").tz_convert(LOCAL_TIMEZONE).strftime("%H:%M") for ts in sorted(value)]


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
    run_brokers: BrokerRunner,
    run_dnse: DnseRunner,
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
    started = datetime.now(LOCAL_TIMEZONE)
    try:
        report = run_daily(
            day=day,
            run_brokers=run_brokers,
            run_dnse=run_dnse,
            consolidate=consolidate,
        )
    except Exception as error:
        send_alert(
            notifier,
            alert_failed(f"Data {day}", error, attempt, log_path, _run_fields(started, datetime.now(started.tzinfo)), day),
            raise_on_error=raise_on_error,
        )
        raise
    send_alert(
        notifier,
        alert_ingested(day, report, _run_fields(started, datetime.now(started.tzinfo)), attempt, log_path),
        raise_on_error=raise_on_error,
    )
    return report
