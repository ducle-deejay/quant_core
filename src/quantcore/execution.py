"""quantcore.execution - Execution Researcher module.
``nautilus_trader`` is imported lazily, inside function bodies only.
"""

from __future__ import annotations

import json
from collections import deque
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


def _ticks_to_nautilus(
    ticks: pd.DataFrame, instrument_id_str: str, price_precision: int
):
    """Convert a decoded tick frame (columns ``ts, price, size,
    aggressor_side``) into Nautilus ``TradeTick`` objects. Trade ids are
    sequential positions in the frame (bookkeeping only - the prices/sizes
    are the recorded data). ``price_precision`` is the instrument's price
    precision; the matching engine rejects ticks at any other precision."""
    from nautilus_trader.model.data import TradeTick
    from nautilus_trader.model.enums import AggressorSide
    from nautilus_trader.model.identifiers import InstrumentId, TradeId
    from nautilus_trader.model.objects import Price, Quantity

    instrument_id = InstrumentId.from_str(instrument_id_str)
    precision = price_precision  # instrument price precision (engine-checked)
    out = []
    aggressor_map = {
        "1": AggressorSide.BUYER,
        "b": AggressorSide.BUYER,
        "buy": AggressorSide.BUYER,
        "buyer": AggressorSide.BUYER,
        "-1": AggressorSide.SELLER,
        "s": AggressorSide.SELLER,
        "sell": AggressorSide.SELLER,
        "seller": AggressorSide.SELLER,
    }
    for i, row in enumerate(ticks.itertuples(index=False)):
        ts_ns = int(pd.Timestamp(row.ts).value)
        aggressor = aggressor_map.get(str(row.aggressor_side).lower(), AggressorSide.NO_AGGRESSOR)
        out.append(
            TradeTick(
                instrument_id,
                Price(float(row.price), precision),
                Quantity(float(row.size), 0),
                aggressor,
                TradeId(str(i)),
                ts_ns,
                ts_ns,
            )
        )
    return out


def _depth_to_nautilus(
    depth: pd.DataFrame, instrument_id_str: str, price_precision: int
):
    """Convert a decoded depth frame (long format ``ts, level, side, price,
    size``, levels 0-9) into Nautilus ``OrderBookDepth10`` objects. Levels
    missing at a timestamp are padded with zero-size orders at the deepest
    recorded price (no trade impact); counts are 1 per present level.
    ``price_precision`` is the instrument's price precision; the matching
    engine rejects depth at any other precision."""
    from nautilus_trader.model.data import BookOrder, OrderBookDepth10
    from nautilus_trader.model.enums import OrderSide
    from nautilus_trader.model.identifiers import InstrumentId
    from nautilus_trader.model.objects import Price, Quantity

    instrument_id = InstrumentId.from_str(instrument_id_str)
    precision = price_precision
    grouped: dict[int, dict[int, tuple[int, float, float]]] = {}
    for row in depth.itertuples(index=False):
        ts_ns = int(pd.Timestamp(row.ts).value)
        side = 1 if str(row.side).lower() in ("buy", "bid", "1", "b") else -1
        grouped.setdefault(ts_ns, {})[int(row.level)] = (side, float(row.price), float(row.size))

    out = []
    order_id = 1
    for ts_ns in sorted(grouped):
        levels = grouped[ts_ns]
        bids: list = []
        asks: list = []
        for side, book in ((1, bids), (-1, asks)):
            side_levels = {lvl: v for lvl, v in levels.items() if v[0] == side}
            pad_price = side_levels[max(side_levels)][1] if side_levels else 0.0
            for level in range(10):
                entry = side_levels.get(level)
                if entry is None:
                    book.append(
                        BookOrder(
                            OrderSide.BUY if side == 1 else OrderSide.SELL,
                            Price(pad_price, precision),
                            Quantity(0.0, 0),
                            order_id,
                        )
                    )
                else:
                    _, price, size = entry
                    book.append(
                        BookOrder(
                            OrderSide.BUY if side == 1 else OrderSide.SELL,
                            Price(price, precision),
                            Quantity(size, 0),
                            order_id,
                        )
                    )
                order_id += 1
        out.append(
            OrderBookDepth10(
                instrument_id,
                bids,
                asks,
                [1] * 10,
                [1] * 10,
                0,
                0,
                ts_ns,
                ts_ns,
            )
        )
    return out


