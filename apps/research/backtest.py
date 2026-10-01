from __future__ import annotations

from nautilus_trader.common import CacheConfig
from nautilus_trader.common import LogLevel

from nautilus_trader.model import AccountType
from nautilus_trader.model import BarType
from nautilus_trader.model import BookType
from nautilus_trader.model import Currency
from nautilus_trader.model import CurrencyType
from nautilus_trader.model import InstrumentId
from nautilus_trader.model import ExecAlgorithmId
from nautilus_trader.model import Money
from nautilus_trader.model import OmsType
from nautilus_trader.model import StandardMarginModel

from nautilus_trader.model import AggregationSource
from nautilus_trader.model import BarAggregation
from nautilus_trader.model import BarSpecification
from nautilus_trader.model import BarType
from nautilus_trader.model import PriceType
from nautilus_trader.model import StrategyId

from nautilus_trader.config import BacktestDataConfig
from nautilus_trader.config import BacktestEngineConfig
from nautilus_trader.config import BacktestRunConfig
from nautilus_trader.config import BacktestVenueConfig
from nautilus_trader.config import DataEngineConfig
from nautilus_trader.config import FileWriterConfig
from nautilus_trader.config import LoggerConfig
from nautilus_trader.persistence import DataCatalogConfig

from nautilus_trader.backtest import BacktestNode
from nautilus_trader.execution import PerContractFeeModel

from nautilus_bridge.actors.directional_alpha import DirectionalAlphaActor
from nautilus_bridge.actors.directional_alpha import DirectionalAlphaActorConfig
# from nautilus_bridge.execution.directional import TWAPModifiedAlgorithm
# from nautilus_bridge.execution.directional import TWAPModifiedAlgorithmConfig
from nautilus_bridge.backtest.run_window import backtest_period
from nautilus_bridge.strategies.directional import DirectionalStrategy
from nautilus_bridge.strategies.directional import DirectionalStrategyConfig

from nautilus_bridge.analyzer.analyzer import analyze


CATALOG_PATH = "/Users/ducle/repos/quant_core/data/catalog"

INSTRUMENT_ID = InstrumentId.from_str("VN30F1M.HNX")

TIME_FRAME = 15
TARGET_BAR_TYPE = BarType.from_str(
    f"{INSTRUMENT_ID}-{TIME_FRAME}-MINUTE-LAST-INTERNAL@1-MINUTE-EXTERNAL"
)
SOURCE_BAR_TYPE = BarType.from_str(
    f"{INSTRUMENT_ID}-1-MINUTE-LAST-EXTERNAL"
)

start = "2018-09-25"
end = "2026"
start_run, end_run = backtest_period(start=start, end=end)

BOOK_SIZE = "100_000_000 VND"
COMMISSION = "22750 VND"

Currency.register(
    Currency("VND", 0, 704, "Vietnamese dong", CurrencyType.FIAT),
)

bar_data = BacktestDataConfig(
    data_type="Bar",
    catalog_path=CATALOG_PATH,
    bar_types=[str(SOURCE_BAR_TYPE)],
)

data_configs = [
    bar_data
]

venue_configs = [
    BacktestVenueConfig(
        name="HNX",
        oms_type=OmsType.NETTING,
        account_type=AccountType.MARGIN,
        book_type=BookType.L1_MBP,
        bar_execution=True,
        starting_balances=[BOOK_SIZE],
        margin_model=StandardMarginModel(),
        fee_model=PerContractFeeModel(Money.from_str(COMMISSION))
    )
]

logging = LoggerConfig(
    clear_log_file=True,
    stdout_level=LogLevel.OFF,
    fileout_level=LogLevel.INFO,
    file_config=FileWriterConfig(
        directory="/Users/ducle/repos/quant_core/tmp/directional/",
        file_name="backtest"
    )
)

engine_configs = BacktestEngineConfig(
    logging=logging,
    data_engine=DataEngineConfig(time_bars_build_with_no_updates=False),  # No INTERNAL time bars outside trading hours
    cache=CacheConfig(bar_capacity=10_000),  # Must hold every warmup bar of the target bar type until on_historical_bars reads them
    catalogs=[DataCatalogConfig(CATALOG_PATH)],  # Serves the actor's warmup request
)

run_configs = BacktestRunConfig(
    venues=venue_configs,
    data=data_configs,
    engine= engine_configs,
    start=start_run,
    end=end_run,
    dispose_on_completion=False,
)

actor_configs = DirectionalAlphaActorConfig(
    instrument_id=INSTRUMENT_ID,
    bar_type=TARGET_BAR_TYPE,
    debug=True,
)

# execution_configs = TWAPModifiedAlgorithmConfig(
#     exec_algorithm_id=ExecAlgorithmId("DIRECTIONAL"),
#     bar_type=TARGET_BAR_TYPE,
# )

strategy_configs = DirectionalStrategyConfig(
    strategy_id=StrategyId('VN30F1M-V1'),
    instrument_id=INSTRUMENT_ID,
    bar_type=TARGET_BAR_TYPE,
    manage_gtd_expiry=True,
    trade_size=1
)

actor = DirectionalAlphaActor(
    config=actor_configs
)

# execution = TWAPModifiedAlgorithm(
#     config=execution_configs
# )

strategy = DirectionalStrategy(
    config=strategy_configs,
)

node = BacktestNode(configs=[run_configs])
node.build()
node.add_actor(run_configs.id, actor)
node.add_strategy(run_configs.id, strategy)
# node.add_exec_algorithm(run_configs.id, execution)

results = node.run()

analyze(
    results,
    node,
    run_configs,
    pos_dir="/Users/ducle/repos/quant_core/tmp/directional",
)
