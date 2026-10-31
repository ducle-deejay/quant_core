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
from datetime import time as time_of_day
from datetime import timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from market_data.sources.dnse.validate import validate_raw_delivery
from market_data.sources.paged_download import PageFetcher
from market_data.sources.paged_download import RateLimited
from market_data.sources.paged_download import download_windows
from market_data.sources.paged_download import split_range
from nautilus_bridge.instruments.derivatives.futures.vn30f1m import VN30F1M_SESSIONS
from nautilus_bridge.instruments.derivatives.futures.vn30f1m import vn30f1m_contract


PAGE_LIMIT = 1_000
PAGE_WORKERS = 6
PAGE_WINDOW_BOUNDARIES = tuple(time_of_day(hour, minute) for hour in range(9, 15) for minute in (0, 30))
# DNSE hourly rate limit exceeded (https://developers.dnse.com.vn/docs/guide/ratelimits/)
TOO_MANY_REQUESTS = 429
MAX_SERVER_RETRIES = 6
MIN_REMAINING = 500
LOCAL_TIMEZONE = ZoneInfo(VN30F1M_SESSIONS.timezone)
WORKING_DATES_FILE = "working_dates.json"

ClientFactory = Callable[[], tuple[Any, list[Any]]]
CONTRACT_DEFINITION_FIELDS = (
    "symbol",
    "isin",
    "listing_date",
    "final_trade_date",
)


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

    working_dates = get_working_dates(client_factory)
    if not working_dates:
        raise ValueError("DNSE returned no working dates")
    if day == today and day not in working_dates:
        return None
    symbol, expiration = vn30f1m_contract(day, recorded_trading_day(root))
    contract = _contract_definition(
        client_factory=client_factory,
        symbol=symbol,
        expiration=expiration,
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


def _retain_contract(directory: Path, contract: dict[str, str | None]) -> None:
    path = directory / f"{contract['symbol']}.json"
    if path.exists():
        retained = json.loads(path.read_text(encoding="utf-8"))
        changed = any(
            retained.get(field) != contract.get(field)
            for field in CONTRACT_DEFINITION_FIELDS
        )
        if changed:
            raise ValueError(f"DNSE contract metadata changed for {contract['symbol']}")
        return
    directory.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(contract, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _contract_definition(
    *,
    client_factory: ClientFactory,
    symbol: str,
    expiration: date,
) -> dict[str, str | None]:
    """DNSE's definition of ``symbol``; a missing finalTradeDate takes ``expiration``."""
    client, observed = client_factory()
    definition = _decode_response(*client.get_security_definition(symbol, board_id="G1"))[1]
    received_at = datetime.now(UTC)
    _ensure_quota(observed[-1] if observed else None)
    if not isinstance(definition, list) or len(definition) != 1:
        raise ValueError(f"Unexpected DNSE security definition for {symbol}")
    record = definition[0]
    if record.get("marketId") != "DVX" or record.get("boardId") != "G1":
        raise ValueError(f"Unexpected DNSE contract identity for {symbol}: {record}")
    listing_date = record.get("listingDate")
    if not listing_date:
        raise ValueError(f"DNSE security definition missing listingDate for {symbol}")
    final_trade_date = record.get("finalTradeDate") or expiration.isoformat()
    try:
        activation_date = date.fromisoformat(str(listing_date)[:10])
        expiration_date = date.fromisoformat(str(final_trade_date)[:10])
    except ValueError as error:
        raise ValueError(
            f"Invalid DNSE contract dates for {symbol}: "
            f"listingDate={listing_date}, finalTradeDate={final_trade_date}",
        ) from error
    if expiration_date != expiration:
        raise ValueError(f"DNSE finalTradeDate {expiration_date} for {symbol} differs from the expiry rule's {expiration}")
    return {
        "symbol": symbol,
        "isin": str(record["isin"]),
        "listing_date": activation_date.isoformat(),
        "final_trade_date": expiration_date.isoformat(),
        "source_event_at": _source_event_at(record.get("time")),
        "received_at": received_at.isoformat(),
    }


def _source_event_at(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, dict):
        seconds = int(value.get("Seconds", value.get("seconds", 0)))
        nanos = int(value.get("Nanos", value.get("nanos", 0)))
        return datetime.fromtimestamp(seconds + nanos / 1_000_000_000, UTC).isoformat()
    timestamp = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=LOCAL_TIMEZONE)
    return timestamp.astimezone(UTC).isoformat()


def get_working_dates(client_factory: ClientFactory) -> set[date]:
    client, observed = client_factory()
    payload = _decode_response(*client.get_working_dates())[1]
    _ensure_quota(observed[-1] if observed else None)
    if not isinstance(payload, dict):
        raise ValueError("DNSE working-dates response is not a JSON object")
    values = payload.get("workingDates")
    if not isinstance(values, list):
        raise ValueError("DNSE working-dates response does not contain workingDates")
    return {date.fromisoformat(str(value)) for value in values}


def read_working_dates(raw_root: Path) -> set[date]:
    path = raw_root / WORKING_DATES_FILE
    if not path.exists():
        return set()
    return {date.fromisoformat(value) for value in json.loads(path.read_text(encoding="utf-8"))}


def recorded_trading_day(raw_root: Path) -> Callable[[date], bool]:
    """Trading-day check against the working dates recorded under ``raw_root``.

    Raises for a date outside the record, since whether it trades is unknown.
    """
    working_dates = read_working_dates(raw_root)
    if not working_dates:
        raise ValueError(f"No DNSE working dates are recorded under {raw_root}")
    first, last = min(working_dates), max(working_dates)

    def is_trading_day(day: date) -> bool:
        if not first <= day <= last:
            raise ValueError(f"{day} is outside the recorded DNSE working dates {first} to {last}")
        return day in working_dates

    return is_trading_day


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
    """Download one day of pages in parallel time windows; page 1 holds the newest records."""

    def make_fetcher() -> PageFetcher:
        client, observed = client_factory()
        method = getattr(client, method_name)

        def fetch(start: int, end: int, token: str | None) -> tuple[str, Any, str | None]:
            observed.clear()
            raw, payload = _request_with_retries(
                lambda: method(
                    symbol,
                    board_id="G1",
                    from_date=start,
                    to_date=end,
                    limit=PAGE_LIMIT,
                    next_page_token=token,
                ),
            )
            if not isinstance(payload, dict):
                raise ValueError(f"DNSE {response_key} response is not a JSON object")
            if not isinstance(payload.get(response_key), list):
                raise ValueError(f"DNSE response does not contain a {response_key} list")
            _ensure_quota(observed[-1] if observed else None)
            if request_delay_seconds > 0:
                time.sleep(request_delay_seconds)
            next_token = payload.get("nextPageToken")
            return raw, payload, str(next_token) if next_token else None

        return fetch

    def trim(payload: dict[str, Any], start: int, end: int) -> str | None:
        # DNSE record times are local wall-clock strings such as 2026-10-27 10:30:00.000
        low = datetime.fromtimestamp(start, LOCAL_TIMEZONE).replace(tzinfo=None)
        high = datetime.fromtimestamp(end, LOCAL_TIMEZONE).replace(tzinfo=None)
        rows = payload[response_key]
        kept = [row for row in rows if low <= datetime.fromisoformat(str(row["time"])) < high]
        if len(kept) == len(rows):
            return None
        return json.dumps({**payload, response_key: kept}, ensure_ascii=False)

    boundaries = [
        int(datetime.combine(day, boundary, tzinfo=LOCAL_TIMEZONE).timestamp())
        for boundary in PAGE_WINDOW_BOUNDARIES
    ]
    # DNSE returns records newest first, so the latest window takes the first page numbers
    windows = split_range(_timestamp(day), _timestamp(day + timedelta(days=1)), boundaries)[::-1]
    download_windows(
        make_fetcher=make_fetcher,
        trim_page=trim,
        windows=windows,
        destination=destination,
        max_workers=PAGE_WORKERS,
    )


def _request_with_retries(request: Callable[[], tuple[int, Any]]) -> tuple[str, Any]:
    for attempt in range(MAX_SERVER_RETRIES):
        try:
            status, body = request()
        except Exception:
            if attempt == MAX_SERVER_RETRIES - 1:
                raise
            time.sleep(min(30.0, 2.0 ** (attempt + 1)))
            continue
        if status == TOO_MANY_REQUESTS:
            raise RateLimited(f"DNSE rate limit exceeded: {body}")
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
