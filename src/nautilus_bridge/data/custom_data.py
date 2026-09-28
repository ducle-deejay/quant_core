from dataclasses import dataclass

from nautilus_trader.model import DataType


@dataclass(frozen=True)
class ExposureData:
    TYPE = DataType("ExposureData")

    target_exposure: float
    ts_event: int
    ts_init: int

from nautilus_trader.model import register_custom_data_class