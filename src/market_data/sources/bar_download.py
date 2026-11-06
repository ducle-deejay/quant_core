"""One-minute bars downloaded from a chart API, retained as raw JSON per symbol and day."""

from __future__ import annotations

import json
import ssl
from collections.abc import Callable
from datetime import date
from datetime import datetime
from datetime import timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd
import truststore
import urllib3

from market_data.sources.session_boundary import normalize_boundary_bars
from nautilus_bridge.instruments.derivatives.futures.vn30f1m import TradingSessions


BAR_COLUMNS = ["timestamp", "open", "high", "low", "close", "volume"]

BarsRequest = Callable[[str, int, int], Any]  # symbol, start and end in epoch seconds
BarsFrame = Callable[[Any], pd.DataFrame]


def session_window(day: date, sessions: TradingSessions) -> tuple[int, int]:
    """Epoch seconds from the first session's start to 15 minutes after the closing auction on ``day``."""
    zone = ZoneInfo(sessions.timezone)
    start = datetime.combine(day, sessions.continuous[0][0], zone)
    end = datetime.combine(day, sessions.closing_auction, zone) + timedelta(minutes=15)
    return int(start.timestamp()), int(end.timestamp())


def get_json(url: str, *, origin: str, fields: dict[str, object] | None = None) -> Any:
    http = urllib3.PoolManager(ssl_context=truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT))
    try:
        response = http.request(
            "GET",
            url,
            fields=fields,
            headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json", "Origin": origin, "Referer": f"{origin}/"},
            timeout=urllib3.Timeout(connect=30.0, read=60.0),
        )
        if not 200 <= response.status < 300:
            raise RuntimeError(f"{url} failed with status={response.status}")
        return json.loads(response.data)
    finally:
        http.clear()


def raw_path(raw_root: Path, symbol: str, day: date) -> Path:
    return raw_root / symbol / f"{day.isoformat()}.json"


def extract_day(
    *,
    raw_root: Path,
    symbol: str,
    day: date,
    sessions: TradingSessions,
    request: BarsRequest,
    frame: BarsFrame,
) -> Path | None:
    """Retain one day's response as raw JSON; None while the source has no bar for the day."""
    path = raw_path(raw_root, symbol, day)
    if path.exists():
        return path
    payload = request(symbol, *session_window(day, sessions))
    if day_bars(payload, day, sessions, frame).empty:
        return None
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(payload), encoding="utf-8")
    temporary.replace(path)
    return path


def read_day(path: Path, day: date, sessions: TradingSessions, frame: BarsFrame) -> pd.DataFrame:
    return day_bars(json.loads(path.read_text(encoding="utf-8")), day, sessions, frame)


def day_bars(payload: Any, day: date, sessions: TradingSessions, frame: BarsFrame) -> pd.DataFrame:
    """The day's bars on session minutes, sorted by open time."""
    bars = frame(payload)
    if bars.empty:
        return pd.DataFrame(columns=BAR_COLUMNS)
    bars = bars.sort_values("timestamp", kind="stable")
    bars = bars[bars["timestamp"].dt.tz_convert(sessions.timezone).dt.date == day].reset_index(drop=True)
    return normalize_boundary_bars(bars, sessions)[BAR_COLUMNS]


def columnar_frame(data: dict[str, list[Any]]) -> pd.DataFrame:
    """Bars from TradingView-style columns t, o, h, l, c, v with t in epoch seconds."""
    return pd.DataFrame(
        {
            "timestamp": pd.to_datetime(data.get("t") or [], unit="s", utc=True),
            "open": data.get("o") or [],
            "high": data.get("h") or [],
            "low": data.get("l") or [],
            "close": data.get("c") or [],
            "volume": data.get("v") or [],
        },
    )
