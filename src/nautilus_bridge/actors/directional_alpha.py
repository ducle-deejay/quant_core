from __future__ import annotations

from nautilus_trader.common import DataActor
from nautilus_trader.common import DataActorConfig
from nautilus_trader.indicators import ExponentialMovingAverage
from nautilus_trader.model import Bar
from nautilus_trader.model import BarType
from nautilus_trader.model import CustomData
from nautilus_trader.model import InstrumentId

from nautilus_bridge.data.custom_data import ExposureData

class DirectionalAlphaActorConfig(DataActorConfig):
    def __init__(
        self,
        *,
        instrument_id: InstrumentId,
        bar_type: BarType,
        **_kwargs: object,
    ) -> None:
        super().__init__()
        self.instrument_id = instrument_id
        self.bar_type = bar_type


class DirectionalAlphaActor(DataActor):
    fast_ema_period = 10
    slow_ema_period = 20

    def __init__(self, config: DirectionalAlphaActorConfig) -> None:
        super().__init__(config)
        self.fast_ema = ExponentialMovingAverage(self.fast_ema_period)
        self.slow_ema = ExponentialMovingAverage(self.slow_ema_period)

    def on_start(self) -> None:
        self.register_indicator_for_bars(self.config.bar_type, self.fast_ema)
        self.register_indicator_for_bars(self.config.bar_type, self.slow_ema)
        self.subscribe_bars(self.config.bar_type)

    def on_bar(self, bar: Bar) -> None:
        if not self.indicators_initialized():
            return

        if self.fast_ema.value >= self.slow_ema.value: 
            target_exposure = 1
        else: 
            target_exposure = -1

        target_exposure = ExposureData(
            target_exposure=target_exposure,
            ts_event=bar.ts_event,
            ts_init=self.clock.timestamp_ns(),
        )

        data_type = target_exposure.TYPE
        data = CustomData(target_exposure.TYPE, target_exposure)
        self.publish_data(data_type, data)
