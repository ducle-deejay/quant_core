from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path
from typing import Any

import pandas as pd
from dotenv import load_dotenv

from trading.adapters.dnse.client import create_dnse_rest_client
from trading.adapters.dnse.config import DNSE_API_VERSION
from trading.adapters.dnse.config import VN_TZ


@lru_cache(maxsize=1)
def load_vn_market_working_dates_from_dnse() -> tuple[str, ...]:
    """Return the working dates published by the DNSE OpenAPI."""
    load_dotenv(Path(__file__).resolve().parents[4] / ".env")
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
    """Parse the DNSE working-date response payload."""
    if isinstance(body, str):
        body = json.loads(body)
    if not isinstance(body, dict) or not isinstance(body.get("workingDates"), list):
        raise ValueError(f"Unexpected DNSE working dates payload: {body}")
    return tuple(str(value) for value in body["workingDates"])


def is_valid_vn_trading_day(
    timestamp_utc: pd.Timestamp,
    timezone_name: str = VN_TZ,
    working_dates: tuple[str, ...] | None = None,
) -> bool:
    """Return whether the timestamp belongs to an accepted VN trading date."""
    local_timestamp = timestamp_utc.tz_convert(timezone_name)
    if working_dates:
        return local_timestamp.date().isoformat() in set(working_dates)
    return local_timestamp.weekday() < 5


def _required_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise ValueError(f"Missing required environment variable: {name}")
    return value