def _make_target_follower_strategy():
    """Build the target-following strategy class (Nautilus imported here,
    at backtest assembly time, never at module import).

    Mirrors the live bridge semantics: at most one working order, min-gap
    and cooldown skips, target changes only. ``mode="bar"`` drives from
    1-minute bars (decision price = bar close); ``mode="tick"`` drives from
    trade ticks (decision price = last trade tick), so fills happen against
    the real book. Order style per config: limit at the decision price (LO)
    or market (MAK). Decision mid for slippage = the decision price.
    """
    from nautilus_trader.model.enums import OrderSide
    from nautilus_trader.model.objects import Price
    from nautilus_trader.trading.strategy import Strategy

    class TargetFollowerStrategy(Strategy):
        """Target-following strategy for the offline engine (two data
        modes). See :func:`_make_target_follower_strategy`."""

        def __init__(
            self,
            config: ExecutionConfig,
            targets: dict[int, int],
            algo: str,
            instrument,
            mode: str,
            bar_type=None,
        ) -> None:
            super().__init__()
            self._cfg = config
            # Sorted pending targets: applied on the first bar/tick at/after
            # each ts.
            self._pending: list[tuple[int, int]] = sorted(targets.items())
            self._algo = algo
            self._instrument = instrument
            self._instrument_id = instrument.id
            self._multiplier = float(instrument.multiplier.as_double())
            self._expiration_ns = int(getattr(instrument, "expiration_ns", 0))
            self._bar_type = bar_type
            self._mode = mode
            self._position = 0
            self._target = 0
            self._queue: deque[int] = deque()
            self._last_submit_ns: int | None = None
            self._last_queue_submit_ns: int | None = None
            self._working_coid: str | None = None
            self._avg_entry: float | None = None
            self._realized_pnl_vnd: float = 0.0
            self.fills: list[dict] = []
            self.order_events: list[dict] = []

        def on_start(self) -> None:
            if self._mode == "tick":
                self.subscribe_trade_ticks(self._instrument_id)
            else:
                self.subscribe_bars(self._bar_type)

        def on_bar(self, bar) -> None:
            self._on_price(int(bar.ts_event), float(bar.close.as_double()))

        def on_trade_tick(self, tick) -> None:
            self._on_price(int(tick.ts_event), float(tick.price.as_double()))

        def _on_price(self, ts_ns: int, price: float) -> None:
            # Session-end awareness: after the contract expires, STOP
            # submitting - no retry loop against an expired instrument
            # (fills before expiry are still recorded).
            if ts_ns > self._expiration_ns:
                return
            while self._pending and self._pending[0][0] <= ts_ns:
                self._target = max(
                    -self._cfg.limits.max_contracts,
                    min(self._cfg.limits.max_contracts, self._pending.pop(0)[1]),
                )

            # Decision mid = the reference price (bar close / last trade
            # tick) - the live bridge convention ("reference price is the
            # last trade price"). Book-mid refinement (queue/adverse-
            # selection aware) is deferred.
            decision_mid = price

            # Submit queued chunks: one per bar in bar mode; in tick mode
            # time-gated by twap_interval_secs so "slice_bars" means a time
            # horizon, not ~0.1s of ticks.
            if self._queue and self._working_coid is None:
                due = True
                if self._mode == "tick" and self._last_queue_submit_ns is not None:
                    due = (
                        ts_ns - self._last_queue_submit_ns
                    ) / 1e9 >= self._cfg.twap_interval_secs
                if due:
                    self._submit(self._queue.popleft(), ts_ns, decision_mid)
                    self._last_queue_submit_ns = ts_ns

            gap = self._target - self._position
            if gap == 0 or self._working_coid is not None:
                return
            if abs(gap) < self._cfg.min_gap_contracts:
                return
            if self._last_submit_ns is not None:
                elapsed = (ts_ns - self._last_submit_ns) / 1e9
                if elapsed < self._cfg.cooldown_secs:
                    return

            plan = plan_orders(gap, self._cfg, self._algo)
            if not plan:
                return
            self._queue = deque(plan[1:])
            self._submit(plan[0], ts_ns, decision_mid)

        def _submit(self, qty: int, ts_ns: int, decision_mid: float) -> None:
            if qty == 0:
                return
            side = OrderSide.BUY if qty > 0 else OrderSide.SELL
            from nautilus_trader.model.objects import Quantity

            quantity = Quantity(abs(qty), 0)
            if self._cfg.order_style == "MAK":
                order = self.order_factory.market(self._instrument_id, side, quantity)
            else:
                price = (
                    self._instrument.make_price(decision_mid)
                    if self._instrument is not None
                    else Price(decision_mid, 1)
                )
                order = self.order_factory.limit(
                    self._instrument_id, side, quantity, price=price
                )
            self.submit_order(order)
            self._working_coid = str(order.client_order_id)
            self._last_submit_ns = ts_ns
            self.order_events.append(
                {"ts_ns": ts_ns, "type": "submit", "qty": qty, "decision_mid": decision_mid}
            )

        def on_order_filled(self, fill) -> None:
            side = 1 if fill.order_side == OrderSide.BUY else -1
            qty = int(fill.last_qty.as_double()) * side
            self._position += qty
            # Update average entry + realized PnL (VND, instrument
            # multiplier) so the report's total_pnl is honest (account
            # balances do not move in the sim with zero fees).
            old_pos = self._position - qty
            px = float(fill.last_px.as_double())
            if old_pos == 0:
                self._avg_entry = px
            elif (old_pos > 0) == (qty > 0):
                self._avg_entry = (
                    old_pos * (self._avg_entry or 0.0) + qty * px
                ) / self._position
            else:
                closing = min(abs(qty), abs(old_pos))
                direction = 1 if old_pos > 0 else -1
                self._realized_pnl_vnd += (
                    closing * (px - (self._avg_entry or 0.0)) * self._multiplier * direction
                )
                if self._position == 0:
                    self._avg_entry = None
                elif self._position * old_pos < 0:
                    self._avg_entry = px
            # The no-stacking invariant: the working guard clears only on a
            # TERMINAL fill; a partial fill keeps the order working (clearing
            # on partials fabricated duplicate orders and position
            # overshoot).
            try:
                order = self.cache.order(fill.client_order_id)
                terminal = order is None or str(order.status) != "PARTIALLY_FILLED"
            except Exception:  # noqa: BLE001
                terminal = True
            if terminal and self._working_coid == str(fill.client_order_id):
                self._working_coid = None
            decision = next(
                (e for e in reversed(self.order_events) if e["type"] == "submit"), None
            )
            decision_mid = (
                decision["decision_mid"] if decision else float(fill.last_px.as_double())
            )
            self.fills.append(
                {
                    "ts_ns": int(fill.ts_event),
                    "side": side,
                    "price": px,
                    "qty": abs(qty),
                    "decision_mid": decision_mid,
                    "slippage_bps": (px - decision_mid)
                    * side
                    * 10_000.0
                    / decision_mid,
                }
            )

        def on_order_rejected(self, event) -> None:
            reason = getattr(event, "reason", "")
            self.order_events.append(
                {"ts_ns": int(event.ts_event), "type": "rejected", "reason": str(reason)}
            )
            self._working_coid = None

    return TargetFollowerStrategy


