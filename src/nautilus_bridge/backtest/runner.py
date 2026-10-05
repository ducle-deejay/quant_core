from __future__ import annotations

from nautilus_trader.backtest import BacktestNode
from nautilus_trader.backtest import BacktestResult
from nautilus_trader.config import BacktestDataConfig
from nautilus_trader.config import BacktestRunConfig
from nautilus_trader.model import BarType
from nautilus_trader.model import InstrumentId
from nautilus_trader.model import StrategyId
from nautilus_trader.persistence import ParquetDataCatalog

from nautilus_bridge.actors.forecast import ForecastActor
from nautilus_bridge.actors.forecast import ForecastActorConfig
from nautilus_bridge.alphas.session_resampling import bar_row
from nautilus_bridge.alphas.session_resampling import bars_frame
from nautilus_bridge.alphas.session_resampling import resample_by_session
from nautilus_bridge.alphas.loader import load_alpha
# from nautilus_bridge.execution.directional import TWAPModifiedAlgorithm
# from nautilus_bridge.execution.directional import TWAPModifiedAlgorithmConfig
from nautilus_bridge.backtest.engine import engine_config
from nautilus_bridge.backtest.sample_split import backtest_period
from nautilus_bridge.backtest.venue import venue_config
from nautilus_bridge.strategies.directional import DirectionalStrategy
from nautilus_bridge.strategies.directional import DirectionalStrategyConfig


def run_backtest(
    *,
    instrument_id: str,
    timeframe: str,
    start: str | None,
    end: str | None,
    book_size: str,
    commission: str,
    alpha: str,
    strategy_id: str,
    fixed_contracts: int,
    catalog_path: str,
    output_dir: str,
) -> tuple[list[BacktestResult], BacktestNode, BacktestRunConfig]:
    instrument_id = InstrumentId.from_str(instrument_id)
    source_bar_type = BarType.from_str(f"{instrument_id}-1-MINUTE-LAST-EXTERNAL")
    start_run, end_run = backtest_period(start=start, end=end)
    alpha_fn = load_alpha(alpha)

    run_config = BacktestRunConfig(
        venues=[venue_config(instrument_id, book_size, commission)],
        data=[
            BacktestDataConfig(
                data_type="Bar",
                catalog_path=catalog_path,
                bar_types=[str(source_bar_type)],
            ),
        ],
        engine=engine_config(catalog_path, output_dir),
        start=start_run,
        end=end_run,
        dispose_on_completion=False,
    )

    source_bars = bars_frame(
        bar_row(bar)
        for bar in ParquetDataCatalog(catalog_path).query_bars(
            [str(source_bar_type)],
            end=end_run.value,
        )
    )
    precomputed_forecast = alpha_fn(resample_by_session(source_bars, timeframe))

    actor = ForecastActor(
        config=ForecastActorConfig(
            instrument_id=instrument_id,
            source_bar_type=source_bar_type,
            timeframe=timeframe,
            alpha_fn=alpha_fn,
            precomputed_forecast=precomputed_forecast,
        ),
    )

    # execution = TWAPModifiedAlgorithm(
    #     config=TWAPModifiedAlgorithmConfig(
    #         exec_algorithm_id=ExecAlgorithmId("DIRECTIONAL"),
    #         bar_type=TARGET_BAR_TYPE,
    #     ),
    # )

    strategy = DirectionalStrategy(
        config=DirectionalStrategyConfig(
            strategy_id=StrategyId(strategy_id),
            instrument_id=instrument_id,
            bar_type=source_bar_type,
            manage_gtd_expiry=True,
            fixed_contracts=fixed_contracts,
        ),
    )

    node = BacktestNode(configs=[run_config])
    node.build()
    node.add_actor(run_config.id, actor)
    node.add_strategy(run_config.id, strategy)
    # node.add_exec_algorithm(run_config.id, execution)

    return node.run(), node, run_config
