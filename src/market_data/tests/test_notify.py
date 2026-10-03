"""Test Discord webhook configuration, payload, delivery failures, and error fencing."""

from __future__ import annotations

import contextlib
import io

import pytest

from market_data.notify import FIELD_VALUE_LIMIT
from market_data.notify import RED
from market_data.notify import Alert
from market_data.notify import DiscordWebhook
from market_data.notify import code_block
from market_data.notify import data_notifier_from_env
from market_data.notify import notify_or_log


class FakeResponse:
    def __init__(self, status_code: int):
        self.status_code = status_code
        self.text = "" if status_code < 300 else "rate limited"


class FakeSession:
    def __init__(self, status_code: int = 204):
        self.status_code = status_code
        self.calls: list[tuple[str, dict]] = []

    def post(self, url, *, json=None, timeout=None):
        self.calls.append((url, json or {}))
        return FakeResponse(self.status_code)


class RaisingNotifier:
    def send(self, alert: Alert):
        raise RuntimeError("boom")


ALERT = Alert(summary="❌ Data 2026-10-05 failed — retry at 17:00", color=RED, fields=(("Step: DNSE extract", "x", False),))


def test_data_notifier_needs_the_webhook_url(monkeypatch):
    monkeypatch.delenv("DATA_DISCORD_WEBHOOK_URL", raising=False)
    assert data_notifier_from_env() is None
    monkeypatch.setenv("DATA_DISCORD_WEBHOOK_URL", "https://discord.com/api/webhooks/1/token")
    assert isinstance(data_notifier_from_env(), DiscordWebhook)


def test_send_posts_the_summary_and_one_colored_embed():
    session = FakeSession()
    DiscordWebhook("https://hook", session=session).send(ALERT)
    [(url, payload)] = session.calls
    assert url == "https://hook"
    assert payload["username"] == "Data Pipeline"
    assert payload["content"] == ALERT.summary
    assert payload["embeds"] == [
        {"color": RED, "fields": [{"name": "Step: DNSE extract", "value": "x", "inline": False}]},
    ]


def test_send_raises_when_discord_rejects_the_message():
    with pytest.raises(RuntimeError, match="HTTP 429"):
        DiscordWebhook("https://hook", session=FakeSession(429)).send(ALERT)


def test_notify_or_log_swallows_errors():
    buffer = io.StringIO()
    with contextlib.redirect_stderr(buffer):
        notify_or_log(RaisingNotifier(), ALERT)
    assert "Alert delivery failed" in buffer.getvalue()


def test_notify_or_log_raises_when_requested():
    with pytest.raises(RuntimeError):
        notify_or_log(RaisingNotifier(), ALERT, raise_on_error=True)


def test_notify_or_log_none_is_noop():
    notify_or_log(None, ALERT)


def test_code_block_keeps_the_end_of_a_long_error():
    fenced = code_block("x" * 5000 + "ValueError: the real cause")
    assert len(fenced) <= FIELD_VALUE_LIMIT
    assert fenced.endswith("ValueError: the real cause\n```")
