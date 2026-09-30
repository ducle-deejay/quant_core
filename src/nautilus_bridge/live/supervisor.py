"""Keep the live node running for one trading day and stop it at the end of the session.

NautilusTrader leaves restart after a failed process to an external supervisor
(docs/concepts/architecture.md, "Crash-only design"); this is that supervisor. It runs
``nautilus_bridge.live.live`` in a child process and reads its exit code (see runner.py):

- 0: the node stopped on request, so it is not restarted
- anything else, including an abort: the node is restarted after a growing delay, at most
  ``MAX_RESTARTS`` times per run

At ``STOP_AT`` (Vietnam local time) it sends SIGTERM to the node, waits ``STOP_GRACE_SECONDS``
for the node's own shutdown, then kills it. SIGINT or SIGTERM sent to the supervisor stops the
node the same way.
"""

from __future__ import annotations

import logging
import signal
import subprocess
import sys
import threading
from collections.abc import Callable
from datetime import datetime
from datetime import time
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[3]
LOG_FILE = ROOT / "data" / "logs" / "live" / "supervisor.log"

TIMEZONE = ZoneInfo("Asia/Ho_Chi_Minh")
STOP_AT = time(15, 0)
STOP_GRACE_SECONDS = 120.0
MAX_RESTARTS = 5
RESTART_DELAYS_SECONDS = (10.0, 30.0, 60.0, 120.0, 300.0)
NODE_COMMAND = (sys.executable, "-m", "nautilus_bridge.live.live")

log = logging.getLogger("supervisor")


class Supervisor:
    def __init__(
        self,
        command: tuple[str, ...] = NODE_COMMAND,
        *,
        stop_at: time = STOP_AT,
        now: Callable[[], datetime] = lambda: datetime.now(TIMEZONE),
        stop_grace_seconds: float = STOP_GRACE_SECONDS,
        max_restarts: int = MAX_RESTARTS,
        restart_delays_seconds: tuple[float, ...] = RESTART_DELAYS_SECONDS,
    ) -> None:
        self._command = command
        self._stop_at = stop_at
        self._now = now
        self._stop_grace_seconds = stop_grace_seconds
        self._max_restarts = max_restarts
        self._restart_delays_seconds = restart_delays_seconds
        self._stop_requested = threading.Event()

    def request_stop(self) -> None:
        """Stop the node and do not start it again (used by the SIGINT/SIGTERM handlers)."""
        self._stop_requested.set()

    def run(self) -> int:
        """Supervise until the stop time; return 0 for a clean day, 1 if restarts ran out."""
        restarts = 0
        while not self._stop_requested.is_set():
            remaining = self._seconds_until_stop()
            if remaining <= 0:
                log.info("Stop time %s reached; not starting the node", self._stop_at)
                return 0
            log.info("Starting the node: %s", " ".join(self._command))
            child = subprocess.Popen(self._command)
            exit_code = self._wait(child)
            if exit_code == 0 or self._stop_requested.is_set() or self._seconds_until_stop() <= 0:
                log.info("Node stopped with exit code %s; supervisor done", exit_code)
                return 0
            if restarts >= self._max_restarts:
                log.error(
                    "Node exited with code %s and the %s restarts are used up; giving up",
                    exit_code,
                    self._max_restarts,
                )
                return 1
            delay = self._restart_delays_seconds[
                min(restarts, len(self._restart_delays_seconds) - 1)
            ]
            restarts += 1
            log.warning(
                "Node exited with code %s; restart %s/%s in %.0f s",
                exit_code,
                restarts,
                self._max_restarts,
                delay,
            )
            if self._stop_requested.wait(min(delay, max(self._seconds_until_stop(), 0))):
                break
        log.info("Stop requested; supervisor done")
        return 0

    def _wait(self, child: subprocess.Popen) -> int:
        """Wait for the child; at the stop time or on a stop request, stop it gracefully."""
        while True:
            timeout = min(1.0, max(self._seconds_until_stop(), 0.0))
            try:
                return child.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                pass
            if self._stop_requested.is_set() or self._seconds_until_stop() <= 0:
                return self._stop_child(child)

    def _stop_child(self, child: subprocess.Popen) -> int:
        log.info("Sending SIGTERM to the node (pid %s)", child.pid)
        child.send_signal(signal.SIGTERM)
        try:
            return child.wait(timeout=self._stop_grace_seconds)
        except subprocess.TimeoutExpired:
            log.error(
                "Node did not stop within %.0f s after SIGTERM; killing it",
                self._stop_grace_seconds,
            )
            child.kill()
            return child.wait()

    def _seconds_until_stop(self) -> float:
        now = self._now()
        stop = datetime.combine(now.date(), self._stop_at, tzinfo=now.tzinfo)
        return (stop - now).total_seconds()


def main() -> int:
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=[logging.StreamHandler(), logging.FileHandler(LOG_FILE)],
    )
    supervisor = Supervisor()
    for stop_signal in (signal.SIGINT, signal.SIGTERM):
        signal.signal(stop_signal, lambda *_: supervisor.request_stop())
    return supervisor.run()


if __name__ == "__main__":
    sys.exit(main())
