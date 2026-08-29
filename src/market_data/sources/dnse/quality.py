from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import UTC
from datetime import date
from datetime import datetime
from datetime import timedelta
from pathlib import Path
from typing import Any


BAR_FILE = re.compile(r"^(?P<interval>[^_]+)_(?P<start>\d{8})_(?P<end>\d{8})\.json$")
PAGE_FILE = re.compile(r"^page_(?P<number>\d{5})\.json$")


@dataclass(frozen=True)
class RawDayValidation:
    """Describe structurally valid DNSE payloads and any missing session bars."""

    counts: dict[str, int]
    missing_bar_timestamps: tuple[int, ...]


def validate_raw_day(raw_day: str | Path) -> dict[str, int]:
    """Reject incomplete or internally inconsistent retained DNSE payloads."""
    validation = validate_raw_delivery(raw_day)
    if validation.missing_bar_timestamps:
        first_missing = datetime.fromtimestamp(validation.missing_bar_timestamps[0], UTC).date()
        raise ValueError(f"DNSE one-minute bar coverage is incomplete for {first_missing}")
    return validation.counts


def validate_raw_delivery(raw_day: str | Path) -> RawDayValidation:
    """Validate retained provider payloads while reporting recoverable bar gaps."""
    root = Path(raw_day) / "hnx" / "futures"
    if not root.is_dir():
        raise FileNotFoundError(f"DNSE futures raw directory does not exist: {root}")
    bar_count, missing_bar_timestamps = _validate_bars(root / "bars")
    counts = {
        "bars": bar_count,
        "trades": _validate_pages(root / "trades", response_key="trades"),
        "orderbook": _validate_pages(root / "orderbook", response_key="quotes"),
    }
    if any(count == 0 for count in counts.values()):
        raise ValueError(f"DNSE trading-day raw data contains an empty category: {raw_day}")
    return RawDayValidation(
        counts=counts,
        missing_bar_timestamps=missing_bar_timestamps,
    )


def read_json(path: str | Path) -> dict[str, Any]:
    source = Path(path)
    payload = json.loads(source.read_bytes())
    if not isinstance(payload, dict):
        raise ValueError(f"Expected a JSON object in {source}")
    return payload


def page_number(path: str | Path) -> int:
    match = PAGE_FILE.fullmatch(Path(path).name)
    if match is None:
        raise ValueError(f"Invalid DNSE page filename: {path}")
    return int(match.group("number"))


def validate_transformed_batch(data: list[Any]) -> None:
    if not data:
        raise ValueError("Cannot load an empty transformed batch")
    timestamps = [item.ts_init for item in data if hasattr(item, "ts_init")]
    if timestamps != sorted(timestamps):
        raise ValueError(f"Transformed {type(data[0]).__name__} timestamps are not monotonic")
    if type(data[0]).__name__ == "OrderBookDepth10":
        for depth in data:
            if len(depth.bids) != 10 or len(depth.asks) != 10:
                raise ValueError("DNSE depth does not contain exactly 10 levels per side")
            if any(depth.bid_counts) or any(depth.ask_counts):
                raise ValueError("DNSE depth invents order counts")
            if depth.flags != 0 or depth.sequence != 0 or depth.ts_init != depth.ts_event:
                raise ValueError("DNSE depth metadata violates the catalog contract")


