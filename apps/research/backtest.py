from __future__ import annotations

from nautilus_bridge.analyzer.analyzer import analyze
from nautilus_bridge.backtest.runner import run_backtest

output_dir = "tmp/directional"
alpha = "apps/research/alphas/ema_cross.py"

instrument_id = "VN30F1M.HNX"
timeframe = "30-MINUTE"
start = "2018-09-25"
end = "2026"
book_size = "100_000_000 VND"
commission = "22750 VND"

results, node, run_config = run_backtest(
    instrument_id=instrument_id,
    timeframe=timeframe,
    start=start,
    end=end,
    book_size=book_size,
    commission=commission,
    alpha=alpha,
    strategy_id="VN30F1M-V1",
    fixed_contracts=1,
    output_dir=output_dir,
)

analyze(results, node, run_config, pos_dir=output_dir)
