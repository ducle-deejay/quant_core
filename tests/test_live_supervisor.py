"""Behaviour of the live supervisor, driven with small real child processes."""

from __future__ import annotations

import sys
import threading
import time as monotonic_time
from datetime import datetime
from datetime import timedelta
from pathlib import Path

from nautilus_bridge.live.supervisor import TIMEZONE
from nautilus_bridge.live.supervisor import Supervisor

PY = sys.executable
# Exits 1 on its first run and 0 afterwards; the run count is kept in the file argv[1].
CRASH_ONCE = (
    "import sys, pathlib; p = pathlib.Path(sys.argv[1]); "
    "n = int(p.read_text()) if p.exists() else 0; p.write_text(str(n + 1)); "
    "sys.exit(1 if n == 0 else 0)"
)
ALWAYS_CRASH = (
    "import sys, pathlib; p = pathlib.Path(sys.argv[1]); "
    "p.write_text(str((int(p.read_text()) if p.exists() else 0) + 1)); sys.exit(1)"
)
STOPS_ON_SIGTERM = (
    "import signal, sys, time; signal.signal(signal.SIGTERM, lambda *a: sys.exit(0)); time.sleep(60)"
)
IGNORES_SIGTERM = "import signal, time; signal.signal(signal.SIGTERM, signal.SIG_IGN); time.sleep(60)"


def _stop_in(seconds: float):
    return (datetime.now(TIMEZONE) + timedelta(seconds=seconds)).time()


def _runs(path: Path) -> int:
    return int(path.read_text()) if path.exists() else 0


def test_crashed_node_is_restarted_and_a_clean_exit_ends_the_day(tmp_path: Path) -> None:
    runs = tmp_path / "runs"
    supervisor = Supervisor(
        (PY, "-c", CRASH_ONCE, str(runs)),
        stop_at=_stop_in(60),
        restart_delays_seconds=(0.0,),
    )

    assert supervisor.run() == 0
    assert _runs(runs) == 2


def test_supervisor_gives_up_after_the_restart_limit(tmp_path: Path) -> None:
    runs = tmp_path / "runs"
    supervisor = Supervisor(
        (PY, "-c", ALWAYS_CRASH, str(runs)),
        stop_at=_stop_in(60),
        max_restarts=2,
        restart_delays_seconds=(0.0,),
    )

    assert supervisor.run() == 1
    assert _runs(runs) == 3  # the first run plus two restarts


def test_node_gets_sigterm_at_the_stop_time() -> None:
    supervisor = Supervisor((PY, "-c", STOPS_ON_SIGTERM), stop_at=_stop_in(1.5))
    started = monotonic_time.monotonic()

    assert supervisor.run() == 0
    assert monotonic_time.monotonic() - started < 10


def test_node_that_ignores_sigterm_is_killed_after_the_grace_period() -> None:
    supervisor = Supervisor(
        (PY, "-c", IGNORES_SIGTERM),
        stop_at=_stop_in(1.0),
        stop_grace_seconds=0.5,
    )
    started = monotonic_time.monotonic()

    assert supervisor.run() == 0
    assert monotonic_time.monotonic() - started < 10


def test_supervisor_started_after_the_stop_time_starts_nothing(tmp_path: Path) -> None:
    runs = tmp_path / "runs"
    supervisor = Supervisor((PY, "-c", CRASH_ONCE, str(runs)), stop_at=_stop_in(-60))

    assert supervisor.run() == 0
    assert _runs(runs) == 0


def test_stop_request_stops_the_node_without_restarting_it(tmp_path: Path) -> None:
    supervisor = Supervisor((PY, "-c", STOPS_ON_SIGTERM), stop_at=_stop_in(60))
    threading.Timer(0.5, supervisor.request_stop).start()
    started = monotonic_time.monotonic()

    assert supervisor.run() == 0
    assert monotonic_time.monotonic() - started < 10
