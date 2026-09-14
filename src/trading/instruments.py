"""Deprecated shim: statics live in ``core.instruments``, Nautilus builders in ``market_data.instruments``."""

from market_data.instruments import (
    FuturesInstrumentSpec,
    build_continuous_futures_contract,
    build_futures_contract,
    load_futures_instrument_spec,
)
