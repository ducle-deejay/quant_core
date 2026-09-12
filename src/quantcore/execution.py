"""quantcore.execution - Execution Researcher module.
``nautilus_trader`` is imported lazily, inside function bodies only.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

from core.artifacts import TargetSeries
from core.contracts import AccountLimits, CostModel, HarnessParams, Instrument
from core.data import BarFrame, CatalogClient
from core.registry import Registry

__all__ = [
    "ExecutionConfig",
    "ExecutionReport",
    "UrgencyInputs",
    "UrgencyReport",
    "SlippageReport",
    "backtest_execution",
    "execution_algorithms",
    "plan_orders",
    "slippage_report",
    "urgency_analysis",
]

#: Repository root (src/quantcore/execution.py -> parents[2]); default root
#: for :meth:`SlippageReport.save`.
REPO_ROOT = Path(__file__).resolve().parents[2]

#: Default save directory for the slippage summary (handoff artifact for
#: cost-model recalibration).
DEFAULT_RESEARCH_DIR = REPO_ROOT / "data" / "research"

#: Continuous-instrument lifetime used by the offline engine (the sim
#: instrument must outlive every researched bar/tick window).
_SIM_TS_INIT = "2018-01-01"
_SIM_EXPIRATION = "2100-01-01"

# --------------------------------------------------------------------------- #
# Extension registry
# --------------------------------------------------------------------------- #

#: Execution-algorithm slot: ``fn(gap_contracts: int, config:
#: ExecutionConfig) -> list[int]`` (signed chunks, positive = buy).
execution_algorithms = Registry("execution_algorithms")


def _marketable_limit_plan(gap_contracts: int, config: "ExecutionConfig") -> list[int]:
    """One order now (live bridge marketable-limit semantics)."""
    if gap_contracts == 0:
        return []
    return [gap_contracts]


def _twap_plan(gap_contracts: int, config: "ExecutionConfig") -> list[int]:
    """Even slices over ``slice_bars`` bars (remainder front-loaded)."""
    if gap_contracts == 0:
        return []
    n = max(1, int(config.slice_bars))
    base = abs(gap_contracts) // n
    rem = abs(gap_contracts) % n
    sign = 1 if gap_contracts > 0 else -1
    chunks = [sign * (base + (1 if i < rem else 0)) for i in range(n)]
    return [c for c in chunks if c != 0]


if "marketable_limit" not in execution_algorithms.names():
    execution_algorithms.register(
        "marketable_limit",
        _marketable_limit_plan,
        source="python",
        description="default one-order-now plan mirroring the live bridge"
        " marketable-limit semantics (the Rust engine has no execution-algorithm"
        " machinery)",
    )
if "twap" not in execution_algorithms.names():
    execution_algorithms.register(
        "twap",
        _twap_plan,
        source="python",
        description="even slices over slice_bars bars",
    )


def plan_orders(
    gap_contracts: int,
    config: "ExecutionConfig",
    algo: str = "twap",
) -> list[int]:
    """Plan and validate signed child quantities for one position gap.

    Dispatch resolves ``algo`` through the ``execution_algorithms``
    registry; the plan contract is
    ``fn(gap_contracts, config) -> list[int]`` (signed child quantities,
    positive = buy).

    Parameters
    ----------
    gap_contracts : int
        Signed position gap in contracts (target - current).
    config : ExecutionConfig
        Execution configuration handed to the algorithm.
    algo : str
        Registry key in ``execution_algorithms`` (default ``"twap"``).

    Returns
    -------
    list[int]
        Signed child quantities (sum == gap, same sign, no zeros).

    Raises
    ------
    TypeError
        Non-integer gap or wrong config type.
    ValueError
        Unknown algorithm or a plan violating the contract above.
    """
    if isinstance(gap_contracts, bool) or not isinstance(gap_contracts, int):
        raise TypeError("gap_contracts must be an integer")
    if not isinstance(config, ExecutionConfig):
        raise TypeError("config must be an ExecutionConfig")
    try:
        chunks = list(execution_algorithms.call(algo, gap_contracts, config))
    except KeyError as exc:
        raise ValueError(str(exc)) from None
    if any(isinstance(chunk, bool) or not isinstance(chunk, int) for chunk in chunks):
        raise ValueError(f"execution algorithm {algo!r} must return integer quantities")
    if any(chunk == 0 for chunk in chunks):
        raise ValueError(f"execution algorithm {algo!r} returned a zero quantity")
    if sum(chunks) != gap_contracts:
        raise ValueError(
            f"execution algorithm {algo!r} quantities sum to {sum(chunks)}, "
            f"expected {gap_contracts}"
        )
    if gap_contracts and any((chunk > 0) != (gap_contracts > 0) for chunk in chunks):
        raise ValueError(f"execution algorithm {algo!r} reversed the gap direction")
    return chunks


# --------------------------------------------------------------------------- #
# Configuration
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class ExecutionConfig:
    """Offline execution backtest configuration.

    Parameters
    ----------
    harness : HarnessParams
        Canonical harness parameters (carried for provenance).
    order_style : str
        ``"LO"`` (limit at the decision price) or ``"MAK"`` (market).
    cooldown_secs : float
        Minimum seconds between order submissions.
    min_gap_contracts : int
        Gaps smaller than this (absolute contracts) are not traded.
    slice_bars : int
        TWAP slice count in bar mode (bar-per-chunk cadence).
    twap_interval_secs : float
        Tick-mode time gate between TWAP chunks (so ``slice_bars`` means a
        time horizon, not ticks).
    limits : AccountLimits
        Account limits (capital funds the sim venue balance; max_contracts
        clamps applied targets).
    allow_l1 : bool
        Tick mode: False requires order-book depth10 (raises if missing);
        True explicitly runs tick-only L1 matching.
    """

    harness: HarnessParams = field(default_factory=HarnessParams)
    order_style: str = "LO"
    cooldown_secs: float = 5.0
    min_gap_contracts: int = 1
    slice_bars: int = 12
    twap_interval_secs: float = 60.0
    limits: AccountLimits = field(default_factory=AccountLimits)
    allow_l1: bool = False


@dataclass(frozen=True)
class ExecutionReport:
    """Offline execution backtest report (in-memory, never auto-saved).

    Parameters
    ----------
    n_target_changes : int
        Number of target timestamps in the input series.
    n_orders : int
        Submitted order count.
    n_fills : int
        (Partial-)fill event count with positive quantity.
    n_rejected : int
        Rejected order count.
    slippage_bps_mean : float
        Mean fill slippage in bp of the decision mid (0.0 with no fills).
    slippage_bps_median : float
        Median fill slippage in bp of the decision mid (0.0 with no fills).
    fills : pandas.DataFrame
        Columns ``ts_ns, side, price, qty, decision_mid, slippage_bps``.
    stats : dict
        Sim-account stats: ``n_positions``, ``realized_pnl_vnd``,
        ``account_balance``, ``total_pnl``; carries ``"error"`` when the
        analyzer step failed (best-effort, never silent).
    algo : str
        The resolved execution-algorithm registry key.
    provenance : dict
        algo + registry source, order style, engine class, data mode,
        instrument id and window.
    """

    n_target_changes: int
    n_orders: int
    n_fills: int
    n_rejected: int
    slippage_bps_mean: float
    slippage_bps_median: float
    fills: pd.DataFrame
    stats: dict
    algo: str
    provenance: dict


# --------------------------------------------------------------------------- #
# Nautilus assembly (lazy imports; nothing above this line imports Nautilus)
# --------------------------------------------------------------------------- #


def _precision_from_increment(value: float) -> int:
    """Decimal precision of a price increment (0.1 -> 1, 1.0 -> 0)."""
    text = format(value, "f").rstrip("0").rstrip(".")
    return len(text.split(".", 1)[1]) if "." in text else 0


def _nautilus_currency():
    """The VN market settlement currency (VND facts match the instrument
    definition JSON owned by core), registered for Nautilus."""
    from nautilus_trader.model.currencies import register_currency
    from nautilus_trader.model.enums import CurrencyType
    from nautilus_trader.model.objects import Currency

    currency = Currency("VND", 0, 704, "Vietnamese dong", CurrencyType.FIAT)
    register_currency(currency, overwrite=True)
    return currency


def _nautilus_instrument(instrument: Instrument):
    """Build the Nautilus futures instrument from a ``core.contracts
    .Instrument`` (symbol, venue, multiplier, tick_size). The simulated
    contract spans a lifetime covering every researched window."""
    from nautilus_trader.model.enums import AssetClass
    from nautilus_trader.model.identifiers import InstrumentId, Symbol, Venue
    from nautilus_trader.model.instruments import FuturesContract
    from nautilus_trader.model.objects import Price, Quantity

    currency = _nautilus_currency()
    instrument_id = InstrumentId(Symbol(instrument.symbol), Venue(instrument.venue))
    price_precision = _precision_from_increment(instrument.tick_size)
    activation_ns = pd.Timestamp(_SIM_TS_INIT, tz="UTC").value
    expiration_ns = pd.Timestamp(_SIM_EXPIRATION, tz="UTC").value
    underlying = instrument.symbol[:-3] if instrument.symbol.endswith("F1M") else instrument.symbol
    return FuturesContract(
        instrument_id=instrument_id,
        raw_symbol=instrument_id.symbol,
        asset_class=AssetClass.INDEX,
        exchange=None,
        currency=currency,
        price_precision=price_precision,
        price_increment=Price(instrument.tick_size, price_precision),
        multiplier=Quantity(instrument.multiplier, 0),
        lot_size=Quantity(1, 0),
        underlying=underlying,
        activation_ns=activation_ns,
        expiration_ns=expiration_ns,
        ts_event=activation_ns,
        ts_init=activation_ns,
    )


def _bars_to_nautilus(bars: BarFrame, instrument: Instrument):
    """Convert a ``BarFrame`` window into Nautilus ``Bar`` objects (real
    recorded bars; no synthesis)."""
    from nautilus_trader.model.data import Bar, BarType
    from nautilus_trader.model.objects import Price, Quantity

    bar_type = BarType.from_str(bars.bar_type)
    expected_id = f"{instrument.symbol}.{instrument.venue}"
    if str(bar_type.instrument_id) != expected_id:
        raise ValueError(
            f"bar_type {bars.bar_type!r} carries instrument"
            f" {str(bar_type.instrument_id)!r}, expected {expected_id!r} from"
            " the target instrument; bars and targets must describe the same"
            " instrument"
        )
    precision = _precision_from_increment(instrument.tick_size)
    out = []
    for i, ts in enumerate(bars.ts):
        ts_ns = int(ts.value)
        out.append(
            Bar(
                bar_type,
                Price(float(bars.open[i]), precision),
                Price(float(bars.high[i]), precision),
                Price(float(bars.low[i]), precision),
                Price(float(bars.close[i]), precision),
                Quantity(float(bars.volume[i]), 0),
                ts_ns,
                ts_ns,
            )
        )
    return bar_type, out


def _make_precomputed_portfolio(targets: TargetSeries):
    """Portfolio implementing ``core.contracts.Portfolio`` over a precomputed
    ``TargetSeries``: ``compute_target`` latches the latest target whose
    timestamp is at/before the decision timestamp (the target series is the
    frozen research decision; the strategy's own gates apply on top)."""
    from core import TargetPosition

    pending = sorted(
        (int(pd.Timestamp(t).value), int(q))
        for t, q in zip(targets.ts, targets.target_contracts)
    )

    class _PrecomputedPortfolio:
        """Returns the precomputed ``TargetPosition`` at each timestamp."""

        def __init__(self) -> None:
            self._pending = list(pending)
            self._current = 0

        def compute_target(self, bars: dict[str, list[float]], ts) -> TargetPosition:
            while self._pending and self._pending[0][0] <= int(pd.Timestamp(ts).value):
                self._current = self._pending.pop(0)[1]
            return TargetPosition(
                ts=ts,
                target_contracts=self._current,
                z_target=0.0,
                reason="precomputed",
                components={},
            )

    return _PrecomputedPortfolio()


# --------------------------------------------------------------------------- #
# Entry points
# --------------------------------------------------------------------------- #


def backtest_execution(
    targets: TargetSeries,
    bars: BarFrame,
    config: ExecutionConfig | None = None,
    algo: str = "marketable_limit",
    catalog: CatalogClient | None = None,
    strategy_factory=None,
) -> ExecutionReport:
    """Offline execution backtest on the Nautilus engine (bar mode).

    Runs the REAL :class:`strategy.TargetPositionStrategy` (the same class
    the live runner uses) against a precomputed portfolio: the default
    ``strategy_factory`` wires a ``_PrecomputedPortfolio`` - whose
    ``compute_target`` returns the ``targets`` value at each timestamp -
    into a fresh strategy. Orders, fills and slippage are read back from
    the engine cache after the run (no mirror strategy).

    Parameters
    ----------
    targets : TargetSeries
        Target contract series (``ts`` + ``target_contracts``).
    bars : BarFrame
        The bar window driving the simulation (real recorded bars).
    config : ExecutionConfig | None
        Defaults to ``ExecutionConfig()``.
    algo : str
        Registry key in ``execution_algorithms`` (validated; the default
        ``"marketable_limit"`` mirrors the live one-order-now semantics).
    catalog : CatalogClient | None
        Must be ``None``: tick mode died with the deleted target-follower
        mirror (the real strategy is bar-driven); a value raises
        ``ValueError`` instead of silently ignoring it.
    strategy_factory : callable | None
        ``fn(portfolio) -> nautilus Strategy``; ``None`` builds the
        default :class:`strategy.TargetPositionStrategy` wired to the
        ``_PrecomputedPortfolio``.

    Returns
    -------
    ExecutionReport
        Counts, fills DataFrame, slippage stats, sim-account stats,
        provenance.

    Raises
    ------
    ValueError
        Empty targets, unknown algorithm, ``catalog`` given (tick mode
        removed), or bar_type/instrument mismatch.

    Notes
    -----
    Decision-mid convention (unchanged): the strategy's reference price -
    the limit price it selected (the last bar close for LO); market orders
    fall back to the fill price. The backtest strategy runs with
    ``warmup_bars=1`` so the precomputed targets act from the first bar.
    """
    from nautilus_trader.backtest.engine import BacktestEngine, BacktestEngineConfig
    from nautilus_trader.common.config import LoggingConfig
    from nautilus_trader.model.enums import (
        AccountType,
        BookType,
        OmsType,
        OrderSide,
        OrderType,
    )
    from nautilus_trader.model.events import OrderFilled, OrderRejected, OrderSubmitted
    from nautilus_trader.model.objects import Money

    from strategy.target_position import TargetPositionConfig, TargetPositionStrategy

    cfg = config or ExecutionConfig()
    try:
        execution_algorithms.get(algo)
    except KeyError as exc:
        raise ValueError(str(exc)) from None
    if len(targets.ts) == 0:
        raise ValueError("targets must be a non-empty TargetSeries")
    if catalog is not None:
        raise ValueError(
            "tick mode (catalog=...) was removed together with the"
            " target-follower mirror strategy: backtest_execution runs the"
            " real bar-driven TargetPositionStrategy, so bar mode is the"
            " only executable mode"
        )

    instrument = targets.instrument
    nautilus_instrument = _nautilus_instrument(instrument)
    currency = nautilus_instrument.quote_currency
    bar_type, data_objects = _bars_to_nautilus(bars, instrument)
    if not data_objects:
        raise ValueError(
            f"no bars in the provided BarFrame window [{bars.ts.min()}, {bars.ts.max()}]"
        )

    portfolio = _make_precomputed_portfolio(targets)
    if strategy_factory is None:
        def strategy_factory(portfolio):  # noqa: E306
            return TargetPositionStrategy(
                TargetPositionConfig(
                    instrument_id=str(nautilus_instrument.id),
                    bar_type=str(bar_type),
                    order_style=cfg.order_style,
                    cooldown_secs=cfg.cooldown_secs,
                    min_gap_contracts=cfg.min_gap_contracts,
                    warmup_bars=1,  # targets are precomputed; act from bar 1
                ),
                portfolio,
            )

    n_target_changes = len(
        {(int(pd.Timestamp(t).value), int(q)) for t, q in zip(targets.ts, targets.target_contracts)}
    )

    engine = BacktestEngine(BacktestEngineConfig(logging=LoggingConfig(log_level="ERROR")))
    try:
        engine.add_venue(
            venue=nautilus_instrument.id.venue,
            # NETTING matches the live entrade OMS: the strategy reads its
            # single per-strategy net position from the cache.
            oms_type=OmsType.NETTING,
            account_type=AccountType.MARGIN,
            starting_balances=[Money(cfg.limits.capital_vnd, currency)],
            base_currency=currency,
            book_type=BookType.L1_MBP,
        )
        engine.add_instrument(nautilus_instrument)
        engine.add_data(data_objects, sort=True)
        strategy = strategy_factory(portfolio)
        engine.add_strategy(strategy)
        engine.run()

        # Read the report back from the engine cache (the real strategy does
        # not record fills itself): decision_mid = the order's limit price
        # (the strategy's reference price), fill price/qty from the events.
        fills: list[dict] = []
        n_orders = 0
        n_rejected = 0
        avg_entry: float | None = None
        position = 0
        realized_pnl_vnd = 0.0
        multiplier = float(nautilus_instrument.multiplier.as_double())
        for order in engine.cache.orders():
            for event in order.events:
                if isinstance(event, OrderSubmitted):
                    n_orders += 1
                elif isinstance(event, OrderRejected):
                    n_rejected += 1
                elif isinstance(event, OrderFilled):
                    side = 1 if event.order_side == OrderSide.BUY else -1
                    qty = int(event.last_qty.as_double())
                    price = float(event.last_px.as_double())
                    decision_mid = (
                        float(order.price.as_double())
                        if order.order_type == OrderType.LIMIT and order.price is not None
                        else price
                    )
                    fills.append(
                        {
                            "ts_ns": int(event.ts_event),
                            "side": side,
                            "price": price,
                            "qty": qty,
                            "decision_mid": decision_mid,
                            "slippage_bps": (price - decision_mid)
                            * side
                            * 10_000.0
                            / decision_mid,
                        }
                    )
                    # Realized PnL (VND, instrument multiplier) via the
                    # avg-entry ledger so total_pnl is honest (sim account
                    # balances do not move with zero fees).
                    old_pos = position
                    position += side * qty
                    if old_pos == 0:
                        avg_entry = price
                    elif (old_pos > 0) == (side * qty > 0):
                        avg_entry = (old_pos * (avg_entry or 0.0) + side * qty * price) / position
                    else:
                        closing = min(abs(side * qty), abs(old_pos))
                        direction = 1 if old_pos > 0 else -1
                        realized_pnl_vnd += (
                            closing * (price - (avg_entry or 0.0)) * multiplier * direction
                        )
                        if position == 0:
                            avg_entry = None
                        elif position * old_pos < 0:
                            avg_entry = price
        fills.sort(key=lambda f: f["ts_ns"])
        slippage = [f["slippage_bps"] for f in fills]

        stats: dict = {}
        try:
            accounts = engine.cache.accounts()
            balance = (
                float(sum(m.as_double() for m in accounts[0].balances_total().values()))
                if accounts
                else 0.0
            )
            stats = {
                "n_positions": len(engine.cache.positions()),
                "realized_pnl_vnd": realized_pnl_vnd,
                "account_balance": balance,
                "total_pnl": realized_pnl_vnd,
            }
        except Exception as exc:  # noqa: BLE001 - analyzer is best-effort, never silent
            stats = {"error": f"{type(exc).__name__}: {exc}"}

        fills_df = pd.DataFrame(
            fills,
            columns=["ts_ns", "side", "price", "qty", "decision_mid", "slippage_bps"],
        )
        return ExecutionReport(
            n_target_changes=n_target_changes,
            n_orders=n_orders,
            n_fills=len(fills),
            n_rejected=n_rejected,
            slippage_bps_mean=float(np.mean(slippage)) if slippage else 0.0,
            slippage_bps_median=float(np.median(slippage)) if slippage else 0.0,
            fills=fills_df,
            stats=stats,
            algo=algo,
            provenance={
                "algo": algo,
                "algo_source": execution_algorithms.get(algo).source,
                "order_style": cfg.order_style,
                "engine": "nautilus_trader.backtest.engine.BacktestEngine",
                "data_mode": "bar",
                "strategy": type(strategy).__name__,
                "instrument_id": str(nautilus_instrument.id),
                "window_start": targets.ts.min().isoformat(),
                "window_end": targets.ts.max().isoformat(),
                "bars": len(bars.ts) if bars is not None else 0,
            },
        )
    finally:
        engine.dispose()


# --------------------------------------------------------------------------- #
# Urgency math
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, kw_only=True)
class UrgencyInputs:
    """Trade-scheduling urgency inputs (keyword-only).

    Parameters
    ----------
    gap_contracts : int
        Signed position gap magnitude context; costs are computed on this
        many contracts (non-negative).
    half_spread_bps : float
        Half the current spread, in basis points of price (>= 0).
    impact_bps : float
        Expected market impact, in basis points of price (>= 0).
    alpha_decay_per_bar : float
        Alpha decay per bar waited, in basis points of price (>= 0).
    value_of_1bp : float
        Money value of 1 bp of price for the whole gap, in the account
        currency (>= 0).
    hold_bars : float
        Expected holding horizon in bars for the waiting cost (> 0).
    """

    gap_contracts: int
    half_spread_bps: float
    impact_bps: float
    alpha_decay_per_bar: float
    value_of_1bp: float
    hold_bars: float = 1.0


