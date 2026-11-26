from __future__ import annotations

from methodica.alpha_evaluator.runner import run_alpha_evaluator

instrument_id = "VN30F1M.HNX"
horizon = 10
commission = "22750 VND"
alphas = {
    "ema_cross_5m": "(ewma(close, 50) - ewma(close, 100)) / ewm_std(ts_delta(close, 5), 100)",
    "momentum_5m": "ts_delta(close, 100) / ewm_std(ts_delta(close, 5), 100)",
    "reversal_1m": "-ts_delta(close, 3) / ewm_std(ts_delta(close, 1), 20)",
    "zscore_revert_5m": "-(close - ts_mean(close, 300)) / ts_std(close, 300)",
    "channel_pos_15m": "(close - ts_min(low, 600)) / (ts_max(high, 600) - ts_min(low, 600)) - 0.5",
    "macd_hist_15m": "(ewma(close, 180) - ewma(close, 390) - ewma(ewma(close, 180) - ewma(close, 390), 135)) / ewm_std(ts_delta(close, 15), 390)",
    "rsi_like_5m": "ewma(ts_delta(close, 5), 70) / ewma(abs(ts_delta(close, 5)), 70)",
    "bar_revert_5m": "-ewma((2 * close - ts_max(high, 5) - ts_min(low, 5)) / (ts_max(high, 5) - ts_min(low, 5) + 0.1), 25)",
    "volume_momentum_5m": "ts_delta(close, 50) / ewm_std(ts_delta(close, 5), 100) * ts_mean(volume, 5) / ts_mean(volume, 300)",
    "price_volume_30m": "ts_corr(ts_delta(close, 30), ts_mean(volume, 30), 600)",
}
slippage = 0.1

run_alpha_evaluator(
    instrument_id=instrument_id,
    alphas=alphas,
    commission=commission,
    horizon=horizon,
    pool=alphas,
    slippage=slippage
)
