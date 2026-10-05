from __future__ import annotations

from collections.abc import Sequence

import pandas as pd

from nautilus_trader.common import DataActor
from nautilus_trader.common import DataActorConfig
from nautilus_trader.indicators import ExponentialMovingAverage
from nautilus_trader.model import Bar
from nautilus_trader.model import BarType
from nautilus_trader.model import CustomData
from nautilus_trader.model import InstrumentId

from nautilus_bridge.data.custom_data import ForecastData
from nautilus_bridge.data.trading_days import warmup_start


class DirectionalAlphaActorConfig(DataActorConfig):
    def __init__(
        self,
        *,
        instrument_id: InstrumentId,
        bar_type: BarType,
        debug: bool = False,
        **_kwargs: object,
    ) -> None:
        super().__init__()
        self.instrument_id = instrument_id
        self.bar_type = bar_type
        self.debug = debug


class DirectionalAlphaActor(DataActor):
    fast_ema_period = 10
    slow_ema_period = 20
    warmup_trading_days = 30

    def __init__(self, config: DirectionalAlphaActorConfig) -> None:
        super().__init__(config)
        self.fast_ema = ExponentialMovingAverage(self.fast_ema_period)
        self.slow_ema = ExponentialMovingAverage(self.slow_ema_period)
        self.debug_rows: list[dict[str, float]] = []
        self.debug_df: pd.DataFrame | None = None

    def on_start(self) -> None:
        bar_type = self.config.bar_type
        self.register_indicator_for_bars(bar_type, self.fast_ema)
        self.register_indicator_for_bars(bar_type, self.slow_ema)
        self._request_warmup()
        self.subscribe_bars(bar_type)

    def _request_warmup(self) -> None:
        bar_type = self.config.bar_type
        self.warmup_start = warmup_start(
            bar_type.composite(),
            self.clock.utc_now(),
            self.warmup_trading_days,
        )
        self.request_bars(
            bar_type.composite(),
            start=self.warmup_start,
            params={"bar_types": [str(bar_type)]},
        )

    def on_historical_bars(self, bars: Sequence[Bar]) -> None:
        bar_type = self.config.bar_type
        if bar_type.spec == bar_type.composite().spec:
            warmup_bars = list(bars)
        else:
            warmup_bars = list(reversed(self.cache.bars(bar_type.standard()) or []))
            for bar in warmup_bars:
                self.fast_ema.handle_bar(bar)
                self.slow_ema.handle_bar(bar)
        for bar in warmup_bars:
            self._debug(bar)

    def on_bar(self, bar: Bar) -> None:
        if not self.indicators_initialized():
            self._debug(bar)
            return

        if self.fast_ema.value >= self.slow_ema.value:
            forecast = 1
        else:
            forecast = -1

        self._debug(
            bar,
            fast_ema=self.fast_ema.value,
            slow_ema=self.slow_ema.value,
            forecast=forecast,
        )

        forecast_data = ForecastData(
            forecast=forecast,
            ts_event=bar.ts_event,
            ts_init=self.clock.timestamp_ns(),
        )

        data_type = forecast_data.TYPE
        data = CustomData(forecast_data.TYPE, forecast_data)
        self.publish_data(data_type, data)

    def on_stop(self) -> None:
        if self.config.debug:
            self.debug_df = self._debug_frame()
            self.log.info(f"Debug frame ready: {len(self.debug_df)} rows")

    def _debug_frame(self) -> pd.DataFrame:
        df = pd.DataFrame(self.debug_rows)
        if df.empty:
            return df
        df.index = pd.to_datetime(df.pop("ts_event"), utc=True).dt.tz_convert("Asia/Ho_Chi_Minh")
        return df

    def _debug(self, bar: Bar, **values: float) -> None:
        if not self.config.debug:
            return
        self.debug_rows.append(
            {
                "ts_event": bar.ts_event,
                "open": bar.open.as_double(),
                "high": bar.high.as_double(),
                "low": bar.low.as_double(),
                "close": bar.close.as_double(),
                "volume": bar.volume.as_double(),
                **values,
            },
        )
