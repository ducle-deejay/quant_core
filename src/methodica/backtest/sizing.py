import numpy as np

from methodica.backtest.forecast import BPS


def optimal_position(refined_forecast, predicted_volatility, risk_aversion):
    return (refined_forecast / BPS) / (2 * risk_aversion * predicted_volatility ** 2)


def target_contracts(position, close, book_size, multiplier, margin_init):
    max_contracts = np.floor(book_size / (close * multiplier * margin_init))
    return (
        np.trunc(position * book_size / (close * multiplier))
        .clip(-max_contracts, max_contracts)
        .fillna(0)
        + 0.0
    )
