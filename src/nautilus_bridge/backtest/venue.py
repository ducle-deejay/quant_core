from __future__ import annotations

from collections.abc import Callable

from nautilus_trader.config import BacktestVenueConfig
from nautilus_trader.execution import PerContractFeeModel
from nautilus_trader.model import AccountType
from nautilus_trader.model import BookType
from nautilus_trader.model import InstrumentId
from nautilus_trader.model import Money
from nautilus_trader.model import OmsType
from nautilus_trader.model import StandardMarginModel


def hnx_venue_config(book_size: str, commission: str) -> BacktestVenueConfig:
    return BacktestVenueConfig(
        name="HNX",
        oms_type=OmsType.NETTING,
        account_type=AccountType.MARGIN,
        book_type=BookType.L1_MBP,
        bar_execution=True,
        starting_balances=[book_size],
        margin_model=StandardMarginModel(),
        fee_model=PerContractFeeModel(Money.from_str(commission)),
    )


VENUE_CONFIGS: dict[str, Callable[[str, str], BacktestVenueConfig]] = {
    "HNX": hnx_venue_config,
}


def venue_config(instrument_id: InstrumentId, book_size: str, commission: str) -> BacktestVenueConfig:
    venue = instrument_id.venue.value
    if venue not in VENUE_CONFIGS:
        raise ValueError(f"No backtest venue config for venue {venue}")
    return VENUE_CONFIGS[venue](book_size, commission)