# --------------------------------------------------------------------------- #
# Entry points
# --------------------------------------------------------------------------- #


def backtest_execution(
    targets: TargetSeries,
    bars: BarFrame,
    config: ExecutionConfig | None = None,
    algo: str = "marketable_limit",
    catalog: CatalogClient | None = None,
) -> ExecutionReport:
    """Offline execution backtest on the Nautilus engine.

    Two data modes:

    - bar mode (default): the continuous instrument driven by the EXPLICIT
      ``bars`` window (real recorded bars; no catalog access).
    - tick mode (``catalog`` given): driven by REAL trade ticks with
      order-book depth10 feeding, loaded from the catalog for
      ``targets.window`` - fills match against the actual book (the
      slippage-review leg, feedback execution -> alpha).

    No hardcoded instrument ids: the instrument derives from
    ``targets.instrument``; the bar type from ``bars.bar_type``.

    Parameters
    ----------
    targets : TargetSeries
        Target contract series (``ts`` + ``target_contracts``).
    bars : BarFrame
        The bar window (consumed in bar mode; provenance in tick mode).
    config : ExecutionConfig | None
        Defaults to ``ExecutionConfig()``.
    algo : str
        Registry key in ``execution_algorithms``.
    catalog : CatalogClient | None
        REQUIRED for tick mode (real ticks/depth); omitted -> bar mode.

    Returns
    -------
    ExecutionReport
        Counts, fills DataFrame, slippage stats, sim-account stats,
        provenance.

    Raises
    ------
    ValueError
        Empty targets, unknown algorithm, bar_type/instrument mismatch, or
        (tick mode) no ticks/depth in the window.
    """
    # Local import: keeps Nautilus lazy even for this function's module.
    from nautilus_trader.backtest.engine import BacktestEngine, BacktestEngineConfig
    from nautilus_trader.common.config import LoggingConfig
    from nautilus_trader.model.enums import AccountType, BookType, OmsType
    from nautilus_trader.model.objects import Money

    cfg = config or ExecutionConfig()
    try:
        execution_algorithms.get(algo)
    except KeyError as exc:
        raise ValueError(str(exc)) from None
    if len(targets.ts) == 0:
        raise ValueError("targets must be a non-empty TargetSeries")

    instrument = targets.instrument
    nautilus_instrument = _nautilus_instrument(instrument)
    currency = nautilus_instrument.quote_currency
    strategy_cls = _make_target_follower_strategy()

    start = targets.ts.min() - pd.Timedelta(minutes=5)
    end = targets.ts.max() + pd.Timedelta(minutes=10)

    if catalog is None:
        # Bar mode: continuous instrument driven by the explicit bar window.
        bar_type, data_objects = _bars_to_nautilus(bars, instrument)
        if not data_objects:
            raise ValueError(
                f"no bars in the provided BarFrame window [{bars.ts.min()}, {bars.ts.max()}]"
            )
        mode = "bar"
        book_type = BookType.L1_MBP
        ticks = depth = None
    else:
        # Tick mode: monthly-contract ticks + order-book depth10 (L2 book
        # matching) from the catalog for the target window.
        instrument_id_str = f"{instrument.symbol}.{instrument.venue}"
        ticks_df = catalog.ticks(instrument_id_str, start=start, end=end)
        depth_df = catalog.depth(instrument_id_str, start=start, end=end)
        if ticks_df.empty:
            raise ValueError(
                f"no trade ticks in [{start}, {end}] for {instrument_id_str}"
            )
        if depth_df.empty and not cfg.allow_l1:
            raise ValueError(
                f"no order-book depth10 for {instrument_id_str} in [{start}, {end}]:"
                " tick mode requires 10-level order-book data to measure"
                " slippage (missing-data behavior, not a silent degradation)."
                " Set ExecutionConfig(allow_l1=True) to run tick-only L1"
                " matching explicitly."
            )
        price_precision = _precision_from_increment(instrument.tick_size)
        ticks = _ticks_to_nautilus(ticks_df, instrument_id_str, price_precision)
        depth = (
            _depth_to_nautilus(depth_df, instrument_id_str, price_precision)
            if not depth_df.empty
            else []
        )
        # L2 book matching when depth exists; explicit L1 fallback otherwise.
        mode = "tick"
        book_type = BookType.L2_MBP if depth else BookType.L1_MBP
        bar_type = None
        data_objects = None

    target_map = {
        int(pd.Timestamp(t).value): int(q)
        for t, q in zip(targets.ts, targets.target_contracts)
    }

    engine = BacktestEngine(BacktestEngineConfig(logging=LoggingConfig(log_level="ERROR")))
    try:
        engine.add_venue(
            venue=nautilus_instrument.id.venue,
            oms_type=OmsType.HEDGING,
            account_type=AccountType.MARGIN,
            starting_balances=[Money(cfg.limits.capital_vnd, currency)],
            base_currency=currency,
            book_type=book_type,
        )
        engine.add_instrument(nautilus_instrument)
        if mode == "tick":
            # Separate add_data calls: the engine only checks the FIRST data
            # object of a batch for book data (engine.pyx:896), so ticks and
            # depth must not share one batch or L2 matching is not armed.
            # An EMPTY depth collection must not be added at all (the engine
            # rejects empty collections).
            engine.add_data(ticks, sort=True)
            if depth:
                engine.add_data(depth, sort=True)
        else:
            engine.add_data(data_objects, sort=True)
        strategy = strategy_cls(
            cfg,
            target_map,
            algo,
            nautilus_instrument,
            mode,
            bar_type if mode == "bar" else None,
        )
        engine.add_strategy(strategy)
        engine.run()
        fills = [f for f in strategy.fills if f["qty"] > 0]
        orders = strategy.order_events
        n_orders = sum(1 for e in orders if e["type"] == "submit")
        n_rejected = sum(1 for e in orders if e["type"] == "rejected")
        slippage = [f["slippage_bps"] for f in fills]
        stats: dict = {}
        try:
            from nautilus_trader.analysis.analyzer import PortfolioAnalyzer

            analyzer = PortfolioAnalyzer()
            analyzer.add_positions(engine.cache.positions())
            accounts = engine.cache.accounts()
            balance = (
                float(sum(m.as_double() for m in accounts[0].balances_total().values()))
                if accounts
                else 0.0
            )
            stats = {
                "n_positions": len(engine.cache.positions()),
                "realized_pnl_vnd": strategy._realized_pnl_vnd,
                "account_balance": balance,
                "total_pnl": strategy._realized_pnl_vnd,
            }
        except Exception as exc:  # noqa: BLE001 - analyzer is best-effort, never silent
            stats = {"error": f"{type(exc).__name__}: {exc}"}

        fills_df = pd.DataFrame(
            fills,
            columns=["ts_ns", "side", "price", "qty", "decision_mid", "slippage_bps"],
        )
        if mode == "tick":
            data_mode = mode + ("-l2" if book_type == BookType.L2_MBP else "-l1")
        else:
            data_mode = mode

        return ExecutionReport(
            n_target_changes=len(target_map),
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
                "data_mode": data_mode,
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
