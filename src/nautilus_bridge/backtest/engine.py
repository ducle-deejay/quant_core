from __future__ import annotations

from nautilus_trader.common import CacheConfig
from nautilus_trader.common import LogLevel
from nautilus_trader.config import BacktestEngineConfig
from nautilus_trader.config import DataEngineConfig
from nautilus_trader.config import FileWriterConfig
from nautilus_trader.config import LoggerConfig
from nautilus_trader.persistence import DataCatalogConfig


def engine_config(catalog_path: str, log_dir: str) -> BacktestEngineConfig:
    return BacktestEngineConfig(
        logging=LoggerConfig(
            clear_log_file=True,
            stdout_level=LogLevel.OFF,
            fileout_level=LogLevel.INFO,
            file_config=FileWriterConfig(directory=log_dir, file_name="backtest"),
        ),
        data_engine=DataEngineConfig(time_bars_build_with_no_updates=False),  # No INTERNAL time bars outside trading hours
        cache=CacheConfig(bar_capacity=10_000),  # Must hold every warmup bar of the target bar type until on_historical_bars reads them
        catalogs=[DataCatalogConfig(catalog_path)],  # Serves the actor's warmup request
    )
