import pandas as pd
from nautilus_trader.persistence import ParquetDataCatalog

from nautilus_bridge.alphas.session_resampling import bar_row, bars_frame, resample_by_session
from nautilus_bridge.backtest.sample_split import sample_window
from nautilus_bridge.data.catalog import catalog_path
from nautilus_bridge.instruments.derivatives.futures.vn30f1m import VN30F1M_SESSIONS


def load_instrument(instrument_id):
    return ParquetDataCatalog(str(catalog_path())).instruments(instrument_ids=[instrument_id])[0]


def load_bars(instrument_id):
    catalog = ParquetDataCatalog(str(catalog_path()))
    return bars_frame(bar_row(bar) for bar in catalog.query_bars([f"{instrument_id}-1-MINUTE-LAST-EXTERNAL"]))


def session_bars(src, timeframe):
    bars = resample_by_session(src, timeframe)
    bars.index = pd.to_datetime(bars.index, unit="ns", utc=True).tz_convert(VN30F1M_SESSIONS.timezone)
    return bars


def forward_return(close, horizon):
    return close.pct_change(horizon).shift(-horizon)


def fit_mask(index, horizon):
    fit_start, fit_end = sample_window("FIT")
    realized_at = index.to_series().shift(-horizon)
    return ((index >= fit_start) & (realized_at < fit_end)).to_numpy()
