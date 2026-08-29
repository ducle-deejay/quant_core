from __future__ import annotations

import argparse
import json
from datetime import date
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from market_data.sources.dnse.pipeline import retained_contract_symbol
from market_data.sources.mirae.extract import request_mirae_history
from market_data.sources.mirae.pipeline import run_daily
from market_data.instrument_provider import instrument_definition_path


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
DEFAULT_CONFIG = HERE / "config" / "pipeline.json"
LOCAL_TIMEZONE = ZoneInfo("Asia/Ho_Chi_Minh")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the Mirae candlestick backup pipeline")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--date", type=date.fromisoformat)
    args = parser.parse_args()
    config = _load_config(args.config)
    day = args.date or _current_local_day()
    report = run_daily(
        request_history=request_mirae_history,
        active_contract=retained_contract_symbol(
            _resolve_path(config["dnse_raw_root"]),
            day,
        ),
        raw_root=_resolve_path(config["raw_root"]),
        catalog_path=_resolve_path(config["catalog_path"]),
        instrument_config=instrument_definition_path(str(config["instrument"])),
        continuous_symbol=str(config["instrument"]),
        day=day,
    )
    print(json.dumps(report, indent=2, sort_keys=True))


def _load_config(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    required = {"raw_root", "dnse_raw_root", "catalog_path", "instrument"}
    missing = required - payload.keys()
    if missing:
        raise ValueError(f"Missing Mirae pipeline config fields: {sorted(missing)}")
    return payload


def _resolve_path(value: object) -> Path:
    path = Path(str(value))
    return path if path.is_absolute() else ROOT / path


def _current_local_day() -> date:
    return datetime.now(LOCAL_TIMEZONE).date()


if __name__ == "__main__":
    main()
