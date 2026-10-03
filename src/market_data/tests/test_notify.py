"""Test Telegram notifier environment parsing, HTML transport, and failures.

Covers optional configuration, HTML escaping, no-op behavior, logged errors,
and opt-in error propagation.
"""

from __future__ import annotations

import contextlib
import io

from market_data.notify import TelegramConfig
from market_data.notify import TelegramNotifier
from market_data.notify import esc
from market_data.notify import notifier_from_env
from market_data.notify import notify_or_log


class FakeResponse:
    status_code = 200
    content = b"{}"

    def __init__(self, payload: dict):
        self._payload = payload

    def json(self):
        return self._payload


class FakeSession:
    def __init__(self):
        self.calls: list[tuple[str, dict]] = []

    def post(self, url, *, json=None, timeout=None):
        self.calls.append((url, json or {}))
        return FakeResponse({"ok": True})


class RaisingNotifier:
    def __init__(self, error: Exception):
        self.error = error

    def send_message(self, text: str):
        raise self.error


def test_notifier_from_env_requires_both(monkeypatch):
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
    assert notifier_from_env() is None

    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "tok")
    assert notifier_from_env() is None  # chat id missing

    monkeypatch.setenv("TELEGRAM_CHAT_ID", "123")
    notifier = notifier_from_env()
    assert isinstance(notifier, TelegramNotifier)
    assert notifier.config.bot_token == "tok"
    assert notifier.config.chat_id == "123"


def test_notify_or_log_swallows_errors():
    buffer = io.StringIO()
    with contextlib.redirect_stderr(buffer):
        notify_or_log(RaisingNotifier(RuntimeError("boom")), "hello")
    assert "Telegram notification failed" in buffer.getvalue()


def test_notify_or_log_raises_when_requested():
    try:
        notify_or_log(RaisingNotifier(RuntimeError("boom")), "hello", raise_on_error=True)
    except RuntimeError:
        pass
    else:
        raise AssertionError("expected RuntimeError")


def test_notify_or_log_none_is_noop():
    notify_or_log(None, "hello")  # must not raise


def test_send_message_uses_html_parse_mode():
    # The default parse_mode is HTML so <pre> blocks in alert text are interpreted as markup.
    session = FakeSession()
    notifier = TelegramNotifier(TelegramConfig(bot_token="tok", chat_id="123"), session=session)
    notifier.send_message("<pre>DNSE  ✅ bars 241</pre>")
    _, payload = session.calls[0]
    assert payload["parse_mode"] == "HTML"
    assert payload["text"] == "<pre>DNSE  ✅ bars 241</pre>"


def test_esc_html_escapes_dynamic_values():
    assert esc("<a&b>") == "&lt;a&amp;b&gt;"
    assert esc("plain") == "plain"
