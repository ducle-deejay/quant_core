"""quant_api.execution - Execution Researcher module (decision note DEC-017).

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
from nautilus_trader.model.data import BarType
from nautilus_trader.model.enums import AccountType, OmsType, OrderSide
from nautilus_trader.model.objects import Money, Price, Quantity
from nautilus_trader.persistence.catalog.parquet import ParquetDataCatalog
from nautilus_trader.trading.strategy import Strategy

from quant_api.core.artifacts import write_slippage_summary
from quant_api.core.config import DEFAULT_BAR_TYPE, DataConfig, REPO_ROOT
from quant_api.core.registry import Registry
from trading.contracts import HarnessParams
from trading.instruments import build_continuous_futures_contract, load_futures_instrument_spec

INSTRUMENT_DEF_PATH = REPO_ROOT / "src" / "market_data" / "instrument_definitions" / "vn30f1m.hnx.json"

# --------------------------------------------------------------------------- #
# Extension registry
# --------------------------------------------------------------------------- #

#: Execution-algorithm slot: fn(gap_contracts, config) -> list[int] (signed chunks).
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


execution_algorithms.register(
    "marketable_limit",
    _marketable_limit_plan,
    source="engine",
    description="one marketable order at the decision bar (live bridge LO/MAK semantics)",
)
execution_algorithms.register(
    "twap",
    _twap_plan,
    source="python",
    description="even slices over slice_bars bars",
)


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
    capital_vnd: float = 100_000_000.0
    margin_rate: float = 0.05
    max_contracts: int = 10
    data: DataConfig | None = None


# --------------------------------------------------------------------------- #
# Nautilus backtest strategy
# --------------------------------------------------------------------------- #


class TargetFollowerStrategy(Strategy):
    """One-bar-in/one-target-out strategy for the offline engine.

    Mirrors the live bridge semantics (Component 6 - Trade Scheduling,
    DEC-008): at most one working order, min-gap and cooldown skips, target
    changes only. Order style per config: limit at the decision close (LO)
    or market (MAK). Decision mid for slippage = decision-bar close.
    """

    def __init__(
        self,
        config: ExecutionConfig,
        targets: dict[int, int],
        algo: str,
        instrument_id,
        bar_type: BarType,
        instrument=None,
    ) -> None:
        super().__init__()
        self._cfg = config
        self._targets = targets  # ts_ns -> signed contracts
        self._algo = algo
        self._instrument_id = instrument_id
        self._bar_type = bar_type
        self._instrument = instrument
        self._position = 0
        self._target = 0
        self._queue: deque[int] = deque()
        self._last_submit_ns: int | None = None
        self._working_coid: str | None = None
        self.fills: list[dict] = []
        self.order_events: list[dict] = []

    def on_start(self) -> None:
        self.subscribe_bars(self._bar_type)

    def on_bar(self, bar) -> None:
        ts_ns = int(bar.ts_event)
        if ts_ns in self._targets:
            self._target = int(self._targets[ts_ns])

        # Submit queued TWAP chunks (one per bar, no stacking).
        if self._queue and self._working_coid is None:
            self._submit(self._queue.popleft(), ts_ns, float(bar.close.as_double()))

        gap = self._target - self._position
        if gap == 0 or self._working_coid is not None:
            return
        if abs(gap) < self._cfg.min_gap_contracts:
            return
        if self._last_submit_ns is not None:
            elapsed = (ts_ns - self._last_submit_ns) / 1e9
            if elapsed < self._cfg.cooldown_secs:
                return

        plan = execution_algorithms.call(self._algo, gap, self._cfg)
        if not plan:
            return
        self._queue = deque(plan[1:])
        self._submit(plan[0], ts_ns, float(bar.close.as_double()))

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
        if self._working_coid == str(fill.client_order_id):
            self._working_coid = None
        decision = next(
            (e for e in reversed(self.order_events) if e["type"] == "submit"), None
        )
        decision_mid = decision["decision_mid"] if decision else float(fill.last_px.as_double())
        self.fills.append(
            {
                "ts_ns": int(fill.ts_event),
                "side": side,
                "price": float(fill.last_px.as_double()),
                "qty": abs(qty),
                "decision_mid": decision_mid,
                "slippage_bps": (float(fill.last_px.as_double()) - decision_mid)
                * side
                * 10_000.0
                / decision_mid,
            }
        )

    def on_order_rejected(self, event) -> None:
        self.order_events.append({"ts_ns": int(event.ts_event), "type": "rejected"})
        self._working_coid = None


# --------------------------------------------------------------------------- #
# Entry points
# --------------------------------------------------------------------------- #


def backtest_execution(
    targets: pd.DataFrame,
    config: ExecutionConfig | None = None,
    data: DataConfig | None = None,
    algo: str = "marketable_limit",
) -> dict:
    """Offline execution backtest on the Nautilus engine.

    ``targets``: DataFrame with columns ``ts`` (UTC datetime) and
    ``target_contracts`` (signed int). Returns an in-memory report:
    {"n_target_changes", "n_orders", "n_fills", "fills", "slippage_bps_mean",
    "slippage_bps_median", "stats", "algo", "provenance"}.
    """
    cfg = config or ExecutionConfig()
    eff_data = data or cfg.data or DataConfig()
    if targets.empty or "target_contracts" not in targets.columns:
        raise ValueError("targets must be a non-empty DataFrame with target_contracts")
    for col in ("ts", "target_contracts"):
        if col not in targets.columns:
            raise ValueError(f"targets missing column {col!r}")

    # Instrument + venue (reuse the live contract builders; the engine
    # builds its SimulatedExchange internally from add_venue).
    spec = load_futures_instrument_spec(INSTRUMENT_DEF_PATH)
    instrument = build_continuous_futures_contract(
        spec, ts_init="2018-01-01", expiration="2100-01-01"
    )
    currency = spec.quote_currency()

    bar_type = BarType.from_str(eff_data.bar_type or DEFAULT_BAR_TYPE)

    # Bars from the research catalog over the targets' window.
    catalog = ParquetDataCatalog(str(REPO_ROOT / "data" / "catalog"))
    start = targets["ts"].min() - pd.Timedelta(minutes=5)
    end = targets["ts"].max() + pd.Timedelta(minutes=10)
    bars = list(
        catalog.bars(bar_types=[str(bar_type)], start=start, end=end)
    )
    if not bars:
        raise ValueError(f"no catalog bars in [{start}, {end}] for {bar_type}")

    target_map = {
        int(pd.Timestamp(t).value): int(v)
        for t, v in zip(targets["ts"], targets["target_contracts"])
    }

    engine = BacktestEngine(BacktestEngineConfig())
    try:
        engine.add_venue(
            venue=instrument.venue,
            oms_type=OmsType.HEDGING,
            account_type=AccountType.MARGIN,
            starting_balances=[Money(cfg.capital_vnd, currency)],
            base_currency=currency,
        )
        engine.add_instrument(instrument)
        engine.add_data(bars)
        strategy = TargetFollowerStrategy(
            cfg, target_map, algo, instrument.id, bar_type, instrument=instrument
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
        try:
            from nautilus_trader.analysis.analyzer import PortfolioAnalyzer

            analyzer = PortfolioAnalyzer(portfolio=engine.portfolio)
            analyzer.add_positions(engine.cache.positions())
            stats = {
                "n_positions": len(engine.cache.positions()),
                "total_pnl": float(engine.cache.account(venue.id).balances_total().as_double()),
            }
        except Exception:  # noqa: BLE001 - analyzer is best-effort
            stats = None
        return {
            "n_target_changes": len(target_map),
            "n_orders": n_orders,
            "n_fills": len(fills),
            "n_rejected": n_rejected,
            "fills": fills,
            "slippage_bps_mean": float(np.mean(slippage)) if slippage else 0.0,
            "slippage_bps_median": float(np.median(slippage)) if slippage else 0.0,
            "stats": stats,
            "algo": algo,
            "provenance": {
                "algo": algo,
                "algo_source": execution_algorithms.get(algo).source,
                "order_style": cfg.order_style,
                "engine": "nautilus_trader.backtest.engine.BacktestEngine",
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
    cost_of_waiting = gap_contracts * alpha_decay_per_bar * value_of_1bp * hold_bars
    cost_of_acting = gap_contracts * (half_spread_bps + impact_bps) * value_of_1bp
    return {
        "cost_of_waiting": cost_of_waiting,
        "cost_of_acting": cost_of_acting,
        "verdict": "act-now" if cost_of_waiting > cost_of_acting else "slice",
    }


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

    Input: explicit fills (each with price, decision_mid, side), a decision
    log, or a session dir under data/logs/sessions/<date>/ containing
    decisions.jsonl. Shortfall = (fill price - decision mid) * side in bp,
    decomposed by session hour, size bucket and vol regime; excess vs the
    cost model (default HarnessParams cost_per_side = 2.294 bp). When
    ``save=True`` the summary is persisted as the weekly handoff artifact
    consumed by cost-model recalibration.
    """
    if fills is None and decision_log is None and session_dir is None:
        raise ValueError("provide fills, decision_log or session_dir")
    if cost_model_bps is None:
        cost_model_bps = HarnessParams().cost_per_side * 10_000.0

    records: list[dict] = []
    if session_dir is not None:
        p = Path(session_dir) / "decisions.jsonl"
        if p.exists():
            decision_log = [
                json.loads(line)
                for line in p.read_text().splitlines()
                if line.strip()
            ]
    if decision_log is not None:
        for e in decision_log:
            if "decision_mid" in e or "price" in e:
                records.append(
                    {
                        "price": float(e.get("price", e.get("decision_mid", 0.0))),
                        "decision_mid": float(e.get("decision_mid", e.get("price", 0.0))),
                        "side": int(e.get("side", 1)),
                        "ts": e.get("ts", e.get("ts_ns")),
                    }
                )
    records.extend(fills or [])

    shortfalls = []
    for r in records:
        mid = r.get("decision_mid")
        price = r.get("price")
        side = r.get("side", 1)
        if mid is None or price is None or mid == 0:
            continue
        shortfalls.append({"bps": (price - mid) * side * 10_000.0 / mid, "ts": r.get("ts")})

    if not shortfalls:
        raise ValueError("no usable fill records (need price, decision_mid, side)")

    by_hour: dict[str, list[float]] = {}
    for s in shortfalls:
        ts = s["ts"]
        hour = None
        if isinstance(ts, str) and len(ts) >= 13:
            hour = ts[11:13]
        elif isinstance(ts, (int, float)):
            hour = str(int(pd.Timestamp(int(ts), unit="ns", tz="UTC").hour)).zfill(2)
        key = hour or "unknown"
        by_hour.setdefault(key, []).append(s["bps"])

    summary = {
        "generated": date.today().isoformat(),
        "n_records": len(shortfalls),
        "mean_shortfall_bps": float(np.mean([s["bps"] for s in shortfalls])),
        "median_shortfall_bps": float(np.median([s["bps"] for s in shortfalls])),
        "cost_model_bps": cost_model_bps,
        "excess_bps": float(np.mean([s["bps"] for s in shortfalls])) - cost_model_bps,
        "by_session_hour": {k: float(np.mean(v)) for k, v in sorted(by_hour.items())},
        "size_buckets": {
            "small_<=3": _mean_or_zero([s["bps"] for s in shortfalls if abs(s["bps"]) <= 3]),
            "large_>3": _mean_or_zero([s["bps"] for s in shortfalls if abs(s["bps"]) > 3]),
        },
    }
    if save:
        write_slippage_summary(summary, week=week, root=root)
    return summary