@dataclass(frozen=True)
class UrgencyReport:
    """Urgency verdict for one gap.

    Parameters
    ----------
    cost_of_waiting : float
        gap * alpha_decay_per_bar * value_of_1bp * hold_bars.
    cost_of_acting : float
        gap * (half_spread_bps + impact_bps) * value_of_1bp.
    verdict : str
        ``"act-now"`` when waiting costs more than acting, else
        ``"slice"``.
    """

    cost_of_waiting: float
    cost_of_acting: float
    verdict: str


def urgency_analysis(inputs: UrgencyInputs) -> UrgencyReport:
    """Trade-scheduling urgency math.

    cost_of_waiting = gap * alpha_decay_per_bar * value_of_1bp * hold_bars;
    cost_of_acting = gap * (half_spread_bps + impact_bps) * value_of_1bp;
    verdict ``"act-now"`` when waiting costs more than acting, else
    ``"slice"``. Units must be consistent across inputs (bp-based costs,
    1bp value in the same currency unit).

    Parameters
    ----------
    inputs : UrgencyInputs
        The non-negative cost inputs (see the dataclass docstring).

    Returns
    -------
    UrgencyReport
        Both costs and the verdict.

    Raises
    ------
    ValueError
        Any negative input or non-positive ``hold_bars``.
    """
    if inputs.gap_contracts < 0:
        raise ValueError("gap_contracts must be non-negative")
    if inputs.value_of_1bp < 0:
        raise ValueError("value_of_1bp must be non-negative")
    if inputs.alpha_decay_per_bar < 0:
        raise ValueError("alpha_decay_per_bar must be non-negative")
    if inputs.half_spread_bps < 0:
        raise ValueError("half_spread_bps must be non-negative")
    if inputs.impact_bps < 0:
        raise ValueError("impact_bps must be non-negative")
    if inputs.hold_bars <= 0:
        raise ValueError("hold_bars must be positive")
    cost_of_waiting = (
        inputs.gap_contracts * inputs.alpha_decay_per_bar * inputs.value_of_1bp * inputs.hold_bars
    )
    cost_of_acting = inputs.gap_contracts * (inputs.half_spread_bps + inputs.impact_bps) * inputs.value_of_1bp
    return UrgencyReport(
        cost_of_waiting=cost_of_waiting,
        cost_of_acting=cost_of_acting,
        verdict="act-now" if cost_of_waiting > cost_of_acting else "slice",
    )


