from __future__ import annotations

import webbrowser
from decimal import Decimal
from http.server import BaseHTTPRequestHandler
from http.server import HTTPServer
from pathlib import Path
from typing import Any

import pandas as pd
import plotly.graph_objects as go
from tabulate import tabulate

from nautilus_trader.backtest import BacktestNode
from nautilus_trader.backtest import BacktestResult
from nautilus_trader.config import BacktestRunConfig
from nautilus_trader.config import TearsheetConfig
from nautilus_trader.analysis import TearsheetCustomChart
from nautilus_trader.analysis import TearsheetRunInfoChart
from nautilus_trader.analysis import TearsheetStatsTableChart
from nautilus_trader.analysis import create_tearsheet
from nautilus_trader.analysis import register_tearsheet_chart
from nautilus_trader.analysis.tearsheet import _render_run_info
from nautilus_trader.model import InstrumentId
from nautilus_trader.model import Money

from nautilus_bridge.alphas.session_resampling import bars_per_day
from nautilus_bridge.analyzer.forecast_statistics import forecast_statistics
from nautilus_bridge.analyzer.statistics import HoldingPeriod
from nautilus_bridge.analyzer.statistics import Turnover
from nautilus_bridge.backtest.sample_split import period_label

STATS_ORDER = [
    "Sharpe Ratio (Realized, 252 days)",
    "Sortino Ratio (252 days)",
    "Average (Return)",
    "Returns Volatility (252 days)",
    Turnover.NAME,
    HoldingPeriod.NAME,
    "Profit Factor",
    "Average Win (Return)",
    "Average Loss (Return)",
    "Tail Ratio",
    "Returns Skewness",
    "Returns Kurtosis",
    "Long Ratio",
    "Risk Return Ratio",
]
ORDERED_STATS_CHART = "ordered_stats"
RUN_INFO_CHART = "run_info_with_alpha"
TABLE_STYLE = {"header_font_size": 15, "header_height": 30, "cells_font_size": 14, "cells_height": 26}


def ordered_stats(
    stats_returns: dict[str, Any],
    stats_general: dict[str, Any],
    forecast_stats: dict[str, float],
) -> dict[str, Any]:
    """Statistics in STATS_ORDER with forecast_stats after the realized Sharpe, then any others."""
    stats = {**stats_returns, **stats_general, **forecast_stats}
    if "Sharpe Ratio (252 days)" in stats:
        stats[STATS_ORDER[0]] = stats.pop("Sharpe Ratio (252 days)")
    order = [STATS_ORDER[0], *forecast_stats, *STATS_ORDER[1:]]
    ordered = {name: stats.pop(name) for name in order if name in stats}
    return {**ordered, **stats}


def render_metrics(stats: dict[str, Any]) -> None:
    missing = [name for name in STATS_ORDER if name not in stats]
    if missing:
        print(f"Statistics missing from this result: {', '.join(missing)}")
    print(
        tabulate(
            stats.items(),
            headers=["Metric", "Value"],
            tablefmt="fancy_grid",
            floatfmt=".4f",
        )
    )


def _render_ordered_stats_table(
    fig: go.Figure,
    row: int,
    col: int,
    stats_returns: dict[str, Any],
    stats_general: dict[str, Any],
    theme_config: dict[str, Any],
    forecast_stats: dict[str, float],
    **_kwargs: Any,
) -> None:
    stats = ordered_stats(stats_returns, stats_general, forecast_stats)
    colors = theme_config["colors"]
    row_colors = [
        colors["table_row_even"] if i % 2 == 0 else colors["table_row_odd"]
        for i in range(len(stats))
    ]
    fig.add_trace(
        go.Table(
            header={
                "values": ["<b>Metric</b>", "<b>Value</b>"],
                "fill_color": colors["primary"],
                "font": {"color": "white"},
                "align": "left",
            },
            cells={
                "values": [list(stats), [f"{value:.4f}" for value in stats.values()]],
                "fill_color": [row_colors, row_colors],
                "align": "left",
                "font": {"color": colors["table_text"]},
            },
            **TABLE_STYLE,
        ),
        row=row,
        col=col,
    )


def _render_run_info_with_alpha(
    fig: go.Figure,
    row: int,
    col: int,
    theme_config: dict[str, Any],
    alpha_name: str,
    run_info: dict[str, Any],
    account_info: dict[str, Any],
    **kwargs: Any,
) -> None:
    _render_run_info(
        fig=fig,
        row=row,
        col=col,
        theme_config=theme_config,
        run_info={"Alpha": alpha_name, **{name: value.replace("_", ",") for name, value in run_info.items()}},
        account_info={name: f"{Decimal(value):,}" for name, value in account_info.items()},
        **kwargs,
    )
    fig.data[-1].update(**TABLE_STYLE)


register_tearsheet_chart(
    name=ORDERED_STATS_CHART,
    subplot_type="table",
    title="Performance Statistics",
    renderer=_render_ordered_stats_table,
)
register_tearsheet_chart(
    name=RUN_INFO_CHART,
    subplot_type="table",
    title="Run Information",
    renderer=_render_run_info_with_alpha,
)


def tearsheet_charts(forecast_stats: dict[str, float], alpha_name: str) -> list:
    custom_charts = {
        TearsheetStatsTableChart: TearsheetCustomChart(
            chart=ORDERED_STATS_CHART, args={"forecast_stats": forecast_stats}
        ),
        TearsheetRunInfoChart: TearsheetCustomChart(chart=RUN_INFO_CHART, args={"alpha_name": alpha_name}),
    }
    return [custom_charts.get(type(chart), chart) for chart in TearsheetConfig().charts]


def render_tearsheet(html: str) -> None:
    page = html.encode("utf-8")

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(page)))
            self.end_headers()
            self.wfile.write(page)

        def log_message(self, _format: str, *args: object) -> None:
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    webbrowser.open(f"http://127.0.0.1:{server.server_port}")
    server.handle_request()
    server.server_close()


def analyze(
    results: list[BacktestResult],
    node: BacktestNode,
    run_configs: BacktestRunConfig,
    *,
    forecast: pd.Series,
    close: pd.Series,
    instrument_id: InstrumentId,
    timeframe: str,
    commission: str,
    alpha: str,
    pos_dir: str = None,
) -> None:

    start = pd.Timestamp(run_configs.start, tz="UTC")
    end = pd.Timestamp(run_configs.end, tz="UTC")

    in_period = (close.index >= start.value) & (close.index <= end.value)
    forecast_stats = forecast_statistics(
        forecast[in_period],
        close[in_period],
        bars_per_day(timeframe),
        node.get_engine_cache(run_configs.id).instrument(instrument_id).multiplier.as_double(),
        Money.from_str(commission).as_double(),
    )

    tearsheet_config = TearsheetConfig(
        theme="nautilus_dark",
        charts=tearsheet_charts(forecast_stats, Path(alpha).stem),
    )

    print(f"Period: {period_label(start, end)}")
    result = results[0]
    render_metrics(ordered_stats(result.stats_returns, result.stats_general, forecast_stats))

    tearsheet = create_tearsheet(
        engine=result,
        node=node,
        output_path=None,
        config=tearsheet_config
    )

    render_tearsheet(tearsheet)

    report = node.generate_positions_report(run_configs.id)
    if pos_dir is not None:
        report.to_csv(Path(pos_dir) / "positions.csv", index=True)