def _validate_bars(directory: Path) -> tuple[int, tuple[int, ...]]:
    paths = sorted(directory.glob("*/*.json"))
    if not paths:
        raise FileNotFoundError(f"No DNSE bar payloads found under {directory}")
    observed_timestamps: set[int] = set()
    missing_timestamps: list[int] = []
    records = 0
    for path in paths:
        match = BAR_FILE.fullmatch(path.name)
        if match is None:
            raise ValueError(f"Invalid DNSE bar filename: {path}")
        start = datetime.strptime(match.group("start"), "%Y%m%d").date()
        end = datetime.strptime(match.group("end"), "%Y%m%d").date()
        if start > end:
            raise ValueError(f"Invalid DNSE bar date range: {path}")
        payload = read_json(path)
        fields = ("t", "o", "h", "l", "c", "v")
        lengths = {field: len(payload.get(field, [])) for field in fields}
        if len(set(lengths.values())) != 1:
            raise ValueError(f"DNSE OHLCV arrays are misaligned in {path}: {lengths}")
        timestamps = [int(value) for value in payload["t"]]
        if any(datetime.fromtimestamp(value, UTC).date() < start for value in timestamps):
            raise ValueError(f"DNSE bar timestamp precedes filename range: {path}")
        if any(datetime.fromtimestamp(value, UTC).date() > end for value in timestamps):
            raise ValueError(f"DNSE bar timestamp exceeds filename range: {path}")
        duplicates = observed_timestamps.intersection(timestamps)
        if duplicates:
            raise ValueError(f"DNSE contains duplicate bar timestamps under {directory}")
        observed_timestamps.update(timestamps)
        if start == end:
            missing_timestamps.extend(_missing_session_bars(timestamps, start))
        records += lengths["t"]
    return records, tuple(missing_timestamps)


def _missing_session_bars(timestamps: list[int], day: date) -> tuple[int, ...]:
    expected = _expected_current_session(day)
    expected_set = set(expected)
    observed = set(timestamps)
    if any(timestamp not in expected_set for timestamp in timestamps):
        raise ValueError(f"DNSE contains out-of-session bars for {day}")
    if timestamps != [timestamp for timestamp in expected if timestamp in observed]:
        raise ValueError(f"DNSE one-minute bars are not in session order for {day}")
    return tuple(timestamp for timestamp in expected if timestamp not in observed)


def _validate_pages(directory: Path, *, response_key: str) -> int:
    day_directories = sorted(path for path in directory.glob("*/*") if path.is_dir())
    if not day_directories:
        raise FileNotFoundError(f"No DNSE {response_key} payloads found under {directory}")
    return sum(_validate_page_directory(path, response_key) for path in day_directories)


def _validate_page_directory(directory: Path, response_key: str) -> int:
    symbol = directory.parent.name
    data_date = date.fromisoformat(directory.name)
    paths = sorted(directory.glob("page_*.json"))
    numbers = [page_number(path) for path in paths]
    if numbers != list(range(1, len(paths) + 1)):
        raise ValueError(f"DNSE page sequence is incomplete under {directory}")

    records = 0
    for index, path in enumerate(paths):
        payload = read_json(path)
        rows = payload.get(response_key)
        if not isinstance(rows, list):
            raise ValueError(f"DNSE payload does not contain {response_key}: {path}")
        if bool(payload.get("nextPageToken")) != (index < len(paths) - 1):
            raise ValueError(f"DNSE pagination terminates incorrectly at {path}")
        _validate_page_rows(rows, symbol=symbol, data_date=data_date, path=path)
        records += len(rows)
    return records


def _validate_page_rows(
    rows: list[dict[str, Any]],
    *,
    symbol: str,
    data_date: date,
    path: Path,
) -> None:
    for row in rows:
        _validate_provider_identity(row, symbol, path)
        if datetime.fromisoformat(str(row["time"])).date() != data_date:
            raise ValueError(f"DNSE record is outside {data_date}: {path}")


def _validate_provider_identity(row: dict[str, Any], symbol: str, path: Path) -> None:
    expected = {"symbol": symbol, "marketId": "DVX", "boardId": "G1"}
    actual = {key: row.get(key) for key in expected}
    if actual != expected or not row.get("isin"):
        raise ValueError(f"Unexpected DNSE identity in {path}: {actual}")


def _expected_current_session(day: date) -> list[int]:
    start = datetime(day.year, day.month, day.day, 2, 0, tzinfo=UTC)
    morning = [start + timedelta(minutes=value) for value in range(150)]
    afternoon_start = start.replace(hour=6)
    afternoon = [afternoon_start + timedelta(minutes=value) for value in range(90)]
    timestamps = [*morning, *afternoon, start.replace(hour=7, minute=45)]
    return [int(value.timestamp()) for value in timestamps]
