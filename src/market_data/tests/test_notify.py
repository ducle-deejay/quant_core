"""Telegram notifier tests (governing note DEC-009): env parsing + failure safety."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from market_data.notify import TelegramNotifier  # noqa: E402
from market_data.notify import notifier_from_env  # noqa: E402
from market_data.notify import notify_or_log  # noqa: E402


class RaisingNotifier:
    def __init__(self, error: Exception):
        self.error = error

    def send_message(self, text: str):
        raise self.error


def test_notifier_from_env_requires_both(monkeypatch=None):
    import os

    os.environ.pop("TELEGRAM_BOT_TOKEN", None)
    os.environ.pop("TELEGRAM_CHAT_ID", None)
    assert notifier_from_env() is None

    os.environ["TELEGRAM_BOT_TOKEN"] = "tok"
    assert notifier_from_env() is None  # chat id missing

    os.environ["TELEGRAM_CHAT_ID"] = "123"
    notifier = notifier_from_env()
    assert isinstance(notifier, TelegramNotifier)
    assert notifier.config.bot_token == "tok"
    assert notifier.config.chat_id == "123"


def test_notify_or_log_swallows_errors(capsys=None):
    import io
    import contextlib

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


def _run_all() -> int:
    failures = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"PASS {name}")
            except AssertionError as error:
                failures += 1
                print(f"FAIL {name}: {error}")
            except Exception as error:  # noqa: BLE001
                failures += 1
                print(f"FAIL {name}: {type(error).__name__}: {error}")
    return failures


if __name__ == "__main__":
    raise SystemExit(1 if _run_all() else 0)