# --------------------------------------------------------------------------- #
# Slippage report
# --------------------------------------------------------------------------- #


def _hour_of(ts) -> str | None:
    """Normalize a fill timestamp to the VN session hour (Asia/Ho_Chi_Minh):
    naive strings are read as Hanoi local, ints as UTC (backtest fills carry
    ts_ns in UTC) - ONE convention for the by_session_hour axis (mixing the
    two timezones would mix sessions)."""
    try:
        if isinstance(ts, str):
            if len(ts) < 13:
                return None
            t = pd.Timestamp(ts)
            if t.tzinfo is None:
                t = t.tz_localize("Asia/Ho_Chi_Minh")
            return str(t.tz_convert("Asia/Ho_Chi_Minh").hour).zfill(2)
        if isinstance(ts, (int, float)):
            t = pd.Timestamp(int(ts), unit="ns", tz="UTC")
            return str(t.tz_convert("Asia/Ho_Chi_Minh").hour).zfill(2)
    except Exception:  # noqa: BLE001
        return None
    return None


def _mean_or_zero(values: list[float]) -> float:
    return float(np.mean(values)) if values else 0.0


@dataclass(frozen=True)
class SlippageReport:
    """Weekly implementation-shortfall review.

    Parameters
    ----------
    generated : str
        ISO date of the report.
    n_records : int
        Usable fill records (price + decision_mid + side present).
    mean_shortfall_bps : float
        Mean shortfall in bp of the decision mid.
    median_shortfall_bps : float
        Median shortfall in bp of the decision mid.
    cost_model_bps : float
        The cost model the excess is measured against.
    excess_bps : float
        ``mean_shortfall_bps - cost_model_bps``.
    by_session_hour : dict
        Mean shortfall per VN session hour (``"HH"`` keys, Hanoi local).
    size_buckets : dict
        Mean shortfall per size bucket (``"small_<=3"`` / ``"large_>3"``
        contracts).
    vol_regime : dict
        Mean shortfall per caller-provided ``vol_regime`` label.
    """

    generated: str
    n_records: int
    mean_shortfall_bps: float
    median_shortfall_bps: float
    cost_model_bps: float
    excess_bps: float
    by_session_hour: dict
    size_buckets: dict
    vol_regime: dict

    def save(self, root: Path | None = None) -> Path:
        """Persist the summary as the weekly handoff artifact (consumed by
        cost-model recalibration).

        Parameters
        ----------
        root : Path | None
            Target directory; ``None`` saves to ``<repo>/data/research``.

        Returns
        -------
        pathlib.Path
            The written JSON path (``slippage_<generated>.json``).
        """
        directory = Path(root) if root is not None else DEFAULT_RESEARCH_DIR
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"slippage_{self.generated}.json"
        payload = {
            "generated": self.generated,
            "n_records": self.n_records,
            "mean_shortfall_bps": self.mean_shortfall_bps,
            "median_shortfall_bps": self.median_shortfall_bps,
            "cost_model_bps": self.cost_model_bps,
            "excess_bps": self.excess_bps,
            "by_session_hour": self.by_session_hour,
            "size_buckets": self.size_buckets,
            "vol_regime": self.vol_regime,
        }
        path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n")
        return path


