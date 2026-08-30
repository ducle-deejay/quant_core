"""Daily ETL orchestrator: DNSE primary, Mirae candlestick fallback, Telegram alerting.

Semantics (fixed vs the nox implementation this replaces):
- DNSE runs first; Mirae runs second and fills ONLY catalog-absent timestamps
  (never averages or overwrites existing bars).
- Coverage is judged AFTER both sources, not after DNSE alone: if Mirae
  resolved every missing DNSE timestamp, the run SUCCEEDS (the nox version
  failed the whole run in that case).
- If both sources failed, or timestamps remain missing after both, the run
  fails loudly and Telegram receives the failure report.
- Alerts: success (with per-source counts), failure, and partial coverage;
  the notifier is failure-safe (market_data.notify).

Config: single JSON file (apps/data/daily/config/pipeline.json) pointing at
the two source configs; credentials via environment (API_KEY/API_SECRET for
DNSE; TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID for alerts).
"""

from __future__ import annotations

import os
import sys
from collections.abc import Callable
from datetime import date
from pathlib import Path
from typing import Any

from market_data.notify import TelegramNotifier
from market_data.notify import notify_or_log
from market_data.sources.dnse.pipeline import retained_contract_symbol
from market_data.sources.dnse.pipeline import run_daily as run_dnse_daily
from market_data.sources.mirae.extract import request_mirae_history
from market_data.sources.mirae.pipeline import run_daily as run_mirae_daily
from market_data.sources.dnse.client import create_dnse_rest_client
from market_data.instrument_provider import instrument_definition_path


SourceRunner = Callable[[date], dict[str, object]]


class DailyDataPipelineError(RuntimeError):
    """Both sources failed, or bars remain missing after the Mirae backfill."""


def run_daily(
    *,
    day: date,
    run_dnse: SourceRunner,
    run_mirae: SourceRunner,
) -> dict[str, object]:
    """Run DNSE first, then Mirae; judge final coverage after both sources.

    Returns the aggregated report. Raises DailyDataPipelineError when DNSE
    failed outright or when timestamps remain missing after both sources.
    """
    dnse_report: dict[str, object] | None = None
    dnse_error: Exception | None = None
    try:
        dnse_report = run_dnse(day)
    except Exception as error:
        dnse_error = error

    mirae_report: dict[str, object] | None = None
    mirae_error: Exception | None = None
    try:
        mirae_report = run_mirae(day)
    except Exception as error:
        mirae_error = error

    if dnse_error is not None:
        raise DailyDataPipelineError(
            f"DNSE daily pipeline failed; Mirae backup {'also failed' if mirae_error is not None else 'attempted'}",
        ) from dnse_error

    remaining = _remaining_missing(dnse_report, mirae_report)
    if remaining:
        raise DailyDataPipelineError(
            f"{len(remaining)} one-minute bars remain missing after both sources",
        )

    report: dict[str, object] = {
        "day": day.isoformat(),
        "dnse": dnse_report,
        "mirae": mirae_report,
    }
    if mirae_error is not None:
        # DNSE fully covered the day; a broken fallback is a warning, not a
        # failed run - surface it in the report/alert instead of failing.
        report["mirae_error"] = str(mirae_error)
    return report


def _remaining_missing(
    dnse_report: dict[str, object] | None,
    mirae_report: dict[str, object] | None,
) -> list[int]:
    """Timestamps DNSE missed that Mirae did not add."""
    missing = _missing_timestamps(dnse_report)
    if not missing:
        return []
    added = _mirae_added_timestamps(mirae_report)
    return [timestamp for timestamp in missing if timestamp not in added]


def _missing_timestamps(report: dict[str, object] | None) -> list[int]:
    if report is None:
        return []
    value = report.get("missing_bar_timestamps", [])
    return [int(timestamp) for timestamp in value] if isinstance(value, list) else []


def _mirae_added_timestamps(report: dict[str, object] | None) -> set[int]:
    if report is None:
        return set()
    records = report.get("records")
    value = records.get("added_bar_timestamps") if isinstance(records, dict) else None
    return {int(timestamp) for timestamp in value} if isinstance(value, list) else set()


