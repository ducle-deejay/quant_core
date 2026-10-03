"""Builders for DNSE day batches used by catalog tests."""

from __future__ import annotations

import pandas as pd
from nautilus_trader.model import AggressorSide
from nautilus_trader.model import Bar
from nautilus_trader.model import BarType
from nautilus_trader.model import BookOrder
from nautilus_trader.model import OrderBookDepth10
from nautilus_trader.model import OrderSide
from nautilus_trader.model import TradeId
from nautilus_trader.model import TradeTick

from market_data.sources.dnse.transform import BAR_TYPE
from nautilus_bridge.instruments.derivatives.futures.vn30f1m import build_continuous_futures_contract


INSTRUMENT = build_continuous_futures_contract()
MINUTE_NS = 60_000_000_000


def day_batches(day: str, price: float) -> list[list]:
    """Instruments, bars, trades in two batches, and depth, as DNSE transform yields them."""
    px, qty = INSTRUMENT.make_price(price), INSTRUMENT.make_qty(1)
    opens = pd.date_range(f"{day} 09:00", periods=4, freq="min", tz="Asia/Ho_Chi_Minh")
    bars = [Bar(BarType.from_str(BAR_TYPE), px, px, px, px, qty, t.value, t.value + MINUTE_NS) for t in opens]
    trades = [
        TradeTick(INSTRUMENT.id, px, qty, AggressorSide.BUY, TradeId(f"{day}-{i}"), t.value, t.value)
        for i, t in enumerate(opens)
    ]

    def levels(side: OrderSide) -> list[BookOrder]:
        return [BookOrder(side, px, qty, 0) for _ in range(10)]

    depth = [
        OrderBookDepth10(INSTRUMENT.id, levels(OrderSide.BUY), levels(OrderSide.SELL), [0] * 10, [0] * 10, 0, 0, t.value, t.value)
        for t in opens
    ]
    return [[INSTRUMENT], bars, trades[:2], trades[2:], depth]
