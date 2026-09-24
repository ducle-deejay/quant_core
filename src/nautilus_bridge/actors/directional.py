from __future__ import annotations

from nautilus_trader.common import DataActor
from nautilus_trader.common import DataActorConfig
from nautilus_trader.indicators import ExponentialMovingAverage
from nautilus_trader.model import Bar
from nautilus_trader.model import BarType
from nautilus_trader.model import InstrumentId


class DirectionalActorConfig(DataActorConfig):
    def __init__(
        self,
        *,
        instrument_id: InstrumentId,
        resolution: str = "1",
        bar_type: BarType,
        **_kwargs: object,
    ) -> None:
        super().__init__()
        self.instrument_id = instrument_id
        self.bar_type = bar_type


class DirectionalActor(DataActor):
    fast_ema_period = 10
    slow_ema_period = 20

    def __init__(self, config: DirectionalActorConfig) -> None:
        super().__init__(config)
        self.fast_ema = ExponentialMovingAverage(self.fast_ema_period)
        self.slow_ema = ExponentialMovingAverage(self.slow_ema_period)

    def on_start(self) -> None:
        self.register_indicator_for_bars(self.config.bar_type, self.fast_ema)
        self.register_indicator_for_bars(self.config.bar_type, self.slow_ema)
        self.subscribe_bars(self.config.bar_type)

    def on_bar(self, _bar: Bar) -> None:
        if not self.indicators_initialized():
            return

        if self.fast_ema.value >= self.slow_ema.value:
            self.publish_signal("directional", "long")
        else:
            self.publish_signal("directional", "short")
