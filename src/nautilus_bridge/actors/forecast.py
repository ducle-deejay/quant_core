from __future__ import annotations

from collections.abc import Sequence

import pandas as pd

from nautilus_trader.common import DataActor
from nautilus_trader.common import DataActorConfig
from nautilus_trader.model import Bar
from nautilus_trader.model import BarType
from nautilus_trader.model import CustomData
from nautilus_trader.model import InstrumentId

from nautilus_bridge.alphas.session_resampling import SessionResampler
from nautilus_bridge.alphas.session_resampling import TargetBarRow
from nautilus_bridge.alphas.session_resampling import bar_row
from nautilus_bridge.alphas.forecast_runtime import AlphaFn
from nautilus_bridge.alphas.forecast_runtime import ForecastRuntime
from nautilus_bridge.alphas.forecast_runtime import PrecomputedForecast
from nautilus_bridge.alphas.forecast_runtime import RollingForecast
from nautilus_bridge.data.custom_data import ForecastData
from nautilus_bridge.data.trading_days import CATALOG_PATH
from nautilus_bridge.data.trading_days import LOOKBACK_TRADING_DAYS
from nautilus_bridge.data.trading_days import warmup_start


class ForecastActorConfig(DataActorConfig):
    def __init__(
        self,
        *,
        instrument_id: InstrumentId,
        source_bar_type: BarType,
        timeframe: str,
        alpha_fn: AlphaFn,
        precomputed_forecast: pd.Series | None = None,
        **_kwargs: object,
    ) -> None:
        super().__init__()
        self.instrument_id = instrument_id
        self.source_bar_type = source_bar_type
        self.timeframe = timeframe
        self.alpha_fn = alpha_fn
        self.precomputed_forecast = precomputed_forecast


class ForecastActor(DataActor):

    def __init__(self, config: ForecastActorConfig) -> None:
        super().__init__(config)
        self.resampler = SessionResampler(config.timeframe)
        self.forecast_runtime: ForecastRuntime
        if config.precomputed_forecast is not None:
            self.forecast_runtime = PrecomputedForecast(config.precomputed_forecast)
        else:
            self.forecast_runtime = RollingForecast(config.alpha_fn, LOOKBACK_TRADING_DAYS)

    def on_start(self) -> None:
        if isinstance(self.forecast_runtime, RollingForecast):
            self._request_warmup()
        self.subscribe_bars(self.config.source_bar_type)

    def _request_warmup(self) -> None:
        start = warmup_start(
            CATALOG_PATH,
            self.config.source_bar_type,
            self.clock.utc_now(),
            LOOKBACK_TRADING_DAYS,
        )
        self.request_bars(self.config.source_bar_type, start=start)

    def on_historical_bars(self, bars: Sequence[Bar]) -> None:
        target_bars: list[TargetBarRow] = []
        for bar in sorted(bars, key=lambda bar: bar.ts_init):
            target_bars.extend(self.resampler.update(bar_row(bar)))
        self.forecast_runtime.warmup(target_bars)

    def on_bar(self, bar: Bar) -> None:
        for target_bar in self.resampler.update(bar_row(bar)):
            self._publish(target_bar)

    def _publish(self, target_bar: TargetBarRow) -> None:
        forecast = self.forecast_runtime.update(target_bar)
        if forecast is None:
            return

        forecast_data = ForecastData(
            forecast=forecast,
            ts_event=target_bar[0],
            ts_init=self.clock.timestamp_ns(),
        )
        self.publish_data(ForecastData.TYPE, CustomData(ForecastData.TYPE, forecast_data))
