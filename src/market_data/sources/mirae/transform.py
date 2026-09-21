from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pandas as pd
from nautilus_trader.model import Bar
from nautilus_trader.model import BarType

from market_data.sources.mirae.quality import read_json
from nautilus_bridge.instruments.derivatives.futures.vn30f1m import (
    build_continuous_futures_contract,
)


BAR_TYPE = "VN30F1M.HNX-1-MINUTE-LAST-EXTERNAL"
LOCAL_TIMEZONE = "Asia/Ho_Chi_Minh"
# External payloads can include two session-boundary records at 11:30 and
# 14:30 local time; the canonical session grid has 241 bars.
BOUNDARY_PREDECESSORS = {(11, 30): (11, 29), (14, 30): (14, 29)}


def transform_day(
    *,
    raw_day: str | Path,
) -> Iterator[list[Any]]:
    """Transform one retained Mirae candlestick ingestion into Nautilus objects."""
    ingestion_ts_ns = _ingestion_day_ts_ns(Path(raw_day))
    continuous = build_continuous_futures_contract(
        ts_event=ingestion_ts_ns,
        ts_init=ingestion_ts_ns,
    )
    yield [continuous]

    root = Path(raw_day) / "hnx" / "futures" / "bars"
    for path in sorted(root.glob("*/*.json")):
        yield _transform_bars(path, continuous)


def _transform_bars(path: Path, instrument: Any) -> list[Any]:
    payload = read_json(path)
    frame = pd.DataFrame(
        {
            "timestamp": pd.to_datetime(payload["t"], unit="s", utc=True).floor("min"),
            "open": payload["o"],
            "high": payload["h"],
            "low": payload["l"],
            "close": payload["c"],
            "volume": payload["v"],
        },
    ).sort_values("timestamp", kind="stable")
    frame = frame.drop_duplicates(subset="timestamp", keep="last")
    bar_type = BarType.from_str(BAR_TYPE)
    frame = _normalize_boundary_bars(frame, bar_type=bar_type)
    bars: list[Bar] = []
    for timestamp, open_, high, low, close, volume in zip(
        frame["timestamp"],
        frame["open"],
        frame["high"],
        frame["low"],
        frame["close"],
        frame["volume"],
        strict=True,
    ):
        ts_event = int(pd.Timestamp(timestamp).value)
        bars.append(
            Bar(
                bar_type,
                instrument.make_price(open_),
                instrument.make_price(high),
                instrument.make_price(low),
                instrument.make_price(close),
                instrument.make_qty(volume),
                ts_event,
                ts_event,
            ),
        )
    return bars


def _normalize_boundary_bars(
    frame: pd.DataFrame,
    *,
    bar_type: object,
) -> pd.DataFrame:
    """Merge session-boundary rows for the target external bar type."""
    if str(bar_type) != BAR_TYPE or frame.empty:
        return frame

    local_timestamps = frame["timestamp"].dt.tz_convert(LOCAL_TIMEZONE)
    boundary_mask = (
        local_timestamps.dt.hour.eq(11) & local_timestamps.dt.minute.eq(30)
    ) | (
        local_timestamps.dt.hour.eq(14) & local_timestamps.dt.minute.eq(30)
    )
    normalized = frame.copy()
    boundary_indices: list[int] = []
    if boundary_mask.any():
        timestamp_indices = normalized.groupby("timestamp", sort=False).groups
        for index, row in normalized.loc[boundary_mask].iterrows():
            timestamp = pd.Timestamp(row["timestamp"])
            local_timestamp = timestamp.tz_convert(LOCAL_TIMEZONE)
            boundary_minute = (local_timestamp.hour, local_timestamp.minute)

            predecessor_timestamp = timestamp - pd.Timedelta(minutes=1)
            predecessor_indices = timestamp_indices.get(predecessor_timestamp, ())
            if len(predecessor_indices) == 0:
                normalized.at[index, "timestamp"] = predecessor_timestamp
                continue
            if len(predecessor_indices) != 1:
                expected_minute = BOUNDARY_PREDECESSORS[boundary_minute]
                raise ValueError(
                    "Cannot normalize VN30F1M.HNX one-minute bar at "
                    f"{timestamp}: expected exactly one {expected_minute[0]:02d}:"
                    f"{expected_minute[1]:02d} predecessor",
                )

            predecessor_index = predecessor_indices[0]
            normalized.at[predecessor_index, "high"] = max(
                normalized.at[predecessor_index, "high"],
                row["high"],
            )
            normalized.at[predecessor_index, "low"] = min(
                normalized.at[predecessor_index, "low"],
                row["low"],
            )
            normalized.at[predecessor_index, "close"] = row["close"]
            normalized.at[predecessor_index, "volume"] += row["volume"]
            boundary_indices.append(index)

        if boundary_indices:
            normalized = normalized.drop(index=boundary_indices)

    local_timestamps = normalized["timestamp"].dt.tz_convert(LOCAL_TIMEZONE)
    canonical_mask = (
        (
            local_timestamps.dt.hour.eq(9)
            | local_timestamps.dt.hour.eq(10)
            | (local_timestamps.dt.hour.eq(11) & local_timestamps.dt.minute.le(29))
        )
        | (
            local_timestamps.dt.hour.eq(13)
            | (local_timestamps.dt.hour.eq(14) & local_timestamps.dt.minute.le(29))
        )
        | (local_timestamps.dt.hour.eq(14) & local_timestamps.dt.minute.eq(45))
    )
    return normalized.loc[canonical_mask].reset_index(drop=True)


def _ingestion_day_ts_ns(raw_day: Path) -> int:
    """Stamp instrument definitions at the ingestion day's UTC midnight, so the
    definition precedes that day's data and replays stay deterministic."""
    from datetime import date

    return int(pd.Timestamp(date.fromisoformat(raw_day.name), tz="UTC").value)
