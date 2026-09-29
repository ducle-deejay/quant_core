"""Behaviour of the live runner that the supervisor relies on, and of the live node build."""

from __future__ import annotations

import asyncio
import gc
import os
import signal
from pathlib import Path

import pytest

from nautilus_bridge.live import live
from nautilus_bridge.live.runner import run_node


class FakeHandle:
    def __init__(self) -> None:
        self.stopped = asyncio.Event()

    def stop(self) -> None:
        self.stopped.set()


class FakeNode:
    """Stops either when its handle is stopped or on its own after ``self_stop_after`` seconds."""

    def __init__(self, self_stop_after: float | None) -> None:
        self._handle = FakeHandle()
        self._self_stop_after = self_stop_after

    def handle(self) -> FakeHandle:
        return self._handle

    async def run_async(self) -> None:
        if self._self_stop_after is not None:
            await asyncio.sleep(self._self_stop_after)
            return
        await self._handle.stopped.wait()


def test_sigterm_stops_the_node_with_exit_code_0() -> None:
    async def run() -> int:
        node = FakeNode(self_stop_after=None)
        task = asyncio.create_task(run_node(node))
        await asyncio.sleep(0.05)
        os.kill(os.getpid(), signal.SIGTERM)
        return await asyncio.wait_for(task, timeout=2)

    assert asyncio.run(run()) == 0


def test_node_that_stops_by_itself_exits_with_code_1() -> None:
    assert asyncio.run(run_node(FakeNode(self_stop_after=0.01))) == 1


def test_live_node_builds_with_the_backtest_components(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    for name in ("API_KEY", "API_SECRET", "ENTRADE_USERNAME", "ENTRADE_PASSWORD"):
        monkeypatch.setenv(name, "test")
    monkeypatch.setattr(live, "load_dotenv", lambda *args, **kwargs: None)
    monkeypatch.setattr(live, "resolve_entrade_account_ids", lambda *args, **kwargs: ("123", "DNSE-456"))
    monkeypatch.setattr(live, "LOG_DIRECTORY", tmp_path)

    node = live.build_node()
    try:
        assert node.trader_id == live.TRADER_ID
    finally:
        node.dispose()
        del node
        gc.collect()
