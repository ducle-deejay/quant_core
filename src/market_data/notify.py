"""Telegram notification transport shared by the data and trading packages.

Single env-var pair drives every alert in the system:

    TELEGRAM_BOT_TOKEN=...
    TELEGRAM_CHAT_ID=...

Failure-safe by contract: alerting must never break the pipeline or the
trading loop, so every public helper swallows transport errors (logged to
stderr) unless ``raise_on_error=True`` is passed explicitly.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from typing import Any

import requests


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

    def send_message(self, text: str) -> dict[str, Any]:
        if not text:
            raise ValueError("Telegram message cannot be empty")

        url = f"{self.config.api_base_url.rstrip('/')}/bot{self.config.bot_token}/sendMessage"
        try:
            response = self._session.post(
                url,
                json={"chat_id": self.config.chat_id, "text": text},
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
