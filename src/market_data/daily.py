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
from market_data.notify import esc
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
# Telegram alert formatting (unified template, DEC-012)
#
# Header : <icon> QC-<DOMAIN> <EVENT> | <date> [<time>] | <verdict>
# Body   : monospace <pre> block, source-grouped, thousands separators
# Footer : only when actionable
# --------------------------------------------------------------------------- #


def alert_success(day: date, report: dict[str, object]) -> str:
    """[QC-DATA] success alert: per-source bullet counts, verdict OK."""
    dnse = report.get("dnse")
    mirae = report.get("mirae")
    dnse_counts = _records(dnse)
    mirae_counts = _records(mirae)
    dnse_block = (
        "DNSE \u2705\n"
        f"\u2022 bars: {_count(dnse_counts, 'Bar'):,}\n"
        f"\u2022 trades: {_count(dnse_counts, 'TradeTick'):,}\n"
        f"\u2022 book: {_count(dnse_counts, 'OrderBookDepth10'):,}"
    )
    mirae_error = report.get("mirae_error")
    if mirae_error:
        verdict = "OK (mirae down)"
        mirae_block = f"Mirae \u274C\n\u2022 {esc(mirae_error)}"
    else:
        verdict = "OK"
        mirae_block = (
            "Mirae \u2705\n"
            f"\u2022 added: {_count(mirae_counts, 'Bar'):,}\n"
            f"\u2022 skipped: {_count(mirae_counts, 'SkippedBar'):,}"
        )
    return (
        f"\u2705 QC-DATA ETL | {day:%d-%m-%Y} | {verdict}\n\n"
        f"{dnse_block}\n{mirae_block}\n\n"
        "gaps 0 · catalog updated"
    )


def alert_failure(day: date, error: Exception, report: dict[str, object] | None) -> str:
    """[QC-DATA] run-failure alert: the error, catalog untouched."""
    return (
        f"\u274C QC-DATA ETL | {day:%d-%m-%Y} | FAILED\n\n"
        f"<code>{esc(error)}</code>\n\n"
        "catalog NOT updated"
    )


def alert_bootstrap_failure(day: date, error: Exception) -> str:
    """[QC-DATA] startup alert (DEC-012): any failure before the run starts."""
    return (
        f"\u274C QC-DATA ETL | {day:%d-%m-%Y} | STARTUP FAILED\n\n"
        f"<code>{esc(error)}</code>\n\n"
        "check data/logs/daily-etl.err.log"
    )


def format_run_missing(day: date) -> str:
    """[QC-DATA] heartbeat alert (DEC-012): the scheduled run never happened."""
    return (
        f"\U0001F6A8 QC-DATA ETL | {day:%d-%m-%Y} | RUN MISSING\n\n"
        "expected 16:00 run not detected\n\n"
        "check: launchctl list · data/logs/daily-etl.err.log"
    )


def _records(report: object) -> dict[str, object]:
    if not isinstance(report, dict):
        return {}
    records = report.get("records")
    return records if isinstance(records, dict) else {}


def _count(records: dict[str, object], key: str) -> int:
    value = records.get(key, 0)
    return value if isinstance(value, int) else 0


def run_and_alert(
    *,
    day: date,
    run_dnse: SourceRunner,
    run_mirae: SourceRunner,
    notifier: TelegramNotifier | None,
    raise_on_error: bool = False,
) -> dict[str, object]:
    """Run the daily pipeline and send the corresponding Telegram alert.

    ``raise_on_error`` opts out of the failure-safe contract (DEC-012): the
    ETL entrypoint passes True so an undeliverable alert fails the run loudly.
    """
    try:
        report = run_daily(day=day, run_dnse=run_dnse, run_mirae=run_mirae)
    except Exception as error:
        notify_or_log(notifier, alert_failure(day, error, None), raise_on_error=raise_on_error)
        raise
    notify_or_log(notifier, alert_success(day, report), raise_on_error=raise_on_error)
    return report
