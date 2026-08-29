from __future__ import annotations

import json
import re
from datetime import UTC
from datetime import date
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np


BAR_FILE = re.compile(r"^1m_(?P<start>\d{8})_(?P<end>\d{8})\.json$")


def validate_raw_day(raw_day: str | Path) -> int:
    """Reject incomplete or internally inconsistent retained Mirae candlesticks."""
    root = Path(raw_day) / "hnx" / "futures" / "bars"
    paths = sorted(root.glob("*/*.json"))
    if not paths:
        raise FileNotFoundError(f"No Mirae candlestick payloads found under {root}")

    timestamps: set[int] = set()
    records = 0
    for path in paths:
        match = BAR_FILE.fullmatch(path.name)
        if match is None:
            raise ValueError(f"Invalid Mirae candlestick filename: {path}")
        start = datetime.strptime(match.group("start"), "%Y%m%d").date()
        end = datetime.strptime(match.group("end"), "%Y%m%d").date()
        if start > end:
            raise ValueError(f"Invalid Mirae candlestick date range: {path}")
        payload = read_json(path)
        fields = ("t", "o", "h", "l", "c", "v")
        lengths = {field: len(payload.get(field, [])) for field in fields}
        if len(set(lengths.values())) != 1:
            raise ValueError(f"Mirae OHLCV arrays are misaligned in {path}: {lengths}")
        if not lengths["t"]:
            raise ValueError(f"Mirae candlestick payload is empty: {path}")
        current = [int(float(value)) for value in payload["t"]]
        normalized = _validate_timestamps(current, start, end, path)
        if len(set(current)) != len(current):
            raise ValueError(f"Mirae contains duplicate candlestick timestamps in {path}")
        duplicates = timestamps.intersection(normalized)
        if duplicates:
            raise ValueError(f"Mirae contains duplicate candlestick timestamps under {root}")
        timestamps.update(normalized)
        _validate_ohlcv(payload, path)
        records += len(normalized)
    return records


def read_json(path: str | Path) -> dict[str, Any]:
    source = Path(path)
    payload = json.loads(source.read_bytes())
    if not isinstance(payload, dict):
        raise ValueError(f"Expected a JSON object in {source}")
    return payload


def validate_transformed_bars(data: list[Any]) -> None:
    """Reject an empty, unordered, or duplicate candidate bar batch before loading."""
    if not data:
        raise ValueError("Cannot load an empty transformed Mirae bar batch")
    timestamps = [bar.ts_event for bar in data]
    if timestamps != sorted(timestamps) or len(set(timestamps)) != len(timestamps):
        raise ValueError("Transformed Mirae bar timestamps must be strictly increasing")


def _validate_timestamps(
    timestamps: list[int],
    start: date,
    end: date,
    path: Path,
) -> set[int]:
    normalized = {timestamp // 60 * 60 for timestamp in timestamps}
    start_timestamp = int(datetime.combine(start, datetime.min.time(), tzinfo=UTC).timestamp())
    end_timestamp = int(datetime.combine(end, datetime.min.time(), tzinfo=UTC).timestamp()) + 86_400
    if any(timestamp < start_timestamp or timestamp >= end_timestamp for timestamp in timestamps):
        raise ValueError(f"Mirae candlestick timestamp is outside filename range: {path}")
    return normalized


def _validate_ohlcv(payload: dict[str, Any], path: Path) -> None:
    prices = np.asarray([payload[field] for field in ("o", "h", "l", "c")], dtype=float)
    volumes = np.asarray(payload["v"], dtype=float)
    if not np.isfinite(prices).all() or not np.allclose(prices * 10, np.round(prices * 10)):
        raise ValueError(f"Mirae candlestick prices do not conform to precision 1: {path}")
    if (
        not np.isfinite(volumes).all()
        or (volumes < 0).any()
        or not np.allclose(volumes, np.round(volumes))
    ):
        raise ValueError(f"Mirae candlestick volumes do not conform to precision 0: {path}")
    opens, highs, lows, closes = prices
    if (highs < np.maximum(opens, closes)).any() or (lows > np.minimum(opens, closes)).any():
        raise ValueError(f"Mirae candlestick OHLC relationship is invalid: {path}")
