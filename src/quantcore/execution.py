"""quantcore.execution - Execution Researcher module (decision note DEC-017).

Offline execution research reusing the Nautilus native machinery where
feasible (decision note DEC-017; Nautilus v1.231.0): ``backtest_execution``
runs a Nautilus ``BacktestEngine`` over the research catalog bars with a
target-following strategy; ``urgency_analysis`` implements the Component 6 -
Trade Scheduling urgency math; ``slippage_report`` produces the weekly
implementation-shortfall review that feeds cost-model recalibration
(feedback 7->1).

Extension slot: ``execution_algorithms`` registry - the plan contract is
``fn(gap_contracts: int, config: ExecutionConfig) -> list[int]`` (signed
child-order quantities, positive = buy). "marketable_limit" is the engine
default (mirror of the live bridge semantics: one working order at a time,
min gap, cooldown); "twap" slices the gap evenly.
"""

from __future__ import annotations

import json
import math
from collections import deque
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
from nautilus_trader.backtest.engine import BacktestEngine, BacktestEngineConfig, SimulatedExchange
from nautilus_trader.common.config import LoggingConfig
from nautilus_trader.model.data import BarType
from nautilus_trader.model.enums import AccountType, BookType, OmsType, OrderSide
from nautilus_trader.model.objects import Money, Price, Quantity
from nautilus_trader.persistence.catalog.parquet import ParquetDataCatalog
from nautilus_trader.trading.strategy import Strategy

from quantcore.core.artifacts import write_slippage_summary
from quantcore.core.config import DEFAULT_BAR_TYPE, DataConfig, REPO_ROOT
from quantcore.core.registry import Registry
from quantcore.core.extensions import ExecutionAlgorithm, _CallableExecutionAlgorithm
from trading.contracts import HarnessParams
from trading.instruments import build_continuous_futures_contract, load_futures_instrument_spec

INSTRUMENT_DEF_PATH = REPO_ROOT / "src" / "market_data" / "instrument_definitions" / "vn30f1m.hnx.json"

# --------------------------------------------------------------------------- #
# Extension registry
# --------------------------------------------------------------------------- #

#: Execution-algorithm slot: fn(gap_contracts, config) -> list[int] (signed chunks).
execution_algorithms = Registry(
    "execution_algorithms",
    contract=ExecutionAlgorithm,
    capability="plan",
    adapter=_CallableExecutionAlgorithm,
)


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


execution_algorithms.register(
    "marketable_limit",
    _marketable_limit_plan,
    source="python",
    description="default one-order-now plan mirroring the live bridge"
    " marketable-limit semantics (Python plan fn; provenance is honest -"
    " the Rust engine has no execution-algorithm machinery)",
)
execution_algorithms.register(
    "twap",
    _twap_plan,
    source="python",
    description="even slices over slice_bars bars",
)


def plan_orders(
    gap_contracts: int,
    algorithm: str,
    config: "ExecutionConfig",
) -> list[int]:
    """Plan and validate signed child quantities for one position gap."""
    if isinstance(gap_contracts, bool) or not isinstance(gap_contracts, int):
        raise TypeError("gap_contracts must be an integer")
    if not isinstance(config, ExecutionConfig):
        raise TypeError("config must be an ExecutionConfig")
    chunks = list(execution_algorithms.call(algorithm, gap_contracts, config))
    if any(isinstance(chunk, bool) or not isinstance(chunk, int) for chunk in chunks):
        raise ValueError(f"execution algorithm {algorithm!r} must return integer quantities")
    if any(chunk == 0 for chunk in chunks):
        raise ValueError(f"execution algorithm {algorithm!r} returned a zero quantity")
    if sum(chunks) != gap_contracts:
        raise ValueError(
            f"execution algorithm {algorithm!r} quantities sum to {sum(chunks)}, "
            f"expected {gap_contracts}"
        )
    if gap_contracts and any((chunk > 0) != (gap_contracts > 0) for chunk in chunks):
        raise ValueError(f"execution algorithm {algorithm!r} reversed the gap direction")
    return chunks


