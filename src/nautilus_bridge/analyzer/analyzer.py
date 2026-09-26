from __future__ import annotations

import webbrowser
from http.server import BaseHTTPRequestHandler
from http.server import HTTPServer
from pathlib import Path
from typing import Any

from tabulate import tabulate

from nautilus_trader.backtest import BacktestNode
from nautilus_trader.backtest import BacktestResult
from nautilus_trader.config import BacktestRunConfig
from nautilus_trader.config import TearsheetConfig
from nautilus_trader.analysis import create_tearsheet

def render_metrics(
    result: BacktestResult,
    *,
    stats_pnls: bool = False,
    stats_returns: bool = True,
    stats_general: bool = False,
) -> None:
    def render_table(metrics: Any) -> None:
        print(
            tabulate(
                metrics.items(),
                headers=["Metric", "Value"],
                tablefmt="fancy_grid",
                floatfmt=".4f",
            )
        )

    if stats_pnls:
        render_table(result.stats_pnls["VND"])
    if stats_returns:
        render_table(result.stats_returns)
    if stats_general:
        render_table(result.stats_general)


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
        theme="nautilus_dark"
    )

    render_metrics(results[0], stats_returns=True)

    tearsheet = create_tearsheet(
        engine=results[0],
        node=node,
        output_path=None,
        config=tearsheet_config
    )

    render_tearsheet(tearsheet)

    report = node.generate_positions_report(run_configs.id)
    if pos_dir is not None:
        report.to_csv(Path(pos_dir) / "positions.csv", index=True)
