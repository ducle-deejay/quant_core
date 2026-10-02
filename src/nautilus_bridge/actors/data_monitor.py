from __future__ import annotations

import enum
from dataclasses import dataclass
from datetime import datetime
from datetime import time
from datetime import timedelta
from zoneinfo import ZoneInfo

from nautilus_trader.common import DataActor
from nautilus_trader.common import DataActorConfig
from nautilus_trader.common import QueueCondition
from nautilus_trader.common import QueueState
from nautilus_trader.common import QueueStateChanged
from nautilus_trader.common import SystemChannel
from nautilus_trader.common import TimeEvent
from nautilus_trader.model import Bar
from nautilus_trader.model import BarType
from nautilus_trader.model import InstrumentId
from nautilus_trader.model import TradeTick

from nautilus_bridge.adapters.entrade.constants import VN_TZ
from nautilus_bridge.instruments.derivatives.futures.vn30f1m import VN30F1M_SESSIONS

CHECK_TIMER_NAME = "data_monitor.check"


class HealthState(enum.Enum):
    OK = "OK"
    DEGRADED = "DEGRADED"
    DOWN = "DOWN"


@dataclass(frozen=True)
class DataHealth:
    instrument_id: InstrumentId
    state: HealthState
    reasons: tuple[str, ...]
    ts: int


class DataMonitorActorConfig(DataActorConfig):
    def __init__(
        self,
        *,
        instrument_id: InstrumentId,
        bar_type: BarType,
        stale_after: timedelta,
        max_latency: timedelta,
        check_interval: timedelta = timedelta(seconds=5),
        sessions: tuple[tuple[time, time], ...] = VN30F1M_SESSIONS.continuous,
        **_kwargs: object,
    ) -> None:
        super().__init__()
        self.instrument_id = instrument_id
        self.bar_type = bar_type
        self.stale_after = stale_after
        self.max_latency = max_latency
        self.check_interval = check_interval
        self.sessions = sessions


class DataMonitorActor(DataActor):
    def __init__(self, config: DataMonitorActorConfig) -> None:
        super().__init__(config)
        self.topic = f"app.data_health.{config.instrument_id}"
        self._tz = ZoneInfo(VN_TZ)
        self._clear_state()

    def on_start(self) -> None:
        self.started_ns = self.clock.timestamp_ns()
        self.subscribe_queue_state(channel=SystemChannel.DATA_EVENTS)
        self.subscribe_trades(self.config.instrument_id)
        self.subscribe_bars(self.config.bar_type)
        self._schedule_check()

    def on_resume(self) -> None:
        self._schedule_check()

    def on_stop(self) -> None:
        self.unsubscribe_queue_state(channel=SystemChannel.DATA_EVENTS)
        self.clock.cancel_timer(CHECK_TIMER_NAME)

    def on_reset(self) -> None:
        self._clear_state()

    def on_trade(self, trade: TradeTick) -> None:
        self.last_trade_ts_init = trade.ts_init
        self.last_trade_latency_ns = trade.ts_init - trade.ts_event

    def on_bar(self, bar: Bar) -> None:
        last = self.last_bar_ts_event
        self.last_bar_ts_event = bar.ts_event
        if last is None:
            return
        session = self._session_of(bar.ts_event)
        same_session = session is not None and session == self._session_of(last)
        interval_ns = self.config.bar_type.spec.get_interval_ns()
        self.bar_gap = same_session and bar.ts_event - last > interval_ns

    def on_queue_state(self, event: QueueStateChanged) -> None:
        if event.state == QueueState.TRIGGERED:
            self.queue_conditions.add(event.condition)
        else:
            self.queue_conditions.discard(event.condition)

    def _on_check(self, event: TimeEvent) -> None:
        now_ns = self.clock.timestamp_ns()
        down: list[str] = []
        degraded: list[str] = []

        session_start_ns = self._current_session_start_ns(now_ns)
        if session_start_ns is not None:
            last_ns = max(self.last_trade_ts_init or self.started_ns, session_start_ns)
            if now_ns - last_ns > self._ns(self.config.stale_after):
                down.append("stale_trades")

        if QueueCondition.BACKLOGGED in self.queue_conditions:
            degraded.append("queue_backlogged")
        if QueueCondition.SLOW in self.queue_conditions:
            degraded.append("queue_slow")
        if self.last_trade_latency_ns > self._ns(self.config.max_latency):
            degraded.append("latency")
        if self.bar_gap:
            degraded.append("missing_bars")

        if down:
            state = HealthState.DOWN
        elif degraded:
            state = HealthState.DEGRADED
        else:
            state = HealthState.OK
        reasons = tuple(down + degraded)

        if (state, reasons) == self.last_published:
            return
        self.last_published = (state, reasons)
        self.publish_message(
            self.topic,
            DataHealth(self.config.instrument_id, state, reasons, now_ns),
        )

    def _schedule_check(self) -> None:
        self.clock.set_timer(
            CHECK_TIMER_NAME,
            self.config.check_interval,
            callback=self._on_check,
        )

    def _clear_state(self) -> None:
        self.started_ns = 0
        self.last_trade_ts_init: int | None = None
        self.last_trade_latency_ns = 0
        self.last_bar_ts_event: int | None = None
        self.bar_gap = False
        self.queue_conditions: set[QueueCondition] = set()
        self.last_published: tuple[HealthState, tuple[str, ...]] | None = None

    def _session_of(self, ts_ns: int) -> tuple[object, int] | None:
        local = datetime.fromtimestamp(ts_ns / 1e9, self._tz)
        for index, (start, end) in enumerate(self.config.sessions):
            if start < local.time() <= end:
                return local.date(), index
        return None

    def _current_session_start_ns(self, now_ns: int) -> int | None:
        local = datetime.fromtimestamp(now_ns / 1e9, self._tz)
        for start, end in self.config.sessions:
            if start <= local.time() < end:
                return int(datetime.combine(local.date(), start, self._tz).timestamp() * 1e9)
        return None

    @staticmethod
    def _ns(delta: timedelta) -> int:
        return int(delta.total_seconds() * 1e9)
