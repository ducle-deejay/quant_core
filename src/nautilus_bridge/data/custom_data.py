from dataclasses import dataclass

from nautilus_trader.model import DataType


@dataclass(frozen=True)
class PositionData:
    TYPE = DataType("PositionData")

    target_position: float
    ts_event: int
    ts_init: int

from nautilus_trader.model import register_custom_data_class