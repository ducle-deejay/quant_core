"""Send alerts to a Discord channel through an incoming webhook, and write each alert to the log first."""

from __future__ import annotations

import logging
from dataclasses import dataclass

import requests


GREEN = 0x2ECC71
YELLOW = 0xF1C40F
RED = 0xE74C3C
FIELD_VALUE_LIMIT = 1024  # Discord docs, docs.discord.com/developers/resources/message, "Embed Limits"
LOG_LEVELS = {GREEN: logging.INFO, YELLOW: logging.WARNING, RED: logging.ERROR}
logger = logging.getLogger("Pipeline")


@dataclass(frozen=True)
class Alert:
    summary: str  # sent as the message text above the embed
    color: int
    fields: tuple[tuple[str, str, bool], ...] = ()  # (name, value, inline)


def code_block(text: object, limit: int = FIELD_VALUE_LIMIT) -> str:
    """Fence ``text`` for an embed field, keeping its end when it is too long."""
    body = str(text).replace("```", "'''")
    room = limit - len("```\n\n```")
    if len(body) > room:
        body = "…" + body[-(room - 1):]
    return f"```\n{body}\n```"


class DiscordWebhook:
    def __init__(
        self,
        url: str,
        *,
        username: str = "Data Pipeline",
        session: requests.Session | None = None,
        timeout_seconds: float = 15.0,
    ) -> None:
        self._url = url
        self._username = username
        self._session = session or requests.Session()
        self._timeout_seconds = timeout_seconds

    def send(self, alert: Alert) -> None:
        payload = {
            "username": self._username,
            "content": alert.summary,
            "embeds": [
                {
                    "color": alert.color,
                    "fields": [
                        {"name": name, "value": value, "inline": inline}
                        for name, value, inline in alert.fields
                    ],
                },
            ],
        }
        response = self._session.post(self._url, json=payload, timeout=self._timeout_seconds)
        if not 200 <= response.status_code < 300:
            raise RuntimeError(f"Discord returned HTTP {response.status_code}: {response.text[:200]}")


def notify_or_log(
    notifier: DiscordWebhook | None,
    alert: Alert,
    *,
    raise_on_error: bool = False,
) -> None:
    """Log the alert before sending it, so the log holds every alert even when Discord delivery fails."""
    logger.log(LOG_LEVELS.get(alert.color, logging.INFO), "alert %s", alert_text(alert))
    if notifier is None:
        logger.info("alert not sent: no Discord webhook configured")
        return
    try:
        notifier.send(alert)
    except Exception as error:  # noqa: BLE001 - alerting is best-effort
        logger.error("alert delivery failed error=%s: %s", type(error).__name__, error)
        if raise_on_error:
            raise


def alert_text(alert: Alert) -> str:
    """The alert on one line: summary, then each non-blank field as name=value."""
    parts = [f'summary="{alert.summary}"']
    for name, value, _ in alert.fields:
        if name.strip("\u200b"):
            text = " ".join(value.replace("```", "").replace("`", "").split())
            parts.append(f'"{name}"="{text}"')
    return " ".join(parts)
