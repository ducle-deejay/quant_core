"""Single live trading runner: composes and blocks in one Nautilus TradingNode.
Usage: .venv/bin/python apps/trading/run.py [--config PATH] [--confirm-live-account]
"""

from __future__ import annotations

import argparse
import signal
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[2]
VN_TZ = ZoneInfo("Asia/Ho_Chi_Minh")
DEFAULT_CONFIG_PATH = ROOT / "apps" / "trading" / "config" / "runtime.json"


def _now_vn_text() -> str:
    """Wall-clock VN time for alert headers."""
    return datetime.now(tz=VN_TZ).strftime("%d-%m-%Y %H:%M:%S")


def _notify(notifier, text: str) -> None:
    """Failure-safe Telegram send (falls back to stderr logging)."""
    if notifier is None:
        print(text, file=sys.stderr)
        return
    from market_data.notify import notify_or_log

    notify_or_log(notifier, text)


def _session_start_text(summary: str) -> str:
    """Session-start alert body (config summary + mode)."""
    from market_data.notify import esc

    return (
        f"\U0001F7E2 QC-TRADING RUN | {_now_vn_text()} | SESSION START\n\n"
        f"<code>{esc(summary)}</code>"
    )


def _session_shutdown_text() -> str:
    """Shutdown alert body (position intentionally stays at the broker)."""
    return (
        f"\U0001F50C QC-TRADING RUN | {_now_vn_text()} | SHUTDOWN\n\n"
        "<code>node stopped · position stays at broker (overnight holding)</code>"
    )


def _calendar_warning_text(detail: str) -> str:
    """DNSE calendar failure warning (fallback heuristic active)."""
    from market_data.notify import esc

    return (
        f"\u26A0\uFE0F QC-TRADING RUN | {_now_vn_text()} | CALENDAR FALLBACK\n\n"
        f"<code>{esc(detail)} · weekday heuristic in use</code>"
    )


def is_vn_working_day_now(notifier) -> tuple[bool, str]:
    """Whether "now" is a VN market working day, with the decision source.

    Uses the DNSE published working dates via ``market_data.dnse_calendar``;
    any fetch failure (missing module, network error, non-200 response)
    falls back to the Mon-Fri weekday heuristic in Asia/Ho_Chi_Minh and
    emits a Telegram warning - the session start never crashes on the
    calendar.

    Returns
    -------
    tuple[bool, str]
        ``(is_working_day, source)`` where ``source`` is ``"dnse"`` or
        ``"weekday-heuristic"``.
    """
    import pandas as pd

    now = datetime.now(tz=VN_TZ)
    try:
        # The landed calendar module names the predicate
        # ``is_valid_vn_trading_day`` (spec sketch: ``is_vn_market_working_day``).
        from market_data.dnse_calendar import (
            is_valid_vn_trading_day,
            load_vn_market_working_dates_from_dnse,
        )

        working_dates = load_vn_market_working_dates_from_dnse()
    except Exception as error:  # noqa: BLE001 - calendar must never crash the start
        detail = f"DNSE working dates unavailable: {type(error).__name__}: {error}"
        _notify(notifier, _calendar_warning_text(detail))
        return now.weekday() < 5, "weekday-heuristic"
    return is_valid_vn_trading_day(pd.Timestamp(now), working_dates=working_dates), "dnse"


def _load_pool_portfolio(runtime_config):
    """Build the live ``PortfolioConfig`` from the research pool + weights.

    Missing pool/weights artifact or corrupt schema aborts with a message
    pointing to the research flow; there is NO silent seed fallback on the
    live path.
    """
    from core.artifacts import AlphaPool, WeightsArtifact
    from trading.portfolio import portfolio_config_from_pool

    try:
        artifact = WeightsArtifact.load()
    except FileNotFoundError as error:
        raise SystemExit(
            f"Missing pool weights artifact (data/pool/weights.json): {error}. "
            "Run the research combine flow to produce it; the live runner "
            "does not fall back to seed expressions."
        ) from error
    try:
        pool = AlphaPool.load()
    except FileNotFoundError as error:
        raise SystemExit(
            f"Missing research pool (data/pool): {error}. Deliver passing "
            "alphas first; the live runner does not fall back to seed "
            "expressions."
        ) from error
    return portfolio_config_from_pool(
        artifact,
        pool,
        runtime_config.instrument,
        limits=runtime_config.limits(),
    )


def _install_sigterm_handler() -> None:
    """Map SIGTERM to KeyboardInterrupt so the node unwinds like on Ctrl-C."""

    def _handler(signum, _frame) -> None:
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, _handler)


def main() -> int:
    """Parse the CLI, compose the node, and block for the session."""
    parser = argparse.ArgumentParser(
        description="QuantCore live trading runner (single Nautilus TradingNode)",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=DEFAULT_CONFIG_PATH,
        help=f"runtime config path (default: {DEFAULT_CONFIG_PATH})",
    )
    parser.add_argument(
        "--confirm-live-account",
        action="store_true",
        help="required when the config selects account=live",
    )
    args = parser.parse_args()

    # Deferred imports: --help must work without the heavy runtime (nautilus,
    # core) being importable, and the imports below are only needed to run.
    from market_data.notify import trading_notifier_from_env
    from trading.config_loader import load_runtime
    from trading.credentials import load_credentials
    from trading.node import build_node

    load_credentials()
    notifier = trading_notifier_from_env()

    config = load_runtime(args.config, confirm_live_account=args.confirm_live_account)

    working_day, source = is_vn_working_day_now(notifier)
    if not working_day:
        print(
            f"Not a VN market working day (source={source}); nothing to do."
        )
        return 0

    portfolio = _load_pool_portfolio(config)

    _notify(notifier, _session_start_text(config.summary()))
    node = build_node(config, portfolio)
    _install_sigterm_handler()
    node.build()
    try:
        node.run()
    except KeyboardInterrupt:
        print("\nStopped by operator")
    finally:
        node.dispose()
        _notify(notifier, _session_shutdown_text())
    return 0


if __name__ == "__main__":
    sys.exit(main())
