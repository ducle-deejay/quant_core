from __future__ import annotations

import json
import os
import ssl
import tempfile
from collections.abc import Callable
from collections.abc import Iterable
from datetime import UTC
from datetime import date
from datetime import datetime
from datetime import timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import truststore
import urllib3

from market_data.sources.mirae.quality import validate_raw_day


MIRAE_HISTORY_URL = "https://mastrade.masvn.com/api/v1/tradingview/history"
MIRAE_HEADERS = {
    "Referer": "https://mastrade.masvn.com/board/futures",
    "platform": "WEB",
}
HISTORY_START = date(2017, 8, 10)
HISTORY_CHUNK_DAYS = 30
LOCAL_TIMEZONE = ZoneInfo("Asia/Ho_Chi_Minh")

HistoryRequest = Callable[[dict[str, int | str]], dict[str, Any]]


def extract_day(
    *,
    request_history: HistoryRequest,
    active_contract: str | None,
    raw_root: str | Path,
    day: date,
    continuous_symbol: str,
) -> None:
    """Retain an initial Mirae history or one scheduled daily append."""
    root = Path(raw_root)
    destination = root / day.isoformat()
    if destination.exists():
        validate_raw_day(destination)
        return

    today = _current_local_date()
    if day > today:
        raise ValueError(f"Cannot use a future acquisition date: {day}")

    if _has_retained_history(root):
        symbol = active_contract if day == today else continuous_symbol
        if symbol is None:
            return
        payload = _request_daily_payload(
            request_history=request_history,
            symbol=symbol,
            day=day,
            today=today,
        )
    else:
        symbol = continuous_symbol
        payload = _request_initial_history(
            request_history=request_history,
            continuous_symbol=continuous_symbol,
            acquisition_day=day,
        )
        if day == today and active_contract is not None:
            current = _request_daily_payload(
                request_history=request_history,
                symbol=active_contract,
                day=day,
                today=today,
            )
            payload = _combine_payloads([payload, current])

    if payload is None:
        return
    start, end = _payload_date_range(payload)
    _retain_snapshot(
        root=root,
        acquisition_day=day,
        symbol=symbol,
        start=start,
        end=end,
        payload=payload,
    )


def request_mirae_history(params: dict[str, int | str]) -> dict[str, Any]:
    """Request one Mirae TradingView history payload."""
    http = urllib3.PoolManager(
        ssl_context=truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT),
    )
    try:
        response = http.request(
            "GET",
            MIRAE_HISTORY_URL,
            fields={key: str(value) for key, value in params.items()},
            headers={
                "Accept": "application/json, text/plain, */*",
                "User-Agent": "Mozilla/5.0",
                **MIRAE_HEADERS,
            },
            timeout=urllib3.Timeout(connect=30.0, read=60.0),
        )
        if not 200 <= response.status < 300:
            raise RuntimeError(f"Mirae history request failed with status={response.status}")
        payload = json.loads(response.data)
    finally:
        http.clear()
    if not isinstance(payload, dict):
        raise ValueError(f"Unexpected Mirae response type: {type(payload).__name__}")
    return payload


def _has_retained_history(root: Path) -> bool:
    if not root.exists():
        return False
    return any(path.is_dir() and _is_acquisition_date(path.name) for path in root.iterdir())


def _is_acquisition_date(value: str) -> bool:
    try:
        date.fromisoformat(value)
    except ValueError:
        return False
    return True


def _request_initial_history(
    *,
    request_history: HistoryRequest,
    continuous_symbol: str,
    acquisition_day: date,
) -> dict[str, Any] | None:
    stop = acquisition_day + timedelta(days=1)
    payloads = []
    start = HISTORY_START
    while start < stop:
        chunk_stop = min(start + timedelta(days=HISTORY_CHUNK_DAYS), stop)
        payloads.append(
            request_history(
                {
                    "symbol": continuous_symbol,
                    "resolution": "1",
                    "from": _timestamp(start),
                    "to": _timestamp(chunk_stop),
                },
            ),
        )
        start = chunk_stop
    return _combine_payloads(payloads)