# --------------------------------------------------------------------------- #
# Configuration
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class ExecutionConfig:
    """Offline execution backtest configuration."""

    harness: HarnessParams = field(default_factory=HarnessParams)
    order_style: str = "LO"  # "LO" (limit at close) | "MAK" (market)
    cooldown_secs: float = 5.0
    min_gap_contracts: int = 1
    slice_bars: int = 12
    twap_interval_secs: float = 60.0  # tick-mode time gate between TWAP chunks
    capital_vnd: float = 100_000_000.0
    margin_rate: float = 0.05
    max_contracts: int = 10
    allow_l1: bool = False  # tick mode: False requires order-book depth10 (raise if missing)
    data: DataConfig | None = None


# --------------------------------------------------------------------------- #
# Nautilus backtest strategy
# --------------------------------------------------------------------------- #


class TargetFollowerStrategy(Strategy):
    """Target-following strategy for the offline engine (two data modes).

    Mirrors the live bridge semantics (Component 6 - Trade Scheduling,
    DEC-008): at most one working order, min-gap and cooldown skips, target
    changes only. ``mode="bar"`` drives from 1-minute bars (decision price =
    bar close); ``mode="tick"`` drives from trade ticks on a monthly contract
    with live order-book data (decision price = last trade tick), so fills
    happen against the real book. Order style per config: limit at the
    decision price (LO) or market (MAK). Decision mid for slippage = the
    decision price.
    """

    def __init__(
        self,
        config: ExecutionConfig,
        targets: dict[int, int],
        algo: str,
        instrument,
        mode: str,
        bar_type: BarType | None = None,
    ) -> None:
        super().__init__()
        self._cfg = config
        # Sorted pending targets: applied on the first bar/tick at/after each ts.
        self._pending: list[tuple[int, int]] = sorted(targets.items())
        self._algo = algo
        self._instrument = instrument
        self._instrument_id = instrument.id
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
        # Session-end awareness (sweep finding): after the contract expires,
        # STOP submitting - no retry loop against an expired instrument
        # (fills before expiry are still recorded). The live bridge stops at
        # session end / force-close; the offline engine mirrors that here.
        if ts_ns > self._expiration_ns:
            return
        while self._pending and self._pending[0][0] <= ts_ns:
            self._target = max(
                -self._cfg.max_contracts, min(self._cfg.max_contracts, self._pending.pop(0)[1])
            )

        # Decision mid = the reference price (bar close / last trade tick) -
        # the live bridge convention ("reference price is the last trade
        # price", trading/strategies/bridge.py). Book-mid refinement
        # (queue/adverse-selection aware) is deferred.
        decision_mid = price

        # Submit queued chunks: one per bar in bar mode; in tick mode time-
        # gated by twap_interval_secs so "slice_bars" means a time horizon,
        # not ~0.1s of ticks (practitioner review).
        if self._queue and self._working_coid is None:
            due = True
            if self._mode == "tick" and self._last_queue_submit_ns is not None:
                due = (ts_ns - self._last_queue_submit_ns) / 1e9 >= self._cfg.twap_interval_secs
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

        plan = plan_orders(gap, self._algo, self._cfg)
        if not plan:
            return
        self._queue = deque(plan[1:])
        self._submit(plan[0], ts_ns, decision_mid)

    def _submit(self, qty: int, ts_ns: int, decision_mid: float) -> None:
        if qty == 0:
            return
        side = OrderSide.BUY if qty > 0 else OrderSide.SELL
        quantity = Quantity(abs(qty), 0)
        if self._cfg.order_style == "MAK":
            order = self.order_factory.market(self._instrument_id, side, quantity)
        else:
            price = (
                self._instrument.make_price(decision_mid)
                if self._instrument is not None
                else Price(decision_mid, 1)
            )
            order = self.order_factory.limit(self._instrument_id, side, quantity, price=price)
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
        # Update average entry + realized PnL (VND, multiplier 100,000) so the
        # report's total_pnl is honest (practitioner review: account balances
        # do not move in the sim with zero fees).
        old_pos = self._position - qty
        px = float(fill.last_px.as_double())
        if old_pos == 0:
            self._avg_entry = px
        elif (old_pos > 0) == (qty > 0):
            self._avg_entry = (old_pos * (self._avg_entry or 0.0) + qty * px) / self._position
        else:
            closing = min(abs(qty), abs(old_pos))
            direction = 1 if old_pos > 0 else -1
            self._realized_pnl_vnd += (
                closing * (px - (self._avg_entry or 0.0)) * 100_000.0 * direction
            )
            if self._position == 0:
                self._avg_entry = None
            elif self._position * old_pos < 0:
                self._avg_entry = px
        # The no-stacking invariant (canon 3.4): the working guard clears only
        # on a TERMINAL fill; a partial fill keeps the order working
        # (practitioner review: clearing on partials fabricated duplicate
        # orders and position overshoot).
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
        decision_mid = decision["decision_mid"] if decision else float(fill.last_px.as_double())
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


