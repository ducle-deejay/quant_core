"""Trading alert helpers over the shared Telegram transport.

Re-exports the single notifier implementation from ``market_data.notify``
and provides message formatters for the live loop: session lifecycle, order
outcomes, force-close, and risk state transitions.

Format follows the unified template (DEC-012):
    <icon> QC-<DOMAIN> <EVENT> | <date> <time VN> | <verdict>
    <pre>aligned body</pre>
Dynamic values are HTML-escaped (the transport sends parse_mode=HTML).
"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from market_data.notify import TelegramNotifier  # noqa: F401  (re-export)
from market_data.notify import TelegramConfig  # noqa: F401  (re-export)
from market_data.notify import esc  # noqa: F401  (re-export)
from market_data.notify import notifier_from_env  # noqa: F401  (re-export)
from market_data.notify import notify_or_log  # noqa: F401  (re-export)

VN_TZ = ZoneInfo("Asia/Ho_Chi_Minh")


def _now_vn() -> str:
    return datetime.now(VN_TZ).strftime("%d-%m-%Y %H:%M:%S")


def format_session(message: str) -> str:
    return f"\U0001F4C8 QC-TRADING PAPER | {_now_vn()} | {esc(message)}"


def format_order_outcome(kind: str, *, client_order_id: str, reason: str | None = None) -> str:
    body = f"coid {esc(client_order_id)}"
    if reason:
        body += f" · reason {esc(reason)}"
    return (
        f"\u26A0\uFE0F QC-TRADING PAPER | {_now_vn()} | ORDER {esc(kind)}\n\n"
        f"<code>{body}</code>"
    )


def format_force_close(position: int, *, time: str) -> str:
    return (
        f"\U0001F6D1 QC-TRADING PAPER | {_now_vn()} | FORCE CLOSE\n\n"
        f"<code>position {position} \u2192 flat · cut {esc(time)}</code>"
    )


def format_risk_state(previous: str, current: str, reason: str) -> str:
    return (
        f"\U0001F6A8 QC-TRADING PAPER | {_now_vn()} | RISK STATE\n\n"
        f"<code>{esc(previous)} \u2192 {esc(current)} · {esc(reason)}</code>"
    )


def format_flatten_failed(instrument: str, attempts: int) -> str:
    return (
        f"\U0001F534 QC-TRADING PAPER | {_now_vn()} | FLATTEN FAILED\n\n"
        f"<code>{esc(instrument)} · attempts {attempts} · manual intervention required</code>"
    )