# --------------------------------------------------------------------------- #
# Composition helpers (used by apps/data/daily/pipeline.py)
# --------------------------------------------------------------------------- #


def dnse_runner(config: dict[str, Any]) -> SourceRunner:
    """DNSE source runner; reports missing timestamps in its report."""

    def run(day: date) -> dict[str, object]:
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

        return run_dnse_daily(
            client_factory=client_factory,
            raw_root=_resolve_path(config["raw_root"]),
            catalog_path=_resolve_path(config["catalog_path"]),
            instrument_config=instrument_definition_path(str(config["instrument"])),
            continuous_symbol=str(config["instrument"]),
            day=day,
            request_delay_seconds=float(config["request_delay_seconds"]),
        )

    return run


def mirae_runner(mirae_config: dict[str, Any], dnse_config: dict[str, Any]) -> SourceRunner:
    """Mirae fallback runner; reuses the DNSE-retained monthly contract."""

    def run(day: date) -> dict[str, object]:
        return run_mirae_daily(
            request_history=request_mirae_history,
            active_contract=retained_contract_symbol(
                _resolve_path(dnse_config["raw_root"]),
                day,
            ),
            raw_root=_resolve_path(mirae_config["raw_root"]),
            catalog_path=_resolve_path(mirae_config["catalog_path"]),
            instrument_config=instrument_definition_path(str(mirae_config["instrument"])),
            continuous_symbol=str(mirae_config["instrument"]),
            day=day,
        )

    return run


ROOT = Path(__file__).resolve().parents[2]


def _resolve_path(value: object) -> Path:
    path = Path(str(value))
    return path if path.is_absolute() else ROOT / path


def load_json_config(path: Path) -> dict[str, Any]:
    import json

    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Expected a JSON object in {path}")
    return payload


# --------------------------------------------------------------------------- #
# Telegram alert formatting
# --------------------------------------------------------------------------- #


def alert_success(day: date, report: dict[str, object]) -> str:
    dnse = _section("DNSE", report.get("dnse"))
    mirae = _section("Mirae", report.get("mirae"))
    mirae_error = report.get("mirae_error")
    warning = (
        f"\n\n\u26A0\ufe0f Mirae fallback failed (DNSE covered the day): {mirae_error}"
        if mirae_error
        else ""
    )
    return (
        f"[QC-DATA] \U00002705 DATA ETL | {day:%d-%m-%Y}\n\n"
        f"{dnse}\n\n{mirae}{warning}\n\nCatalog updated"
    )


def alert_failure(day: date, error: Exception, report: dict[str, object] | None) -> str:
    dnse = _section("DNSE", report.get("dnse") if report else None, error=error)
    return f"[QC-DATA] \U0000274C DATA ETL | {day:%d-%m-%Y}\n\n{dnse}\n\n{error}"


def _section(source: str, report: object, *, error: Exception | None = None) -> str:
    if error is not None:
        return f"{source} \U0000274C {error}"
    if not isinstance(report, dict):
        return f"{source} - not run"
    records = report.get("records")
    counts = records if isinstance(records, dict) else {}
    if source == "DNSE":
        return (
            f"DNSE \U00002705\n"
            f"Bars       {_count(counts, 'Bar'):>9,}\n"
            f"Trades     {_count(counts, 'TradeTick'):>9,}\n"
            f"Order book {_count(counts, 'OrderBookDepth10'):>9,}"
        )
    return (
        f"Mirae \U00002705\n"
        f"Bars added   {_count(counts, 'Bar'):>7,}\n"
        f"Bars skipped {_count(counts, 'SkippedBar'):>7,}"
    )


def _count(records: dict[str, object], key: str) -> int:
    value = records.get(key, 0)
    return value if isinstance(value, int) else 0


def run_and_alert(
    *,
    day: date,
    run_dnse: SourceRunner,
    run_mirae: SourceRunner,
    notifier: TelegramNotifier | None,
) -> dict[str, object]:
    """Run the daily pipeline and send the corresponding Telegram alert."""
    try:
        report = run_daily(day=day, run_dnse=run_dnse, run_mirae=run_mirae)
    except Exception as error:
        notify_or_log(notifier, alert_failure(day, error, None))
        raise
    notify_or_log(notifier, alert_success(day, report))
    return report
