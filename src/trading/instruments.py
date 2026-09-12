"""Deprecated shim: statics live in ``core.instruments``, Nautilus builders in ``market_data.instruments``."""

from core.instruments import CostModel, Instrument  # noqa: F401
from market_data.instruments import (  # noqa: F401
    FuturesInstrumentSpec,
    build_continuous_futures_contract,
    build_futures_contract,
    load_futures_instrument_spec,
)
