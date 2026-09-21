"""Test writing the daily ETL status file and classifying run states.

Covers successful, failed, running, missing, stale-running, and mismatched
day records.
"""

from __future__ import annotations

import sys
import tempfile
from datetime import UTC
from datetime import date
from datetime import datetime
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from market_data.heartbeat import check_status  # noqa: E402
from market_data.heartbeat import write_status  # noqa: E402


DAY = date(2026, 8, 30)


def test_heartbeat_ok_after_success():
    with tempfile.TemporaryDirectory() as tmp:
        write_status(DAY, result="ok", root=Path(tmp))
        status, detail = check_status(day=DAY, root=Path(tmp))
        assert status == "ok"
        assert detail == "ok"


def test_heartbeat_failed_keeps_watcher_quiet():
    with tempfile.TemporaryDirectory() as tmp:
        write_status(DAY, result="failed: DNSE down", root=Path(tmp))
        status, detail = check_status(day=DAY, root=Path(tmp))
        assert status == "failed"
        assert "DNSE down" in detail


def test_heartbeat_missing_without_status_file():
    with tempfile.TemporaryDirectory() as tmp:
        status, detail = check_status(day=DAY, root=Path(tmp))
        assert status == "missing"
        assert "no status file" in detail


def test_heartbeat_missing_for_other_day():
    with tempfile.TemporaryDirectory() as tmp:
        write_status(DAY, result="ok", root=Path(tmp))
        status, _ = check_status(day=date(2026, 8, 31), root=Path(tmp))
        assert status == "missing"


def test_heartbeat_running_not_yet_stale():
    with tempfile.TemporaryDirectory() as tmp:
        write_status(DAY, result="running", root=Path(tmp))
        status, _ = check_status(day=DAY, root=Path(tmp), now=datetime.now(UTC))
        assert status == "running"


def test_heartbeat_stale_running_is_missing():
    with tempfile.TemporaryDirectory() as tmp:
        write_status(DAY, result="running", root=Path(tmp))
        stale = datetime.now(UTC) + timedelta(hours=4)
        status, detail = check_status(day=DAY, root=Path(tmp), now=stale)
        assert status == "missing"
        assert "stale" in detail


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