# --------------------------------------------------------------------------- #
# Entry points
# --------------------------------------------------------------------------- #


def backtest_execution(
    targets: pd.DataFrame,
    config: ExecutionConfig | None = None,
    data: DataConfig | None = None,
    algo: str = "marketable_limit",
    instrument_id: str | None = None,
) -> dict:
    """Offline execution backtest on the Nautilus engine.

    ``targets``: DataFrame with columns ``ts`` (UTC datetime) and
    ``target_contracts`` (signed int). Two data modes:

    - ``instrument_id=None`` (default): the continuous VN30F1M instrument
      driven by 1-minute bars from the research catalog.
    - ``instrument_id="41I1G9000.HNX"`` (monthly contract in the catalog):
      driven by REAL trade ticks with order-book depth10 feeding - fills
      match against the actual book (the slippage-review leg, feedback 7->1).

    Returns an in-memory report: {"n_target_changes", "n_orders", "n_fills",
    "fills", "order_events", "slippage_bps_mean", "slippage_bps_median",
    "stats", "stats_error", "algo", "provenance"}.
    """
    cfg = config or ExecutionConfig()
    eff_data = data or cfg.data or DataConfig()
    if targets.empty:
        raise ValueError("targets must be a non-empty DataFrame")
    for col in ("ts", "target_contracts"):
        if col not in targets.columns:
            raise ValueError(f"targets missing column {col!r}")

    catalog_path = (
        Path(eff_data.catalog_path)
        if eff_data.catalog_path
        else REPO_ROOT / "data" / "catalog"
    )
    if not catalog_path.exists():
        raise FileNotFoundError(f"research catalog not found at {catalog_path}")
    catalog = ParquetDataCatalog(str(catalog_path))
    start = targets["ts"].min() - pd.Timedelta(minutes=5)
    end = targets["ts"].max() + pd.Timedelta(minutes=10)

    if instrument_id is None:
        # Bar mode: continuous instrument + 1-minute bars.
        spec = load_futures_instrument_spec(INSTRUMENT_DEF_PATH)
        instrument = build_continuous_futures_contract(
            spec, ts_init="2018-01-01", expiration="2100-01-01"
        )
        currency = spec.quote_currency()
        bar_type = BarType.from_str(eff_data.bar_type or DEFAULT_BAR_TYPE)
        data_objects = list(
            catalog.bars(bar_types=[str(bar_type)], start=start, end=end)
        )
        if not data_objects:
            raise ValueError(f"no catalog bars in [{start}, {end}] for {bar_type}")
        mode = "bar"
        book_type = BookType.L1_MBP
    else:
        # Tick mode: monthly contract instrument from the catalog, driven by
        # real trade ticks with order-book depth10 (L2 book matching).
        instruments = {str(i.id): i for i in catalog.instruments()}
        instrument = instruments.get(instrument_id)
        if instrument is None:
            raise ValueError(
                f"instrument {instrument_id!r} not in catalog;"
                f" available: {sorted(instruments)}"
            )
        currency = instrument.quote_currency
        ticks = list(catalog.trade_ticks(instrument_id=instrument.id, start=start, end=end))
        depth = list(catalog.order_book_depth10(instrument_id=instrument.id, start=start, end=end))
        # Guard: the catalog query can silently return OTHER instruments' data
        # when the requested instrument has none in range (practitioner
        # review) - filter to the requested instrument id explicitly.
        ticks = [t for t in ticks if t.instrument_id == instrument.id]
        depth = [d for d in depth if d.instrument_id == instrument.id]
        if not ticks:
            raise ValueError(f"no trade ticks in [{start}, {end}] for {instrument_id}")
        if not depth and not cfg.allow_l1:
            raise ValueError(
                f"no order-book depth10 for {instrument_id} in [{start}, {end}]:"
                " tick mode requires 10-level order-book data to measure"
                " slippage (missing-data behavior, not a silent degradation)."
                " Set ExecutionConfig(allow_l1=True) to run tick-only L1"
                " matching explicitly."
            )
        # L2 book matching when depth exists; explicit L1 fallback otherwise.
        book_type = BookType.L2_MBP if depth else BookType.L1_MBP
        data_objects = ticks + depth
        mode = "tick"

    target_map = {
        int(pd.Timestamp(t).value): int(v)
        for t, v in zip(targets["ts"], targets["target_contracts"])
    }

    engine = BacktestEngine(
        BacktestEngineConfig(logging=LoggingConfig(log_level="ERROR"))
    )
    try:
        engine.add_venue(
            venue=instrument.venue,
            oms_type=OmsType.HEDGING,
            account_type=AccountType.MARGIN,
            starting_balances=[Money(cfg.capital_vnd, currency)],
            base_currency=currency,
            book_type=book_type,
        )
        engine.add_instrument(instrument)
        if mode == "tick":
            # Separate add_data calls: the engine only checks the FIRST data
            # object of a batch for book data (engine.pyx:896), so ticks and
            # depth must not share one batch or L2 matching is not armed.
            # An EMPTY depth collection must not be added at all (the engine
            # rejects empty collections - found by the full-coverage sweep).
            engine.add_data(ticks, sort=True)
            if depth:
                engine.add_data(depth, sort=True)
        else:
            engine.add_data(data_objects, sort=True)
        strategy = TargetFollowerStrategy(
            cfg,
            target_map,
            algo,
            instrument,
            mode,
            bar_type if mode == "bar" else None,
        )
        engine.add_strategy(strategy)
        engine.run()
        fills = strategy.fills
        orders = strategy.order_events
        fills = [f for f in fills if f["qty"] > 0]
        n_orders = sum(1 for e in orders if e["type"] == "submit")
        n_rejected = sum(1 for e in orders if e["type"] == "rejected")
        slippage = [f["slippage_bps"] for f in fills]
        stats: dict | None = None
        stats_error: str | None = None
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
        except Exception as exc:  # noqa: BLE001 - analyzer is best-effort, but never silent
            stats = None
            stats_error = f"{type(exc).__name__}: {exc}"
        return {
            "n_target_changes": len(target_map),
            "n_orders": n_orders,
            "n_fills": len(fills),
            "n_rejected": n_rejected,
            "fills": fills,
            "order_events": orders,
            "slippage_bps_mean": float(np.mean(slippage)) if slippage else 0.0,
            "slippage_bps_median": float(np.median(slippage)) if slippage else 0.0,
            "stats": stats,
            "stats_error": stats_error,
            "algo": algo,
            "provenance": {
                "algo": algo,
                "algo_source": execution_algorithms.get(algo).source,
                "order_style": cfg.order_style,
                "engine": "nautilus_trader.backtest.engine.BacktestEngine",
                "data_mode": mode + ("-l2" if mode == "tick" and book_type == BookType.L2_MBP else "-l1" if mode == "tick" else ""),
            },
        }
    finally:
        engine.dispose()


