"""Data actor computing the EMA cross signal for an EMACross strategy.

Adapted from the EMACross reference strategy
(docs/tutorials/ema_cross.py in the nautilus_trader repository) and the
DataActor example (docs/concepts/actors.md).
"""

from __future__ import annotations

from nautilus_trader.common import DataActor
from nautilus_trader.common import DataActorConfig
from nautilus_trader.indicators import ExponentialMovingAverage
from nautilus_trader.model import Bar
from nautilus_trader.model import BarType
from nautilus_trader.model import InstrumentId


SIGNAL_NAME = "EMA_CROSS"


class EMACrossActorConfig(DataActorConfig):
    def __init__(
        self,
        *,
        instrument_id: InstrumentId,
        resolution: str = "1",
        fast_ema_period: int = 10,
        slow_ema_period: int = 20,
        signal_name: str = SIGNAL_NAME,
        **_kwargs: object,
    ) -> None:
        super().__init__()
        self.instrument_id = instrument_id
        self.bar_type = BarType.from_str(
            f"{instrument_id}-{resolution}-MINUTE-LAST-EXTERNAL",
        )
        self.fast_ema_period = fast_ema_period
        self.slow_ema_period = slow_ema_period
        self.signal_name = signal_name


class EMACrossActor(DataActor):
    """Publish the EMA cross state as a signal: LONG or SHORT."""

    def __init__(self, config: EMACrossActorConfig) -> None:
        super().__init__(config)
        self.fast_ema = ExponentialMovingAverage(config.fast_ema_period)
        self.slow_ema = ExponentialMovingAverage(config.slow_ema_period)

    def on_start(self) -> None:
        self.register_indicator_for_bars(self.config.bar_type, self.fast_ema)
        self.register_indicator_for_bars(self.config.bar_type, self.slow_ema)
        self.subscribe_bars(self.config.bar_type)

    def on_bar(self, _bar: Bar) -> None:
        if not self.indicators_initialized():
            return

        if self.fast_ema.value >= self.slow_ema.value:
            self.publish_signal(self.config.signal_name, "LONG")
        else:
            self.publish_signal(self.config.signal_name, "SHORT")
