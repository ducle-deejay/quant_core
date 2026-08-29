from __future__ import annotations

import json
import os
import tempfile
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC
from datetime import date
from datetime import datetime
from datetime import time as datetime_time
from datetime import timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from market_data.sources.dnse.quality import validate_raw_delivery


PAGE_LIMIT = 1_000
MAX_SERVER_RETRIES = 6
MIN_REMAINING = 500
LOCAL_TIMEZONE = ZoneInfo("Asia/Ho_Chi_Minh")

ClientFactory = Callable[[], tuple[Any, list[Any]]]


def extract_day(
    *,
    client_factory: ClientFactory,
    raw_root: str | Path,
    day: date,
    continuous_symbol: str,
    request_delay_seconds: float = 0.02,
) -> None:
    """Extract one DNSE trading day while preserving provider payloads."""
    root = Path(raw_root)
    destination = root / day.isoformat()
    if destination.exists():
        validate_raw_delivery(destination)
        return None
    today = datetime.now(LOCAL_TIMEZONE).date()
    if day > today:
        raise ValueError(f"Cannot extract future date: {day}")
    if day.weekday() >= 5:
        return None

    working_dates = _get_working_dates(client_factory)
    if not working_dates:
        raise ValueError("DNSE returned no working dates")
    if day == today and day not in working_dates:
        return None
    contract = _front_month_contract(
        client_factory=client_factory,
        continuous_symbol=continuous_symbol,
        day=day,
        working_dates=working_dates,
    )

    root.mkdir(parents=True, exist_ok=True)
    _retain_contract(root / "contracts", contract)
    with tempfile.TemporaryDirectory(
        prefix=f".{day.isoformat()}-incomplete-",
        dir=root,
    ) as temporary:
        raw_day = Path(temporary) / day.isoformat()
        futures_root = raw_day / "hnx" / "futures"
        _download_bars(
            client_factory=client_factory,
            destination=futures_root / "bars" / continuous_symbol,
            symbol=continuous_symbol,
            day=day,
        )
        with ThreadPoolExecutor(max_workers=2, thread_name_prefix="dnse-extract") as executor:
            trades = executor.submit(
                _download_pages,
                client_factory=client_factory,
                destination=futures_root / "trades" / contract["symbol"] / day.isoformat(),
                response_key="trades",
                method_name="get_trades",
                symbol=contract["symbol"],
                day=day,
                request_delay_seconds=request_delay_seconds,
            )
            orderbook = executor.submit(
                _download_pages,
                client_factory=client_factory,
                destination=futures_root / "orderbook" / contract["symbol"] / day.isoformat(),
                response_key="quotes",
                method_name="get_quotes",
                symbol=contract["symbol"],
                day=day,
                request_delay_seconds=request_delay_seconds,
            )
            trades.result()
            orderbook.result()

        validate_raw_delivery(raw_day)
        os.replace(raw_day, destination)