def _mean_or_zero(values: list[float]) -> float:
    return float(np.mean(values)) if values else 0.0


def urgency_analysis(
    gap_contracts: float,
    half_spread_bps: float,
    impact_bps: float,
    alpha_decay_per_bar: float,
    value_of_1bp: float,
    hold_bars: float = 1.0,
) -> dict:
    """Component 6 - Trade Scheduling urgency math (canon section 3.1).

    cost_of_waiting = gap * alpha_decay_per_bar * value_of_1bp * hold_bars;
    cost_of_acting = gap * (half_spread_bps + impact_bps) * value_of_1bp;
    verdict "act-now" when waiting costs more than acting, else "slice".
    Units must be consistent across inputs (bp-based costs, 1bp value in
    the same currency unit).
    """
    if gap_contracts < 0:
        raise ValueError("gap_contracts must be non-negative")
    if value_of_1bp < 0:
        raise ValueError("value_of_1bp must be non-negative")
    if alpha_decay_per_bar < 0:
        raise ValueError("alpha_decay_per_bar must be non-negative")
    if half_spread_bps < 0:
        raise ValueError("half_spread_bps must be non-negative")
    if impact_bps < 0:
        raise ValueError("impact_bps must be non-negative")
    if hold_bars <= 0:
        raise ValueError("hold_bars must be positive")
    cost_of_waiting = gap_contracts * alpha_decay_per_bar * value_of_1bp * hold_bars
    cost_of_acting = gap_contracts * (half_spread_bps + impact_bps) * value_of_1bp
    return {
        "cost_of_waiting": cost_of_waiting,
        "cost_of_acting": cost_of_acting,
        "verdict": "act-now" if cost_of_waiting > cost_of_acting else "slice",
    }


