"""Host a LiveNode on an asyncio loop and report why it stopped.

Follows docs/concepts/live.md, "Hosted event loops": ``run_async()`` leaves SIGINT and
SIGTERM to the host, so this module installs them and records whether a stop was
requested. The exit code tells a supervisor whether a restart is needed:

- 0: the node stopped because the process received SIGINT or SIGTERM
- 1: the node stopped by itself (e.g. ``shutdown_on_error`` after an ERROR log)
"""

from __future__ import annotations

import asyncio
import signal

from nautilus_trader.live import LiveNode

STOP_SIGNALS = (signal.SIGINT, signal.SIGTERM)


async def run_node(node: LiveNode) -> int:
    """Run the node until it stops; return 0 for a signal-requested stop, 1 otherwise."""
    handle = node.handle()
    stop_requested = False

    def request_stop() -> None:
        nonlocal stop_requested
        stop_requested = True
        handle.stop()

    loop = asyncio.get_running_loop()
    for stop_signal in STOP_SIGNALS:
        loop.add_signal_handler(stop_signal, request_stop)
    try:
        await node.run_async()
    finally:
        for stop_signal in STOP_SIGNALS:
            loop.remove_signal_handler(stop_signal)
    return 0 if stop_requested else 1
