from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pandas as pd
from nautilus_trader.model import Bar
from nautilus_trader.model import BarType

from market_data.sources.legacy_boundary import legacy_boundary_record_mask
from market_data.sources.mirae.quality import read_json
from nautilus_bridge.instruments.derivatives.futures.vn30f1m import VN30F1M_SESSIONS
from nautilus_bridge.instruments.derivatives.futures.vn30f1m import (
    build_continuous_futures_contract,
)


BAR_TYPE = "VN30F1M.HNX-1-MINUTE-LAST-EXTERNAL"
LOCAL_TIMEZONE = "Asia/Ho_Chi_Minh"
# External payloads include two session-boundary records at 11:30 and 14:30 local
# time (verified in data/raw/vietnam/{dnse,mirae}, 2026-09-30); the canonical session
# grid has 241 bars (verified in data/catalog: 09:00-11:29, 13:00-14:29 and 14:45).
# Bars are labelled at the minute open. Nautilus releases a bar at ts_init, which must be
# the interval close, so ts_init = ts_event + 1 minute. The 14:45 bar is the ATC
# (at-the-close auction) print, a single event known at 14:45 (HNX derivatives
# closing auction 14:30-14:45; DNSE trading-hours guide), so its ts_init stays at ts_event.
ONE_MINUTE_NS = 60_000_000_000


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
                _bar_ts_init(timestamp, ts_event),
            ),
        )
    return bars


def _bar_ts_init(timestamp: pd.Timestamp, ts_event: int) -> int:
    if VN30F1M_SESSIONS.is_closing_auction(pd.Timestamp(timestamp)):
        return ts_event
    return ts_event + ONE_MINUTE_NS


def _normalize_boundary_bars(
    frame: pd.DataFrame,
    *,
    bar_type: object,
) -> pd.DataFrame:
    """Merge 11:30/14:30 boundary rows into the preceding minute and keep only
    canonical session minutes; no-op for other bar types."""
    if str(bar_type) != BAR_TYPE or frame.empty:
        return frame

    boundary_mask = legacy_boundary_record_mask(frame["timestamp"])
    normalized = frame.copy()
    boundary_indices: list[int] = []
    if boundary_mask.any():
        timestamp_indices = normalized.groupby("timestamp", sort=False).groups
        for index, row in normalized.loc[boundary_mask].iterrows():
            timestamp = pd.Timestamp(row["timestamp"])
            predecessor_timestamp = timestamp - pd.Timedelta(minutes=1)
            predecessor_indices = timestamp_indices.get(predecessor_timestamp, ())
            if len(predecessor_indices) == 0:
                normalized.at[index, "timestamp"] = predecessor_timestamp
                continue
            if len(predecessor_indices) != 1:
                expected_minute = predecessor_timestamp.tz_convert(
                    VN30F1M_SESSIONS.timezone,
                ).strftime("%H:%M")
                raise ValueError(
                    "Cannot normalize VN30F1M.HNX one-minute bar at "
                    f"{timestamp}: expected exactly one {expected_minute} predecessor",
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

    canonical_mask = VN30F1M_SESSIONS.session_minute_mask(normalized["timestamp"])
    return normalized.loc[canonical_mask].reset_index(drop=True)


def _ingestion_day_ts_ns(raw_day: Path) -> int:
    """Stamp instrument definitions at the ingestion day's UTC midnight, so the
    definition precedes that day's data and replays stay deterministic."""
    from datetime import date

    return int(pd.Timestamp(date.fromisoformat(raw_day.name), tz="UTC").value)