def _hour_of(ts) -> str | None:
    """Normalize a fill timestamp to the VN session hour (Asia/Ho_Chi_Minh):
    naive strings are read as Hanoi local, ints as UTC (backtest fills carry
    ts_ns in UTC) - ONE convention for the by_session_hour axis
    (practitioner review: mixing the two mixed timezones)."""
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


def slippage_report(
    fills: list[dict] | None = None,
    decision_log: list[dict] | None = None,
    session_dir: str | None = None,
    cost_model_bps: float | None = None,
    save: bool = True,
    week: str | None = None,
    root=None,
) -> dict:
    """Weekly implementation-shortfall review (feedback 7->1).

    Input: explicit fills (each with price, decision_mid, side, optional
    qty and vol_regime), a decision log, or a session dir. Session dirs are
    read for ``fills.jsonl`` (fill artifacts) first; a bridge-style
    ``decisions.jsonl`` alone raises an actionable error - the bridge logs
    decisions only, fill prices live in the streaming catalog
    (practitioner review). Shortfall = (fill price - decision mid) * side
    in bp of the reference price; decomposed by session hour (Hanoi local),
    size bucket (fill quantity) and vol regime (caller-provided
    ``vol_regime`` per fill); excess vs the cost model (default
    HarnessParams cost_per_side = 2.294 bp). When ``save=True`` the summary
    is persisted as the weekly handoff artifact consumed by cost-model
    recalibration.
    """
    if fills is None and decision_log is None and session_dir is None:
        raise ValueError("provide fills, decision_log or session_dir")
    if cost_model_bps is None:
        cost_model_bps = HarnessParams().cost_per_side * 10_000.0

    records: list[dict] = []
    if session_dir is not None:
        fills_path = Path(session_dir) / "fills.jsonl"
        dec_path = Path(session_dir) / "decisions.jsonl"
        if fills_path.exists():
            fills = [
                json.loads(line)
                for line in fills_path.read_text().splitlines()
                if line.strip()
            ]
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
    if decision_log is not None:
        for e in decision_log:
            if "decision_mid" in e or "price" in e:
                records.append(
                    {
                        "price": float(e.get("price", e.get("decision_mid", 0.0))),
                        "decision_mid": float(e.get("decision_mid", e.get("price", 0.0))),
                        "side": int(e.get("side", 1)),
                        "qty": float(e.get("qty", 1.0)),
                        "vol_regime": e.get("vol_regime"),
                        "ts": e.get("ts", e.get("ts_ns")),
                    }
                )
    records.extend(fills or [])

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
                "bps": (price - mid) * side * 10_000.0 / mid,
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

    summary = {
        "generated": date.today().isoformat(),
        "n_records": len(shortfalls),
        "mean_shortfall_bps": float(np.mean([s["bps"] for s in shortfalls])),
        "median_shortfall_bps": float(np.median([s["bps"] for s in shortfalls])),
        "cost_model_bps": cost_model_bps,
        "excess_bps": float(np.mean([s["bps"] for s in shortfalls])) - cost_model_bps,
        "by_session_hour": {k: float(np.mean(v)) for k, v in sorted(by_hour.items())},
        "size_buckets": {
            k: _mean_or_zero(v) for k, v in by_size.items()
        },
        "vol_regime": {k: float(np.mean(v)) for k, v in sorted(by_regime.items())},
    }
    if save:
        write_slippage_summary(summary, week=week, root=root)
    return summary
