from __future__ import annotations

from decimal import Decimal

from nautilus_trader.config import StrategyConfig
from nautilus_trader.model import CustomData
from nautilus_trader.model import InstrumentId
from nautilus_trader.model import OrderSide
from nautilus_trader.trading import Strategy

from nautilus_bridge.data.custom_data import PositionData


class DirectionalStrategyConfig(StrategyConfig):
    def __init__(
        self,
        *,
        instrument_id: InstrumentId,
        trade_size: Decimal = Decimal("1"),
        **_kwargs: object,
    ) -> None:
        super().__init__()
        self.instrument_id = instrument_id
        self.trade_size = trade_size


class DirectionalStrategy(Strategy):

    def __init__(self, config: DirectionalStrategyConfig) -> None:
        super().__init__(config)
        self.instrument = None

    def on_start(self) -> None:
        self.instrument = self.cache.instrument(self.config.instrument_id)
        self.subscribe_data(PositionData.TYPE)

    def on_data(self, position_data: CustomData) -> None:
        position_data = position_data.data
        target_position = position_data.target_position

        if self.instrument is None:
            return
        
        if target_position > 0:
            if self.portfolio.is_net_flat(self.config.instrument_id):
                self.buy()
            elif self.portfolio.is_net_short(self.config.instrument_id):
                self.close_all_positions(self.config.instrument_id)
                self.buy()
        
        elif target_position < 0:
            if self.portfolio.is_net_flat(self.config.instrument_id):
                self.sell()
            elif self.portfolio.is_net_long(self.config.instrument_id):
                self.close_all_positions(self.config.instrument_id)
                self.sell()

    def buy(self) -> None:
        order = self.order_factory.market(
            self.config.instrument_id,
            OrderSide.BUY,
            self.instrument.make_qty(self.config.trade_size),
        )
        self.submit_order(order)

    def sell(self) -> None:
        order = self.order_factory.market(
            self.config.instrument_id,
            OrderSide.SELL,
            self.instrument.make_qty(self.config.trade_size),
        )
        self.submit_order(order)

    def on_stop(self) -> None:
        self.close_all_positions(self.config.instrument_id)
