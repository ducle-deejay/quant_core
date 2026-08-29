"""Trading alert helpers over the shared Telegram transport.

Re-exports the single notifier implementation from ``market_data.notify``
(one bot token/chat id pair drives data and trading alerts) and provides
message formatters for the live loop: session lifecycle, order outcomes,
force-close, and risk state transitions.
"""

from __future__ import annotations

from market_data.notify import TelegramNotifier  # noqa: F401  (re-export)
from market_data.notify import TelegramConfig  # noqa: F401  (re-export)
from market_data.notify import notifier_from_env  # noqa: F401  (re-export)
from market_data.notify import notify_or_log  # noqa: F401  (re-export)


def format_session(message: str) -> str:
    return f"\U0001F4C8 TRADING | {message}"


def format_order_outcome(kind: str, *, client_order_id: str, reason: str | None = None) -> str:
    suffix = f" reason={reason}" if reason else ""
    return (
        f"\U000026A0 TRADING | ORDER {kind}\n"
        f"Order: {client_order_id}{suffix}"
    )


def format_force_close(position: int, *, time: str) -> str:
    return (
        f"\U0001F6D1 TRADING | FORCE CLOSE {time}\n"
        f"Position: {position} contracts -> flat"
    )


def format_risk_state(previous: str, current: str, reason: str) -> str:
    return (
        f"\U0001F6A8 TRADING | RISK STATE {previous} -> {current}\n"
        f"Reason: {reason}"
    )


def format_flatten_failed(instrument: str, attempts: int) -> str:
    return (
        f"\U0001F534 TRADING | FLATTEN FAILED after {attempts} attempts\n"
        f"Instrument: {instrument} - manual intervention required"
    )
