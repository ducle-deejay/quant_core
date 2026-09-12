"""Shared signal-processing helpers — one implementation for research AND live.
Every function here is PARITY-LOCKED (see per-function notes).
"""

from __future__ import annotations

import math


def sanitize_scores(series: list[float]) -> list[float]:
    """Forward-fill non-finite score values, mirroring the engine's
    ``sanitize_scores``: leading non-finite values take the first finite
    value, interior ones carry the last finite value forward, and an
    all-non-finite series maps to zeros.

    Parity-locked: semantics must match the Rust engine; do not change
    without re-recording the goldens."""
    first = next((v for v in series if math.isfinite(v)), None)
    if first is None:
        return [0.0] * len(series)
    last = first
    out: list[float] = []
    for v in series:
        if math.isfinite(v):
            last = v
        out.append(last)
    return out


def close_returns(close: list[float]) -> list[float]:
    """Per-bar simple close returns: ``r[0] = 0.0``, ``r[t] = c[t]/c[t-1] - 1``.

    Parity-locked: do not change without re-recording the goldens."""
    r = [0.0] * len(close)
    for t in range(1, len(close)):
        r[t] = close[t] / close[t - 1] - 1.0
    return r


def rolling_vol(close: list[float], window: int, bars_per_day: int) -> list[float]:
    """Annualised rolling realised vol of simple close returns.

    ``vol_est[t] = sample_std(r[t-window+1 .. t]) * sqrt(bars_per_day)`` with
    ``r[0] = 0.0`` and ``r[t] = close[t]/close[t-1] - 1``. Trailing windows
    with fewer than two samples yield 0.0 (the engine's ``ts_std`` yields NaN
    there; 0.0 is used so the vol-target zero guard produces a flat output
    and the series stays finite for ``vol_target_py``).

    Parity-locked: semantics must match the engine's ``ts_std`` convention
    (0.0 for windows with fewer than two samples); do not change without
    re-recording the goldens."""
    rets = close_returns(close)
    scale = math.sqrt(bars_per_day)
    out: list[float] = []
    for t in range(len(rets)):
        win = rets[max(0, t - window + 1) : t + 1]
        if len(win) < 2:
            out.append(0.0)
            continue
        mean = sum(win) / len(win)
        var = sum((v - mean) * (v - mean) for v in win) / (len(win) - 1)  # ddof=1
        out.append(math.sqrt(var) * scale)
    return out