def _request_daily_payload(
    *,
    request_history: HistoryRequest,
    symbol: str,
    day: date,
    today: date,
) -> dict[str, Any] | None:
    stop = _timestamp(day + timedelta(days=1))
    if day == today:
        stop = min(stop, _current_utc_timestamp())
    if stop <= _timestamp(day):
        return None
    return _validated_payload(
        request_history(
            {
                "symbol": symbol,
                "resolution": "1",
                "from": _timestamp(day),
                "to": stop,
            },
        ),
    )


def _combine_payloads(payloads: Iterable[dict[str, Any] | None]) -> dict[str, Any] | None:
    fields = ("t", "o", "h", "l", "c", "v")
    rows: dict[int, tuple[Any, ...]] = {}
    for payload in payloads:
        validated = _validated_payload(payload)
        if validated is None:
            continue
        values = [validated[field] for field in fields]
        for row in zip(*values, strict=True):
            rows[int(float(row[0]))] = row
    if not rows:
        return None
    ordered = [rows[timestamp] for timestamp in sorted(rows)]
    merged = {field: [row[index] for row in ordered] for index, field in enumerate(fields)}
    return {"s": "ok", **merged}


def _validated_payload(payload: dict[str, Any] | None) -> dict[str, Any] | None:
    if payload is None:
        return None
    if not isinstance(payload, dict):
        raise ValueError(f"Unexpected Mirae response type: {type(payload).__name__}")
    data = _unwrap_response(payload)
    status = data.get("s")
    if status == "no_data":
        return None
    if status != "ok":
        raise RuntimeError(f"Mirae returned an unexpected history status: {status}")
    fields = ("t", "o", "h", "l", "c", "v")
    lengths = {field: len(data.get(field, [])) for field in fields}
    if len(set(lengths.values())) != 1:
        raise ValueError(f"Mirae OHLCV arrays are misaligned: {lengths}")
    if not lengths["t"]:
        return None
    return data


def _unwrap_response(payload: dict[str, Any]) -> dict[str, Any]:
    if payload.get("code") not in (None, "SUCCESS"):
        raise RuntimeError(f"Mirae returned an unsuccessful response: {payload}")
    data = payload.get("data", payload)
    if not isinstance(data, dict):
        raise ValueError(f"Unexpected Mirae data type: {type(data).__name__}")
    return data


def _payload_date_range(payload: dict[str, Any]) -> tuple[date, date]:
    timestamps = [datetime.fromtimestamp(float(value), UTC).date() for value in payload["t"]]
    return min(timestamps), max(timestamps)


def _retain_snapshot(
    *,
    root: Path,
    acquisition_day: date,
    symbol: str,
    start: date,
    end: date,
    payload: dict[str, Any],
) -> None:
    root.mkdir(parents=True, exist_ok=True)
    destination = root / acquisition_day.isoformat()
    with tempfile.TemporaryDirectory(
        prefix=f".{acquisition_day.isoformat()}-incomplete-",
        dir=root,
    ) as temporary:
        raw_day = Path(temporary) / acquisition_day.isoformat()
        destination_file = (
            raw_day / "hnx" / "futures" / "bars" / symbol / f"1m_{start:%Y%m%d}_{end:%Y%m%d}.json"
        )
        destination_file.parent.mkdir(parents=True, exist_ok=True)
        destination_file.write_text(json.dumps(payload), encoding="utf-8")
        validate_raw_day(raw_day)
        os.replace(raw_day, destination)


def _timestamp(day: date) -> int:
    return int(datetime.combine(day, datetime.min.time(), tzinfo=UTC).timestamp())


def _current_local_date() -> date:
    return datetime.now(LOCAL_TIMEZONE).date()


def _current_utc_timestamp() -> int:
    return int(datetime.now(UTC).timestamp())
