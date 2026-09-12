"""VN market working dates from the DNSE OpenAPI.

Ported from the nox_system DNSE adapter and adapted to the existing REST
client in ``market_data.sources.dnse`` (same endpoint and payload
contract). Credentials come from the repo-root ``.env`` (``API_KEY`` /
``API_SECRET``); TLS certificate verification is enforced by the client
factory.
"""

from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd
from dotenv import load_dotenv

from market_data.sources.dnse.client import DNSE_API_VERSION
from market_data.sources.dnse.client import create_dnse_rest_client

#: Vietnam local timezone (exchange session zone).
VN_TZ = ZoneInfo("Asia/Ho_Chi_Minh")

__all__ = [
    "VN_TZ",
    "is_valid_vn_trading_day",
    "load_vn_market_working_dates_from_dnse",
    "parse_working_dates_body",
]


@lru_cache(maxsize=1)
def load_vn_market_working_dates_from_dnse() -> tuple[str, ...]:
    """Return the working dates published by the DNSE OpenAPI.

    Loads the repo-root ``.env``, creates the verified DNSE REST client and
    calls the working-dates endpoint once per process (LRU-cached).

    Returns
    -------
    tuple[str, ...]
        ISO date strings of every market working date.

    Raises
    ------
    ValueError
        If ``API_KEY``/``API_SECRET`` are missing or the endpoint returns a
        non-200 status.
    """
    load_dotenv(Path(__file__).resolve().parents[2] / ".env")
    client = create_dnse_rest_client(
        api_key=_required_env("API_KEY"),
        api_secret=_required_env("API_SECRET"),
        base_url="https://openapi.dnse.com.vn",
        api_version=DNSE_API_VERSION,
    )
    status, body = client.get_working_dates(dry_run=False)
    if status != 200:
        raise ValueError(f"DNSE get_working_dates failed with status={status}, body={body}")
    return parse_working_dates_body(body)


def parse_working_dates_body(body: Any) -> tuple[str, ...]:
    """Parse the DNSE working-date response payload.

    Parameters
    ----------
    body : Any
        Raw response body; a JSON string or an already-decoded dict with a
        ``workingDates`` list.

    Returns
    -------
    tuple[str, ...]
        ISO date strings of every market working date.

    Raises
    ------
    ValueError
        If the payload does not have the expected shape.
    """
    if isinstance(body, str):
        body = json.loads(body)
    if not isinstance(body, dict) or not isinstance(body.get("workingDates"), list):
        raise ValueError(f"Unexpected DNSE working dates payload: {body}")
    return tuple(str(value) for value in body["workingDates"])


def is_valid_vn_trading_day(
    timestamp_utc: pd.Timestamp,
    timezone_name: str | ZoneInfo = VN_TZ,
    working_dates: tuple[str, ...] | None = None,
) -> bool:
    """Return whether the timestamp belongs to an accepted VN trading date.

    Parameters
    ----------
    timestamp_utc : pandas.Timestamp
        Timestamp to test (UTC).
    timezone_name : str | zoneinfo.ZoneInfo
        Session zone used to resolve the local date.
    working_dates : tuple[str, ...] | None
        Accepted ISO dates; when empty/None, falls back to the
        Monday-Friday weekday check.

    Returns
    -------
    bool
        True when the local date is a trading date.
    """
    local_timestamp = timestamp_utc.tz_convert(timezone_name)
    if working_dates:
        return local_timestamp.date().isoformat() in set(working_dates)
    return local_timestamp.weekday() < 5


def _required_env(name: str) -> str:
    """Return the required environment variable or raise ValueError."""
    value = os.getenv(name)
    if not value:
        raise ValueError(f"Missing required environment variable: {name}")
    return value
