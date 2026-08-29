from __future__ import annotations

import argparse
import json
import os
from datetime import date
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

from market_data.instrument_provider import instrument_definition_path
from market_data.sources.dnse.client import create_dnse_rest_client
from market_data.sources.dnse.pipeline import run_daily


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
DEFAULT_CONFIG = HERE / "config" / "pipeline.json"
LOCAL_TIMEZONE = ZoneInfo("Asia/Ho_Chi_Minh")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the daily DNSE ETL pipeline")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--date", type=date.fromisoformat)
    args = parser.parse_args()
    config = _load_config(args.config)
    load_dotenv(ROOT / ".env")

    def client_factory() -> tuple[Any, list[Any]]:
        api_key = os.getenv("API_KEY")
        api_secret = os.getenv("API_SECRET")
        if not api_key or not api_secret:
            raise RuntimeError("API_KEY and API_SECRET must be defined in .env")
        observed: list[Any] = []
        client = create_dnse_rest_client(
            api_key=api_key,
            api_secret=api_secret,
            rate_limit_observer=observed.append,
        )
        return client, observed

    report = run_daily(
        client_factory=client_factory,
        raw_root=_resolve_path(config["raw_root"]),
        catalog_path=_resolve_path(config["catalog_path"]),
        instrument_config=instrument_definition_path(str(config["instrument"])),
        continuous_symbol=str(config["instrument"]),
        day=args.date or datetime.now(LOCAL_TIMEZONE).date(),
        request_delay_seconds=float(config["request_delay_seconds"]),
    )
    print(json.dumps(report, indent=2, sort_keys=True))


def _load_config(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    required = {"raw_root", "catalog_path", "instrument", "request_delay_seconds"}
    missing = required - payload.keys()
    if missing:
        raise ValueError(f"Missing DNSE pipeline config fields: {sorted(missing)}")
    return payload


def _resolve_path(value: object) -> Path:
    path = Path(str(value))
    return path if path.is_absolute() else ROOT / path


if __name__ == "__main__":
    main()