def _retain_contract(directory: Path, contract: dict[str, str]) -> None:
    path = directory / f"{contract['symbol']}.json"
    if path.exists():
        retained = json.loads(path.read_text(encoding="utf-8"))
        if retained != contract:
            raise ValueError(f"DNSE contract metadata changed for {contract['symbol']}")
        return
    directory.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(contract, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _front_month_contract(
    *,
    client_factory: ClientFactory,
    continuous_symbol: str,
    day: date,
    working_dates: set[date],
) -> dict[str, str]:
    client, observed = client_factory()
    instruments = _decode_response(
        *client.get_instruments(market_id="DVX", security_group_id="FU", limit=100),
    )[1]
    _ensure_quota(observed[-1] if observed else None)
    if not isinstance(instruments, dict):
        raise ValueError("DNSE instruments response is not a JSON object")
    records = instruments.get("data")
    if not isinstance(records, list):
        raise ValueError("DNSE instruments response does not contain a data list")
    matches = [
        item
        for item in records
        if isinstance(item, dict) and item.get("symbolType") == continuous_symbol
    ]
    if len(matches) != 1:
        raise ValueError(f"Expected one DNSE {continuous_symbol} contract, found {len(matches)}")
    symbol = str(matches[0]["symbol"])

    definition = _decode_response(*client.get_security_definition(symbol, board_id="G1"))[1]
    _ensure_quota(observed[-1] if observed else None)
    if not isinstance(definition, list) or len(definition) != 1:
        raise ValueError(f"Unexpected DNSE security definition for {symbol}")
    record = definition[0]
    if record.get("marketId") != "DVX" or record.get("boardId") != "G1":
        raise ValueError(f"Unexpected DNSE contract identity for {symbol}: {record}")
    expiration = _front_month_expiration(day, working_dates)
    return {
        "symbol": symbol,
        "isin": str(record["isin"]),
        "expiration": expiration.isoformat(),
    }


def _get_working_dates(client_factory: ClientFactory) -> set[date]:
    client, observed = client_factory()
    payload = _decode_response(*client.get_working_dates())[1]
    _ensure_quota(observed[-1] if observed else None)
    if not isinstance(payload, dict):
        raise ValueError("DNSE working-dates response is not a JSON object")
    values = payload.get("workingDates")
    if not isinstance(values, list):
        raise ValueError("DNSE working-dates response does not contain workingDates")
    return {date.fromisoformat(str(value)) for value in values}


def _front_month_expiration(day: date, working_dates: set[date]) -> datetime:
    year = day.year
    month = day.month
    candidate = _third_thursday(year, month)
    if day >= candidate:
        month += 1
        if month == 13:
            year += 1
            month = 1
        candidate = _third_thursday(year, month)
    while candidate not in working_dates:
        candidate -= timedelta(days=1)
    return datetime.combine(candidate, datetime_time(14, 45), tzinfo=LOCAL_TIMEZONE).astimezone(UTC)


def _third_thursday(year: int, month: int) -> date:
    first = date(year, month, 1)
    return first + timedelta(days=(3 - first.weekday()) % 7 + 14)


def _download_bars(
    *,
    client_factory: ClientFactory,
    destination: Path,
    symbol: str,
    day: date,
) -> None:
    client, observed = client_factory()
    raw, payload = _decode_response(
        *client.get_ohlc(
            "DERIVATIVE",
            {
                "symbol": symbol,
                "resolution": "1",
                "from": _timestamp(day),
                "to": _timestamp(day + timedelta(days=1)),
            },
        ),
    )
    _ensure_quota(observed[-1] if observed else None)
    if not isinstance(payload, dict):
        raise ValueError("DNSE OHLC response is not a JSON object")
    lengths = {key: len(payload.get(key, [])) for key in ("t", "o", "h", "l", "c", "v")}
    if len(set(lengths.values())) != 1:
        raise ValueError(f"Misaligned DNSE OHLCV arrays for {day}: {lengths}")
    _write_payload(destination / f"1m_{day:%Y%m%d}_{day:%Y%m%d}.json", raw)


def _download_pages(
    *,
    client_factory: ClientFactory,
    destination: Path,
    response_key: str,
    method_name: str,
    symbol: str,
    day: date,
    request_delay_seconds: float,
) -> None:
    client, observed = client_factory()
    method = getattr(client, method_name)
    next_token: str | None = None
    seen_tokens: set[str] = set()
    page_number = 1

    while True:
        observed.clear()

        def request(token: str | None = next_token) -> tuple[int, Any]:
            return method(
                symbol,
                board_id="G1",
                from_date=_timestamp(day),
                to_date=_timestamp(day + timedelta(days=1)),
                limit=PAGE_LIMIT,
                next_page_token=token,
            )

        raw, payload = _request_with_retries(request)
        if not isinstance(payload, dict):
            raise ValueError(f"DNSE {response_key} response is not a JSON object")
        if not isinstance(payload.get(response_key), list):
            raise ValueError(f"DNSE response does not contain a {response_key} list")
        _write_payload(destination / f"page_{page_number:05d}.json", raw)
        _ensure_quota(observed[-1] if observed else None)

        token = payload.get("nextPageToken")
        if not token:
            return
        token = str(token)
        if token in seen_tokens:
            raise ValueError(f"DNSE repeated pagination token for {response_key}/{day}")
        seen_tokens.add(token)
        next_token = token
        page_number += 1
        if request_delay_seconds > 0:
            time.sleep(request_delay_seconds)


def _request_with_retries(request: Callable[[], tuple[int, Any]]) -> tuple[str, Any]:
    for attempt in range(MAX_SERVER_RETRIES):
        try:
            status, body = request()
        except Exception:
            if attempt == MAX_SERVER_RETRIES - 1:
                raise
            time.sleep(min(30.0, 2.0 ** (attempt + 1)))
            continue
        if status == 200 or status < 500 or attempt == MAX_SERVER_RETRIES - 1:
            return _decode_response(status, body)
        time.sleep(min(30.0, 2.0 ** (attempt + 1)))
    raise RuntimeError("DNSE request retries exhausted")


def _decode_response(status: int, body: Any) -> tuple[str, Any]:
    if status != 200:
        raise RuntimeError(f"DNSE request failed with status={status}: {body}")
    if not isinstance(body, str):
        raise ValueError(f"Unexpected DNSE SDK response type: {type(body)}")
    return body, json.loads(body)


def _ensure_quota(rate_limit: Any | None) -> None:
    if rate_limit is not None and int(rate_limit.remaining) < MIN_REMAINING:
        raise RuntimeError(
            f"Stopped before DNSE quota exhaustion: remaining={rate_limit.remaining}",
        )


def _timestamp(day: date) -> int:
    return int(datetime.combine(day, datetime.min.time(), tzinfo=UTC).timestamp())


def _write_payload(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
