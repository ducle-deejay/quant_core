from __future__ import annotations

from collections.abc import Sequence

import pandas as pd

from nautilus_trader.common import DataActor
from nautilus_trader.common import DataActorConfig
from nautilus_trader.model import Bar
from nautilus_trader.model import BarType
from nautilus_trader.model import CustomData
from nautilus_trader.model import InstrumentId

from nautilus_bridge.alphas.frame import BinRow
from nautilus_bridge.alphas.frame import SessionBinner
from nautilus_bridge.alphas.frame import bar_row
from nautilus_bridge.alphas.sources import AlphaFn
from nautilus_bridge.alphas.sources import AlphaSource
from nautilus_bridge.alphas.sources import PrecomputedSource
from nautilus_bridge.alphas.sources import RollingSource
from nautilus_bridge.data.custom_data import ExposureData
from nautilus_bridge.data.trading_days import CATALOG_PATH
from nautilus_bridge.data.trading_days import LOOKBACK_TRADING_DAYS
from nautilus_bridge.data.trading_days import warmup_start


class VectorAlphaActorConfig(DataActorConfig):
    def __init__(
        self,
        *,
        instrument_id: InstrumentId,
        bar_type: BarType,
        timeframe: pd.Timedelta,
        alpha_fn: AlphaFn,
        precomputed_exposure: pd.Series | None = None,
        **_kwargs: object,
    ) -> None:
        super().__init__()
        self.instrument_id = instrument_id
        self.bar_type = bar_type
        self.timeframe = timeframe
        self.alpha_fn = alpha_fn
        self.precomputed_exposure = precomputed_exposure


class VectorAlphaActor(DataActor):

    def __init__(self, config: VectorAlphaActorConfig) -> None:
        super().__init__(config)
        self.binner = SessionBinner(config.timeframe)
        self.source: AlphaSource
        if config.precomputed_exposure is not None:
            self.source = PrecomputedSource(config.precomputed_exposure)
        else:
            self.source = RollingSource(config.alpha_fn, LOOKBACK_TRADING_DAYS)

    def on_start(self) -> None:
        if isinstance(self.source, RollingSource):
            self._request_warmup()
        self.subscribe_bars(self.config.bar_type)

    def _request_warmup(self) -> None:
        start = warmup_start(
            CATALOG_PATH,
            self.config.bar_type,
            self.clock.utc_now(),
            LOOKBACK_TRADING_DAYS,
        )
        self.request_bars(self.config.bar_type, start=start)

    def on_historical_bars(self, bars: Sequence[Bar]) -> None:
        bins: list[BinRow] = []
        for bar in sorted(bars, key=lambda bar: bar.ts_init):
            bins.extend(self.binner.update(bar_row(bar)))
        self.source.warmup(bins)

    def on_bar(self, bar: Bar) -> None:
        for bin_row in self.binner.update(bar_row(bar)):
            self._publish(bin_row)

    def _publish(self, bin_row: BinRow) -> None:
        target_exposure = self.source.update(bin_row)
        if target_exposure is None:
            return

        exposure = ExposureData(
            target_exposure=target_exposure,
            ts_event=bin_row[0],
            ts_init=self.clock.timestamp_ns(),
        )
        self.publish_data(ExposureData.TYPE, CustomData(ExposureData.TYPE, exposure))
