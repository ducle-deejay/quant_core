"""Telegram notification transport shared by the data and trading packages.

Two env-var pairs drive the two alert channels (DEC-011):

    DATA_TELEGRAM_BOT_TOKEN / DATA_TELEGRAM_CHAT_ID      (data ingest)
    TRADING_TELEGRAM_BOT_TOKEN / TRADING_TELEGRAM_CHAT_ID (live trading)

Messages use Telegram ``parse_mode=HTML`` (DEC-012): formatters build the
markup, dynamic values must be escaped with :func:`esc`.

Failure-safe by contract: alerting must never break the pipeline or the
trading loop, so every public helper swallows transport errors (logged to
stderr) unless ``raise_on_error=True`` is passed explicitly. The daily ETL
entrypoint opts out (DEC-012): an undeliverable alert fails the run loudly.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from html import escape
from typing import Any

import requests


def esc(value: object) -> str:
    """HTML-escape dynamic text embedded in alert messages (parse_mode=HTML)."""
    return escape(str(value))


@dataclass(frozen=True)
class TelegramConfig:
    """External Telegram transport configuration."""

    bot_token: str
    chat_id: str | int
    timeout_seconds: float = 15.0
    api_base_url: str = "https://api.telegram.org"


class TelegramNotificationError(RuntimeError):
    """External Telegram transport failure."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        payload: Any = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.payload = payload


class TelegramNotifier:
    """Send one text message per call; callers own retry policy."""

    def __init__(
        self,
        config: TelegramConfig,
        *,
        session: requests.Session | None = None,
    ) -> None:
        self.config = config
        self._session = session or requests.Session()

    def send_message(self, text: str, *, parse_mode: str = "HTML") -> dict[str, Any]:
        if not text:
            raise ValueError("Telegram message cannot be empty")

        url = f"{self.config.api_base_url.rstrip('/')}/bot{self.config.bot_token}/sendMessage"
        payload: dict[str, Any] = {"chat_id": self.config.chat_id, "text": text}
        if parse_mode:
            payload["parse_mode"] = parse_mode
        try:
            response = self._session.post(
                url,
                json=payload,
                timeout=self.config.timeout_seconds,
            )
        except requests.RequestException as exc:
            raise TelegramNotificationError(f"Telegram request failed: {exc}") from exc

        try:
            payload = response.json() if response.content else {}
        except ValueError as exc:
            raise TelegramNotificationError(
                "Telegram returned a non-JSON response",
                status_code=response.status_code,
                payload=response.text,
            ) from exc

        if not 200 <= response.status_code < 300:
            raise TelegramNotificationError(
                f"Telegram returned HTTP {response.status_code}",
                status_code=response.status_code,
                payload=payload,
            )
        if not isinstance(payload, dict) or payload.get("ok") is not True:
            raise TelegramNotificationError(
                "Telegram rejected the message",
                status_code=response.status_code,
                payload=payload,
            )
        return payload


def notifier_from_env(
    *,
    bot_token_env: str = "TELEGRAM_BOT_TOKEN",
    chat_id_env: str = "TELEGRAM_CHAT_ID",
) -> TelegramNotifier | None:
    """Build a notifier from the environment, or None when unconfigured."""
    bot_token = os.getenv(bot_token_env, "").strip()
    chat_id = os.getenv(chat_id_env, "").strip()
    if not bot_token and not chat_id:
        return None
    if not bot_token or not chat_id:
        print(
            f"Telegram skipped: {bot_token_env} and {chat_id_env} must be set together",
            file=sys.stderr,
        )
        return None
    return TelegramNotifier(
        TelegramConfig(bot_token=bot_token, chat_id=chat_id),
    )


def data_notifier_from_env() -> TelegramNotifier | None:
    """Alerts for data ingest: DATA_TELEGRAM_BOT_TOKEN / DATA_TELEGRAM_CHAT_ID."""
    return notifier_from_env(
        bot_token_env="DATA_TELEGRAM_BOT_TOKEN",
        chat_id_env="DATA_TELEGRAM_CHAT_ID",
    )


def trading_notifier_from_env() -> TelegramNotifier | None:
    """Alerts for live trading: TRADING_TELEGRAM_BOT_TOKEN / TRADING_TELEGRAM_CHAT_ID."""
    return notifier_from_env(
        bot_token_env="TRADING_TELEGRAM_BOT_TOKEN",
        chat_id_env="TRADING_TELEGRAM_CHAT_ID",
    )


def notify_or_log(
    notifier: TelegramNotifier | None,
    text: str,
    *,
    raise_on_error: bool = False,
) -> None:
    """Send through ``notifier``; never break the caller when it fails."""
    if notifier is None:
        return
    try:
        notifier.send_message(text)
    except Exception as error:  # noqa: BLE001 - alerting is best-effort
        if raise_on_error:
            raise
        print(f"Telegram notification failed: {error}", file=sys.stderr)