def slippage_report(
    fills: pd.DataFrame | None = None,
    session_dir: Path | None = None,
) -> SlippageReport:
    """Weekly implementation-shortfall review (feedback execution -> alpha).

    Input: explicit fills (DataFrame with ``price``, ``decision_mid``,
    ``side`` and optional ``qty``, ``vol_regime``, ``ts``/``ts_ns``
    columns) or a session dir. Session dirs are read for ``fills.jsonl``
    first; a bridge-style ``decisions.jsonl`` alone raises an actionable
    error - the bridge logs decisions only, fill prices live in the
    streaming catalog. Shortfall = (fill price - decision mid) * side in bp
    of the reference price; decomposed by session hour (Hanoi local), size
    bucket (fill quantity) and vol regime (caller-provided per fill);
    excess vs the cost model (the documented scalar fraction x 10,000 =
    2.29 bp). Saving is the caller's explicit ``SlippageReport.save()``.

    Parameters
    ----------
    fills : pandas.DataFrame | None
        Fill records (see above).
    session_dir : Path | None
        Directory holding ``fills.jsonl`` (or ``decisions.jsonl``, which
        raises).

    Returns
    -------
    SlippageReport
        The in-memory report.

    Raises
    ------
    ValueError
        No input given, an unusable session dir, or no usable fill records.
    """
    if fills is None and session_dir is None:
        raise ValueError("provide fills or session_dir")
    cost_model_bps = CostModel().cost_per_side_frac * 10_000.0

    records: list[dict] = []
    if session_dir is not None:
        fills_path = Path(session_dir) / "fills.jsonl"
        dec_path = Path(session_dir) / "decisions.jsonl"
        if fills_path.exists():
            fills = pd.DataFrame(
                [
                    json.loads(line)
                    for line in fills_path.read_text().splitlines()
                    if line.strip()
                ]
            )
        elif dec_path.exists():
            raise ValueError(
                f"{session_dir} has a decisions.jsonl but no fills.jsonl: the"
                " bridge decision log carries no fill prices (it logs close/"
                " target/action only). Pass fills= explicitly or point"
                " session_dir at an artifact that includes fills.jsonl."
            )
        else:
            raise FileNotFoundError(
                f"neither fills.jsonl nor decisions.jsonl found in {session_dir}"
                " (dir missing or no session artifacts)"
            )
    if fills is not None and not fills.empty:
        for e in fills.to_dict("records"):
            records.append(e)

    shortfalls = []
    for r in records:
        mid = r.get("decision_mid")
        price = r.get("price")
        side = r.get("side", 1)
        ts = r.get("ts", r.get("ts_ns"))
        if mid is None or price is None or mid == 0:
            continue
        shortfalls.append(
            {
                "bps": (float(price) - float(mid)) * float(side) * 10_000.0 / float(mid),
                "ts": ts,
                "qty": float(r.get("qty", 1.0)),
                "vol_regime": r.get("vol_regime"),
            }
        )

    if not shortfalls:
        raise ValueError("no usable fill records (need price, decision_mid, side)")

    by_hour: dict[str, list[float]] = {}
    by_size: dict[str, list[float]] = {"small_<=3": [], "large_>3": []}
    by_regime: dict[str, list[float]] = {}
    for s in shortfalls:
        hour = _hour_of(s["ts"])
        by_hour.setdefault(hour or "unknown", []).append(s["bps"])
        bucket = "small_<=3" if s["qty"] <= 3 else "large_>3"
        by_size[bucket].append(s["bps"])
        if s["vol_regime"] is not None:
            by_regime.setdefault(str(s["vol_regime"]), []).append(s["bps"])

    mean_bps = float(np.mean([s["bps"] for s in shortfalls]))
    return SlippageReport(
        generated=date.today().isoformat(),
        n_records=len(shortfalls),
        mean_shortfall_bps=mean_bps,
        median_shortfall_bps=float(np.median([s["bps"] for s in shortfalls])),
        cost_model_bps=cost_model_bps,
        excess_bps=mean_bps - cost_model_bps,
        by_session_hour={k: float(np.mean(v)) for k, v in sorted(by_hour.items())},
        size_buckets={k: _mean_or_zero(v) for k, v in by_size.items()},
        vol_regime={k: float(np.mean(v)) for k, v in sorted(by_regime.items())},
    )
