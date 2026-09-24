from __future__ import annotations

from decimal import Decimal

from nautilus_trader.config import StrategyConfig
from nautilus_trader.model import InstrumentId
from nautilus_trader.model import OrderSide
from nautilus_trader.trading import Strategy


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
        self.subscribe_signal("directional")

    def on_signal(self, signal) -> None:
        if self.instrument is None:
            return
        if signal.value == "long":
            if self.portfolio.is_net_flat(self.config.instrument_id):
                self.buy()
            elif self.portfolio.is_net_short(self.config.instrument_id):
                self.close_all_positions(self.config.instrument_id)
                self.buy()
        elif signal.value == "short":
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
