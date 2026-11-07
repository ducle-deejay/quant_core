from __future__ import annotations

import webbrowser
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
from nautilus_trader.analysis import TearsheetStatsTableChart
from nautilus_trader.analysis import create_tearsheet
from nautilus_trader.analysis import register_tearsheet_chart

from nautilus_bridge.analyzer.statistics import HoldingPeriod
from nautilus_bridge.analyzer.statistics import Turnover
from nautilus_bridge.backtest.sample_split import period_label

STATS_ORDER = [
    "Sharpe Ratio (252 days)",
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


def ordered_stats(stats_returns: dict[str, Any], stats_general: dict[str, Any]) -> dict[str, Any]:
    """Statistics in STATS_ORDER, then any others in the order given."""
    stats = {**stats_returns, **stats_general}
    ordered = {name: stats.pop(name) for name in STATS_ORDER if name in stats}
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
    **_kwargs: Any,
) -> None:
    stats = ordered_stats(stats_returns, stats_general)
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
                "font": {"color": "white", "size": 12},
                "align": "left",
            },
            cells={
                "values": [list(stats), [f"{value:.4f}" for value in stats.values()]],
                "fill_color": [row_colors, row_colors],
                "align": "left",
                "font": {"size": 11, "color": colors["table_text"]},
            },
        ),
        row=row,
        col=col,
    )


register_tearsheet_chart(
    name=ORDERED_STATS_CHART,
    subplot_type="table",
    title="Performance Statistics",
    renderer=_render_ordered_stats_table,
)

TEARSHEET_CHARTS = [
    TearsheetCustomChart(chart=ORDERED_STATS_CHART)
    if isinstance(chart, TearsheetStatsTableChart)
    else chart
    for chart in TearsheetConfig().charts
]


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
    pos_dir: str = None,
) -> None:

    tearsheet_config = TearsheetConfig(
        theme="nautilus_dark",
        charts=TEARSHEET_CHARTS,
    )

    start = pd.Timestamp(run_configs.start, tz="UTC")
    end = pd.Timestamp(run_configs.end, tz="UTC")
    print(f"Period: {period_label(start, end)}")
    result = results[0]
    render_metrics(ordered_stats(result.stats_returns, result.stats_general))

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
