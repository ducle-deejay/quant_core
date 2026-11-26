import pandas as pd
from nautilus_trader.persistence import ParquetDataCatalog

from methodica.alpha_miner.genetic import evolve
from nautilus_bridge.alphas.session_resampling import BAR_COLUMNS, bar_row, bars_frame
from nautilus_bridge.backtest.sample_split import sample_window
from nautilus_bridge.data.catalog import catalog_path


def fit_bars(instrument_id):
    bar_type = f"{instrument_id}-1-MINUTE-LAST-EXTERNAL"
    source_bars = bars_frame(bar_row(bar) for bar in ParquetDataCatalog(str(catalog_path())).query_bars([bar_type]))
    bars = source_bars.set_index(pd.to_datetime(source_bars["ts_init"], unit="ns", utc=True))[list(BAR_COLUMNS)]
    fit_start, fit_end = sample_window("FIT")
    return bars[(bars.index >= fit_start) & (bars.index < fit_end)]


def run_alpha_miner(*, instrument_id, seeds=(), horizon=10, population=100, top_k=10, max_depth=3, seed=0):
    return evolve(fit_bars(instrument_id), seeds, horizon, population, top_k, max_depth, seed)
