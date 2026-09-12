"""Single score -> contracts implementation (one formula, one module)."""

from __future__ import annotations

import math

from .contracts import AccountLimits
from .instruments import Instrument

__all__ = [
    "apply_hysteresis",
    "hysteresis_band_contracts",
    "max_contracts_at",
    "to_contracts",
]


def max_contracts_at(
    price: float, instrument: Instrument, limits: AccountLimits
) -> int:
    """Compute the margin-feasible maximum signed-contract magnitude at a price.

    Parameters
    ----------
    price : float
        Reference price in VND per index point (e.g. last close).
    instrument : Instrument
        Static instrument data; supplies ``multiplier`` (VND per index point).
    limits : AccountLimits
        Account limits; supplies ``capital_vnd``, ``safety_factor`` and
        ``margin_rate`` (deposit ratio, fraction).

    Returns
    -------
    int
        ``floor(capital_vnd * safety_factor /
        (margin_rate * price * multiplier))``. Not clamped by
        ``max_contracts``; callers clip the rounded target themselves.
    """
    return math.floor(
        limits.capital_vnd
        * limits.safety_factor
        / (limits.margin_rate * price * instrument.multiplier)
    )


def to_contracts(
    z: float,
    price: float,
    cap: float,
    instrument: Instrument,
    limits: AccountLimits,
) -> int:
    """Convert one z-score target into a signed contract count.

    Parameters
    ----------
    z : float
        Composite score in z-units.
    price : float
        Reference price in VND per index point.
    cap : float
        z-value mapped to the maximum position; must be positive.
    instrument : Instrument
        Static instrument data (multiplier).
    limits : AccountLimits
        Account limits (sizing and hard ``max_contracts`` clip).

    Returns
    -------
    int
        ``round(z / cap * max_contracts_at(...))`` clipped to
        ``+/-limits.max_contracts``. Returns 0 for non-finite ``z`` and for
        non-finite or non-positive ``price``. Python ``round`` is
        half-to-even, which keeps the conversion deterministic.
    """
    if not math.isfinite(z):
        return 0
    if not math.isfinite(price) or price <= 0.0:
        return 0
    raw = round(z / cap * max_contracts_at(price, instrument, limits))
    return max(-limits.max_contracts, min(limits.max_contracts, raw))


def hysteresis_band_contracts(
    band: float,
    cap: float,
    price: float,
    instrument: Instrument,
    limits: AccountLimits,
) -> int:
    """Convert the z-units no-trade band into a contract-count band.

    Parameters
    ----------
    band : float
        No-trade band width in z-units (e.g. ``HarnessParams.band``).
    cap : float
        z-value mapped to the maximum position; must be positive.
    price : float
        Reference price in VND per index point.
    instrument : Instrument
        Static instrument data (multiplier).
    limits : AccountLimits
        Account limits (sizing inputs).

    Returns
    -------
    int
        ``max(1, round(band / cap * max_contracts_at(...)))`` — at least one
        contract, so a flat book can always react to a signal.
    """
    return max(1, round(band / cap * max_contracts_at(price, instrument, limits)))


def apply_hysteresis(raw: int, prev: int, band_contracts: int) -> int:
    """Hold the previous position while the change stays inside the band.

    Caller contract: live callers stay stateless and call
    :func:`to_contracts` only; research backtest loops carry a ``prev``
    contracts variable and call this between rounds.

    Parameters
    ----------
    raw : int
        Newly converted target in contracts.
    prev : int
        Previous (held) target in contracts.
    band_contracts : int
        Dead-zone width in contracts (from :func:`hysteresis_band_contracts`).

    Returns
    -------
    int
        ``prev`` when ``abs(raw - prev) <= band_contracts``, else ``raw``.
    """
    return prev if abs(raw - prev) <= band_contracts else raw
