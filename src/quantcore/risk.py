"""quantcore.risk - Quant Risk Researcher module."""

from __future__ import annotations

import json
import math
from collections import Counter
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

import alpha_core
import numpy as np

from core.artifacts import Composite, SpecSheet, TargetSeries, WindowMismatch
from core.contracts import (
    AccountLimits,
    HarnessParams,
    Instrument,
    RiskConfig,
    RiskState,
)
from core.data import BarFrame
from core.mapping import hysteresis_band_contracts, max_contracts_at
from core.registry import Registry
from core.signal import close_returns, rolling_vol
from core.risk import (
    ACTIVE,
    HALTED,
    REDUCING,
    REASON_EXCEEDS_MAX,
    REASON_EXPOSURE,
    REASON_LOSS,
    REASON_REDUCING_ONLY,
    REASON_STALE,
    RiskLedger,
    in_tz,
    is_session_open,
    parse_close_time,
    session_day,
)

__all__ = [
    "PolicyInput",
    "RiskBacktestConfig",
    "RiskBacktestResult",
    "RiskLedger",
    "SideReport",
    "SessionReport",
    "GaugeReport",
    "backtest_portfolio",
    "divergence_gauges",
    "post_mortem",
    "risk_policies",
    "sizing_methods",
]

#: Default sizing/policy registry keys used by ``backtest_portfolio``.
#: ``RiskBacktestConfig`` is frozen without name fields, so selection
#: happens at the registry: register a replacement under the same name
#: (``replace=True``) to change the backtest.
DEFAULT_SIZING = "vol_target_drawdown"
DEFAULT_POLICY = "trigger_matrix"

#: Rolling realized-vol window (bars) for the sizing stack's vol estimate.
VOL_EST_WINDOW = 20

#: Gauge 3 bound: mean |actual - target| in contracts treated as healthy.
TRACKING_ERROR_BOUND_CONTRACTS = 1.0

#: Gauge 4 expected fill rate (fraction) - a LOWER limit.
FILL_RATE_EXPECTED = 0.95


# --------------------------------------------------------------------------- #
# Sizing registry
# --------------------------------------------------------------------------- #

#: Sizing slot. UNIFORM call convention for every method (engine defaults
#: and python-registered alike):
#: ``fn(z_scores, vol_est, target_vol, drawdowns=None, floor=None) -> list[float]``
sizing_methods = Registry("sizing_methods")


def _vol_target(z_scores, vol_est, target_vol, drawdowns=None, floor=None):
    """Engine-backed vol targeting."""
    return alpha_core.vol_target_py(z_scores, vol_est, target_vol, floor)


def _drawdown_overlay(z_scores, vol_est, target_vol, drawdowns=None, floor=None):
    """Engine-backed drawdown ladder overlay (no-op when drawdowns is None)."""
    if drawdowns is None:
        return list(z_scores)
    return alpha_core.drawdown_multiplier_py(list(drawdowns))


def _vol_target_drawdown(z_scores, vol_est, target_vol, drawdowns=None, floor=None):
    """The wired default stack: vol target, then drawdown overlay
    (no-op overlay when drawdowns is None)."""
    scaled = alpha_core.vol_target_py(z_scores, vol_est, target_vol, floor)
    if drawdowns is None:
        return scaled
    mult = alpha_core.drawdown_multiplier_py(list(drawdowns))
    return [s * m for s, m in zip(scaled, mult)]


for _name, _fn in (
    ("vol_target", _vol_target),
    ("drawdown_overlay", _drawdown_overlay),
    ("vol_target_drawdown", _vol_target_drawdown),
):
    if _name not in sizing_methods.names():
        sizing_methods.register(_name, _fn, source="engine")


# --------------------------------------------------------------------------- #
# Risk-policy registry
# --------------------------------------------------------------------------- #

#: Risk-policy slot. Custom policy contract:
#: ``fn(policy_input: PolicyInput) -> dict`` with keys ``{"status",
#: "allowed_position", "reason"}``. ``PolicyInput`` is the FULL contract -
#: all seven keys, documented on the dataclass.
risk_policies = Registry("risk_policies")


@dataclass(frozen=True)
class PolicyInput:
    """One risk-policy decision request (the full custom-policy contract).

    Parameters
    ----------
    ts : datetime
        Bar/decision timestamp (UTC preferred; the ledger normalizes).
    position : int
        Current signed position, in contracts.
    session_pnl : float
        Session PnL so far, in VND (realized + marked).
    target : int
        Desired signed position, in contracts.
    config : dict
        ``RiskConfig`` asdict (limits, instrument, triggers) for policies
        that read configuration.
    ledger : object
        The loop's ledger (``RiskLedger``; used by the ``trigger_matrix``
        policy only). Custom policies may ignore it.
    price : float
        Current price (bar close), the mark and fill price.
    """

    ts: datetime
    position: int
    session_pnl: float
    target: int
    config: dict
    ledger: object
    price: float


def _trigger_matrix_policy(policy_input: PolicyInput) -> dict:
    """Offline policy application driving the ``RiskLedger`` trigger matrix.

    The ledger is driven per bar: fills for position deltas (realized PnL
    in VND), mark at the close, bar arrival, then ``decide()`` (loss limit,
    staleness - staleness cannot fire offline on a continuous bar feed -
    exposure cap) and ``gate()`` semantics: HALTED flattens, REDUCING only
    reduces, ACTIVE allows capped targets.
    """
    ledger = policy_input.ledger
    ts: datetime = policy_input.ts
    price: float = policy_input.price
    target: int = policy_input.target

    ledger.on_bar(ts)
    ledger.mark(price, ts)
    state = ledger.decide()
    current = ledger.position

    if state.status == HALTED:
        allowed = 0  # flatten
        reason = state.reason
    elif state.status == REDUCING:
        allowed = min(abs(current), ledger.config.limits.max_contracts) * (
            1 if current >= 0 else -1
        )
        reason = state.reason
    else:
        allowed_ok, gate_reason = ledger.gate(target, current)
        allowed = target if allowed_ok else current
        # Surface gate denials (exceeds-max-contracts / reducing-only) so
        # trigger_counts reflects every intervention, not just status
        # changes.
        reason = gate_reason or state.reason

    delta = allowed - current
    if delta != 0:
        ledger.record_fill(price, delta, ts)
    return {"status": state.status, "reason": reason, "allowed_position": allowed}


if "trigger_matrix" not in risk_policies.names():
    risk_policies.register(
        "trigger_matrix",
        _trigger_matrix_policy,
        source="python",
        description="offline RiskLedger trigger matrix (ported from"
        " trading.risk.state, rewired to core.contracts.RiskConfig)",
    )


# --------------------------------------------------------------------------- #
# Configuration and reports
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class RiskBacktestConfig:
    """Configuration for :func:`backtest_portfolio`.

    Parameters
    ----------
    harness : HarnessParams
        Canonical parameters (band/cap feed the contract-conversion
        hysteresis; bars_per_day the PnL aggregation).
    vol_target : float
        Annualized volatility target for the sizing stack (fraction).
    vol_floor : float | None
        Optional vol floor for the sizing stack (fraction).
    risk : RiskConfig
        Live-equivalent risk configuration (triggers, tz, session close);
        the offline ledger is constructed from it.
    limits : AccountLimits
        Account limits (capital, safety factor, margin rate,
        max_contracts) driving the contract conversion.
    """

    harness: HarnessParams = field(default_factory=HarnessParams)
    vol_target: float = 0.1
    vol_floor: float | None = None
    risk: RiskConfig = field(default_factory=RiskConfig)
    limits: AccountLimits = field(default_factory=AccountLimits)


@dataclass(frozen=True)
class SideReport:
    """One side ("before" = sizing only, "after" = policy applied) of the
    portfolio backtest.

    Parameters
    ----------
    performance : dict
        ``net_sharpe``, ``max_drawdown``, ``total_net_pnl`` of the side's
        contract series (canonical PnL units; sharpe/drawdown scale-free).
    risk_process : dict
        ``n_interventions``, ``intervention_cost_estimate_vnd``,
        ``mean_abs_tracking_error``, ``max_abs_position``,
        ``trigger_counts`` (overfit guard: sizing models are never judged
        on performance alone).
    """

    performance: dict
    risk_process: dict


@dataclass(frozen=True)
class RiskBacktestResult:
    """Full portfolio-backtest report (in-memory, never auto-saved).

    Parameters
    ----------
    targets : TargetSeries
        The "after" contract series - the artifact handed to execution.
    before : SideReport
        Sizing-only side.
    after : SideReport
        Policy-applied side.
    interventions : list[dict]
        Status-change events: ``{"ts", "previous", "current", "reason"}``.
    metrics_diff : dict
        ``after.performance - before.performance`` for ``net_sharpe`` and
        ``max_drawdown``.
    provenance : dict
        Sizing/policy names + registry sources + engine version.
    """

    targets: TargetSeries
    before: SideReport
    after: SideReport
    interventions: list[dict]
    metrics_diff: dict
    provenance: dict


@dataclass(frozen=True)
class GaugeReport:
    """Divergence-gauge report (in-memory, never auto-saved).

    Parameters
    ----------
    gauges : dict
        Gauge id -> ``{"value", "expected", "status", "note"}`` (value may
        be None with status "n/a" and a reason note).
    escalation : str
        ``"critical"`` / ``"warning"`` / ``"none"`` across all gauges.
    """

    gauges: dict
    escalation: str


@dataclass(frozen=True)
class SessionReport:
    """Session post-mortem (data only - never auto-applied).

    Parameters
    ----------
    session_dir : str
        The dissected session directory.
    n_decision_events : int
        Decision-log event count.
    n_risk_transitions : int
        Risk-transition event count.
    timeline : list[dict]
        First 200 events merged from both logs (sorted by ``ts_ns``/``ts``).
    target_flips : int
        Count of target changes in the decision log.
    big_gap_moves : int
        Target changes of 3+ contracts.
    risk_transition_counts : dict
        ``"status:reason"`` -> count.
    recommendations : list[dict]
        Candidate recommendations derived from the triggers observed.
    """

    session_dir: str
    n_decision_events: int
    n_risk_transitions: int
    timeline: list[dict]
    target_flips: int
    big_gap_moves: int
    risk_transition_counts: dict
    recommendations: list[dict]


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #






def _drawdowns_from_pnl(
    pnl: list[float], close: list[float], capital_vnd: float, multiplier: float
) -> list[float]:
    """Proxy drawdown series: equity = 1 + cumsum(bar pnl in VND) / capital,
    drawdown = 1 - equity / running peak. Documented proxy for the ladder
    input (the drawdown multiplier interprets fractions of initial equity)."""
    equity = 1.0
    peak = 1.0
    out: list[float] = []
    for bar_pnl, px in zip(pnl, close):
        equity += bar_pnl * px * multiplier / capital_vnd
        peak = max(peak, equity)
        out.append(max(0.0, 1.0 - equity / peak) if peak > 0 else 0.0)
    return out


def _z_to_contracts(
    z_series: list[float],
    close: list[float],
    harness: HarnessParams,
    instrument: Instrument,
    limits: AccountLimits,
) -> list[int]:
    """Score series -> contract series with the no-trade band (dead-zone
    WITH hysteresis: hold the previous position while
    |new - prev| <= band_contracts; ``canonical_map`` applies the same rule
    in z units, this mirrors it in contract units).

    Composition note: the band is applied to the UNCLIPPED raw count and
    the clip to +/- ``limits.max_contracts`` happens only when the position
    actually moves - that order is what the recorded research outputs (and
    the ``canonical_map`` z-unit rule) encode, so the loop uses
    ``core.mapping.max_contracts_at`` + ``hysteresis_band_contracts`` and
    the explicit old-order clip instead of composing
    ``to_contracts`` (clip-first) with ``apply_hysteresis``. Direct
    score->contracts conversion without a band remains
    ``core.mapping.to_contracts`` (the live path, where clip order is
    immaterial)."""
    out: list[int] = []
    prev = 0
    cap = harness.cap
    for z, price in zip(z_series, close):
        if not math.isfinite(z) or price <= 0.0:
            out.append(prev)
            continue
        band_contracts = hysteresis_band_contracts(
            harness.band, cap, price, instrument, limits
        )
        raw = round(z / cap * max_contracts_at(price, instrument, limits))
        if abs(raw - prev) > band_contracts:
            prev = max(-limits.max_contracts, min(limits.max_contracts, raw))
        out.append(prev)
    return out


def _performance(pnl: list[float], bars_per_day: int) -> dict:
    """Daily-aggregated performance triple for one contract series."""
    daily = [sum(pnl[i : i + bars_per_day]) for i in range(0, len(pnl), bars_per_day)]
    return {
        "net_sharpe": alpha_core.sharpe_py(daily, bars_per_day=bars_per_day),
        "max_drawdown": alpha_core.max_drawdown_py(daily),
        "total_net_pnl": sum(daily),
    }


def _resolve(registry: Registry, name: str) -> object:
    """Registry lookup with the API's KeyError -> ValueError convention."""
    try:
        return registry.get(name)
    except KeyError as exc:
        raise ValueError(str(exc)) from None


def _instrument_for(bars: BarFrame) -> Instrument:
    """Resolve the bar window's instrument (bare symbol from the id)."""
    symbol = bars.instrument_id.split(".", 1)[0]
    return Instrument.load(symbol)


def _windows_mismatch(composite_window, bars_window) -> bool:
    """Field-by-field window comparison for the WindowMismatch guard."""
    return (
        composite_window.instrument_id != bars_window.instrument_id
        or composite_window.bar_type != bars_window.bar_type
        or composite_window.n_bars != bars_window.n_bars
        or composite_window.start != bars_window.start
        or composite_window.end != bars_window.end
    )


# --------------------------------------------------------------------------- #
# Entry points
# --------------------------------------------------------------------------- #


def backtest_portfolio(
    composite: Composite,
    bars: BarFrame,
    config: RiskBacktestConfig | None = None,
) -> RiskBacktestResult:
    """PORTFOLIO BACKTEST (position level): sizing -> policy -> PnL, run
    "before" (sizing only) and "after" (policy applied).

    Sizing and policy are resolved through the ``sizing_methods`` /
    ``risk_policies`` registries (real dispatch, defaults
    ``vol_target_drawdown`` / ``trigger_matrix``). The contract conversion
    goes through ``core.mapping`` (band hysteresis in contract units). The
    drawdown proxy and the intervention-cost math use the bar instrument's
    multiplier.

    Parameters
    ----------
    composite : Composite
        The combined composite (z-units); its ``window`` must equal
        ``bars.window``.
    bars : BarFrame
        The bar window (close feeds returns and marks).
    config : RiskBacktestConfig | None
        Defaults to ``RiskBacktestConfig()``.

    Returns
    -------
    RiskBacktestResult
        ``targets`` (the "after" TargetSeries artifact for execution), both
        SideReports, interventions, metrics diff, provenance.

    Raises
    ------
    WindowMismatch
        ``composite.window`` differs from ``bars.window``.
    ValueError
        Composite length mismatch, unknown sizing/policy names, or a
        sizing method returning malformed values.

    Notes
    -----
    Units: z-scores are z-units; positions are integer contracts (names end
    in ``_contracts``); money values carry the ``_vnd`` suffix; ``vol_target``
    and loss limits are fractions (0.02 == 2%); ``cost_drag_pct``-style
    outputs are percent.
    """
    cfg = config or RiskBacktestConfig()
    h = cfg.harness
    instrument = _instrument_for(bars)
    limits = cfg.limits
    multiplier = instrument.multiplier
    capital_vnd = limits.capital_vnd
    cost_per_side = instrument.cost.cost_per_side_frac

    if _windows_mismatch(composite.window, bars.window):
        raise WindowMismatch(
            f"composite window {composite.window} does not match bars window"
            f" {bars.window}; the composite must be built on exactly this"
            " bar window"
        )

    sizing_method = _resolve(sizing_methods, DEFAULT_SIZING)
    policy_method = _resolve(risk_policies, DEFAULT_POLICY)

    close = bars.close_list()
    ts = list(bars.ts.to_pydatetime())
    n = len(close)
    composite_list = [float(v) for v in composite.scores]
    if len(composite_list) != n:
        raise ValueError(
            f"composite length {len(composite_list)} != data bars {n};"
            " composite must be aligned with the data window"
        )

    returns = close_returns(close)
    vol_est = rolling_vol(close, VOL_EST_WINDOW, h.bars_per_day)

    # Sizing pass 1 (no overlay): position proxy for the drawdown estimate.
    z = sizing_methods.call(
        DEFAULT_SIZING, composite_list, vol_est, cfg.vol_target, None, cfg.vol_floor
    )
    if len(z) != n:
        raise ValueError(
            f"sizing method {DEFAULT_SIZING!r} returned {len(z)} values (expected {n})"
        )
    if not all(math.isfinite(value) for value in z):
        raise ValueError(f"sizing method {DEFAULT_SIZING!r} returned non-finite values")
    proxy = _z_to_contracts(z, close, h, instrument, limits)
    proxy_pnl = alpha_core.compute_pnl_py(proxy, returns, cost_per_side, h.bars_per_day).net
    dd = _drawdowns_from_pnl(list(proxy_pnl), close, capital_vnd, multiplier)

    # Sizing pass 2 WITH the drawdown overlay: the full sizing stack is
    # "before" (what the portfolio would do, no risk policy).
    z2 = sizing_methods.call(
        DEFAULT_SIZING, composite_list, vol_est, cfg.vol_target, dd, cfg.vol_floor
    )
    if len(z2) != n:
        raise ValueError(
            f"sizing method {DEFAULT_SIZING!r} returned {len(z2)} values (expected {n})"
        )
    if not all(math.isfinite(value) for value in z2):
        raise ValueError(f"sizing method {DEFAULT_SIZING!r} returned non-finite values")
    before = _z_to_contracts(z2, close, h, instrument, limits)
    before_pnl = alpha_core.compute_pnl_py(before, returns, cost_per_side, h.bars_per_day).net

    # Policy pass ("after"): risk lets a subset of the sized target through.
    ledger = RiskLedger(cfg.risk)
    after: list[int] = []
    interventions: list[dict] = []
    policy_reasons: Counter = Counter()
    prev_status = ACTIVE
    for t in range(n):
        result = risk_policies.call(
            DEFAULT_POLICY,
            PolicyInput(
                ts=ts[t],
                position=ledger.position,
                session_pnl=ledger.realized_pnl_vnd + ledger.marked_pnl_vnd,
                target=before[t],
                config=asdict(cfg.risk),
                ledger=ledger,
                price=close[t],
            ),
        )
        if result["reason"]:
            policy_reasons[result["reason"]] += 1
        if result["status"] != prev_status:
            interventions.append(
                {
                    "ts": ts[t].isoformat(),
                    "previous": prev_status,
                    "current": result["status"],
                    "reason": result["reason"] or "recovered",
                }
            )
            prev_status = result["status"]
        after.append(result["allowed_position"])

    after_pnl = alpha_core.compute_pnl_py(after, returns, cost_per_side, h.bars_per_day).net

    # Risk-process metrics:
    # - tracking error = |after - before| (policy-driven deviation),
    # - trigger counts = EVERY policy reason (status changes AND gate
    #   denials like exceeds-max-contracts / reducing-only),
    # - intervention cost = actual fill deltas of the after series
    #   (sum |after[t] - after[t-1]| over changes, priced at cost_per_side),
    # - max_abs_position per side.
    tracking = [abs(a - b) for a, b in zip(after, before)]
    fill_deltas = [
        abs(after[t] - after[t - 1])
        for t in range(1, len(after))
        if after[t] != after[t - 1]
    ]
    policy_cost = sum(
        d * cost_per_side * close[t] * multiplier
        for d, t in zip(fill_deltas, range(1, len(after)))
    )

    def _side(pnl_series, series, is_after: bool) -> SideReport:
        return SideReport(
            performance=_performance(list(pnl_series), h.bars_per_day),
            risk_process={
                "n_interventions": len(interventions) if is_after else 0,
                "intervention_cost_estimate_vnd": policy_cost if is_after else 0.0,
                "mean_abs_tracking_error": (
                    float(np.mean(tracking)) if (is_after and tracking) else 0.0
                ),
                "max_abs_position": max((abs(p) for p in series), default=0),
                "trigger_counts": dict(policy_reasons) if is_after else {},
            },
        )

    before_report = _side(before_pnl, before, is_after=False)
    after_report = _side(after_pnl, after, is_after=True)
    metrics_diff = {
        "net_sharpe": after_report.performance["net_sharpe"]
        - before_report.performance["net_sharpe"],
        "max_drawdown": after_report.performance["max_drawdown"]
        - before_report.performance["max_drawdown"],
    }
    targets = TargetSeries.from_arrays(
        ts=bars.ts,
        target_contracts=np.asarray(after, dtype=np.int64),
        window=composite.window,
        instrument=instrument,
    )
    provenance = {
        "sizing": DEFAULT_SIZING,
        "sizing_source": sizing_method.source,
        "policy": DEFAULT_POLICY,
        "policy_source": policy_method.source,
        "engine_version": getattr(alpha_core, "__version__", "unknown"),
    }
    return RiskBacktestResult(
        targets=targets,
        before=before_report,
        after=after_report,
        interventions=interventions,
        metrics_diff=metrics_diff,
        provenance=provenance,
    )


def divergence_gauges(spec: SpecSheet, live: dict) -> GaugeReport:
    """Divergence gauges comparing live behavior against the spec sheet.

    Each gauge is computed only from the inputs present; missing inputs
    yield value None with a reason. Bands:

    - gauge 1 (predictive IC vs ``spec.expected_ic``): standard-error bands
      (warning |v-e| > 2.5*se, critical > 4*se, se = 1/sqrt(n)) so the
      monitor's noise floor tracks the estimator's sampling noise. The
      horizon is the ladder entry with max |expected IC| (1 with expected
      0.0 when the sheet has no ladder); the spec-sheet IC is score_t vs
      forward returns t+1..t+h - a contemporaneous correlation would
      false-critical healthy signals.
    - gauge 2 (implementation shortfall vs ``spec.cost_model_bps``): ratio
      bands vs the cost model.
    - gauge 3 (position tracking error vs
      ``TRACKING_ERROR_BOUND_CONTRACTS``): the bound is an UPPER limit
      (healthy = value <= bound).
    - gauge 4 (fill rate vs ``FILL_RATE_EXPECTED``): a LOWER bound
      (0 fills = critical).

    Parameters
    ----------
    spec : SpecSheet
        Expectations (``expected_ic``, ``cost_model_bps``).
    live : dict
        Optional keys: ``score``, ``returns``, ``fills`` (each with
        price/decision_mid/side), ``current_positions``,
        ``target_positions``, ``orders``, ``n_fills``, ``feed_gaps``.

    Returns
    -------
    GaugeReport
        Gauges + overall escalation.
    """
    gauges: dict[str, dict] = {}
    expected_ic = getattr(spec, "expected_ic", None) or {}

    # Gauge 1: rolling PREDICTIVE IC vs spec expectation.
    score = live.get("score")
    returns = live.get("returns")
    if expected_ic:
        horizon_key = max(expected_ic, key=lambda h: abs(float(expected_ic[h])))
        horizon = int(horizon_key)
        exp = float(expected_ic[horizon_key])
    else:
        horizon = 1
        exp = 0.0
    if score is not None and returns is not None and len(score) == len(returns):
        if len(score) - horizon < 8:
            gauges["gauge_1"] = {
                "value": None,
                "status": "n/a",
                "note": "series too short for the requested horizon",
            }
        else:
            # Window: at least 480 bars, growing with the series so longer
            # samples reduce sampling noise.
            window = min(len(score) - horizon, max(480, (len(score) - horizon) // 4))
            x = np.asarray(score[-window:], dtype=float)
            y = np.asarray(returns[-window + horizon :], dtype=float)
            x = x[: len(y)]
            finite = np.isfinite(x) & np.isfinite(y)
            if int(finite.sum()) >= 8:
                rx = np.argsort(np.argsort(x[finite])).astype(float)
                ry = np.argsort(np.argsort(y[finite])).astype(float)
                rx -= rx.mean()
                ry -= ry.mean()
                denom = math.sqrt(float((rx * rx).sum() * (ry * ry).sum()))
                value = float((rx * ry).sum()) / denom if denom else 0.0
                n = int(finite.sum())
                se = 1.0 / math.sqrt(n) if n > 0 else 1.0
                diff = abs(value - exp)
                status = (
                    "ok"
                    if diff <= 2.5 * se
                    else ("warning" if diff <= 4.0 * se else "critical")
                )
                gauges["gauge_1"] = {
                    "value": value,
                    "expected": exp,
                    "status": status,
                    "note": f"se={se:.4f} (n={n})",
                }
            else:
                gauges["gauge_1"] = {"value": None, "status": "n/a", "note": "too few finite pairs"}
    else:
        gauges["gauge_1"] = {"value": None, "status": "n/a", "note": "score/returns missing"}

    # Gauge 2: implementation shortfall vs cost model, in basis points of
    # the reference price (shortfall = (fill - mid) * side / mid * 10000).
    fills = live.get("fills")
    if fills:
        shortfalls = [
            (float(f["price"]) - float(f["decision_mid"]))
            / float(f["decision_mid"])
            * (1 if f["side"] > 0 else -1)
            * 10_000.0
            for f in fills
            if f.get("decision_mid")
        ]
        if shortfalls:
            value = float(np.mean(shortfalls))
            gauges["gauge_2"] = _gauge(
                "implementation shortfall (bp)", value, float(spec.cost_model_bps)
            )
        else:
            gauges["gauge_2"] = {"value": None, "status": "n/a", "note": "no decision_mid in fills"}
    else:
        gauges["gauge_2"] = {"value": None, "status": "n/a", "note": "fills missing"}

    # Gauge 3: position tracking error vs design bound (UPPER limit).
    current = live.get("current_positions")
    target = live.get("target_positions")
    if current is not None and target is not None and len(current) == len(target):
        value = float(np.mean([abs(c - t) for c, t in zip(current, target)]))
        bound = TRACKING_ERROR_BOUND_CONTRACTS
        status = "ok" if value <= bound else ("warning" if value <= 2.0 * bound else "critical")
        gauges["gauge_3"] = {
            "value": value,
            "expected": bound,
            "status": status,
            "note": "bound is an upper limit",
        }
    else:
        gauges["gauge_3"] = {"value": None, "status": "n/a", "note": "position series missing"}

    # Gauge 4: fill rate (LOWER limit): 0 fills = critical operational
    # failure; below half the expected rate = critical.
    orders = live.get("orders")
    feed_gaps = int(live.get("feed_gaps", 0))
    if orders:
        n_orders = len(orders)
        n_fills = int(live.get("n_fills", sum(1 for f in fills or [])))
        exp = FILL_RATE_EXPECTED
        if n_orders == 0:
            gauges["gauge_4"] = {"value": None, "status": "n/a", "note": "no orders"}
        else:
            value = n_fills / n_orders
            if value <= 0.0:
                status = "critical"
            elif value < 0.5 * exp:
                status = "critical"
            elif value < exp:
                status = "warning"
            else:
                status = "ok"
            gauges["gauge_4"] = {
                "value": value,
                "expected": exp,
                "status": status,
                "note": "fill rate is a lower limit",
                "feed_gaps": feed_gaps,
            }
    else:
        gauges["gauge_4"] = {"value": None, "status": "n/a", "note": "orders missing"}

    statuses = [
        g["status"]
        for g in gauges.values()
        if g.get("status") in ("ok", "warning", "critical")
    ]
    escalation = "critical" if "critical" in statuses else ("warning" if "warning" in statuses else "none")
    return GaugeReport(gauges=gauges, escalation=escalation)


def _gauge(name: str, value: float | None, expected: float) -> dict:
    """Ratio-banded gauge: ok <= 0.5, warning <= 1.0, else critical of the
    distance to the expected value (absolute bands when expected == 0)."""
    if value is None:
        return {"value": None, "status": "n/a", "note": f"{name}: no data"}
    if expected == 0:
        status = "ok" if abs(value) <= 0.5 else ("warning" if abs(value) <= 1.0 else "critical")
    else:
        ratio = abs(value - expected) / abs(expected)
        status = "ok" if ratio <= 0.5 else ("warning" if ratio <= 1.0 else "critical")
    return {"value": value, "expected": expected, "status": status, "note": ""}


def post_mortem(session_dir: Path) -> SessionReport:
    """Session dissection: reads the session's decision log and risk
    transition log under ``session_dir`` and returns a structured timeline,
    loss-attribution notes and candidate recommendations (data only - never
    auto-applied).

    Parameters
    ----------
    session_dir : Path
        Directory holding ``decisions.jsonl`` and ``risk_transitions.jsonl``.

    Returns
    -------
    SessionReport
        Timeline (first 200 events), flip/gap counts, transition counts and
        recommendations.
    """
    d = Path(session_dir)
    events: list[dict] = []

    def _read_jsonl(name: str, kind: str) -> list[dict]:
        rows: list[dict] = []
        p = d / name
        if not p.exists():
            return rows
        for line in p.read_text().splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            row["_kind"] = kind
            rows.append(row)
        return rows

    decisions = _read_jsonl("decisions.jsonl", "decision")
    transitions = _read_jsonl("risk_transitions.jsonl", "risk_transition")
    events = sorted(
        decisions + transitions,
        key=lambda r: r.get("ts_ns", r.get("ts", 0)),
    )

    target_flips = 0
    big_gaps = 0
    last_target: int | None = None
    for e in decisions:
        t = e.get("target_contracts")
        if t is None:
            continue
        t = int(t)
        if last_target is not None and t != last_target:
            target_flips += 1
            if abs(t - last_target) >= 3:
                big_gaps += 1
        last_target = t

    transitions_by_status = Counter(
        (e.get("current"), e.get("reason")) for e in transitions if e.get("current")
    )
    reasons = [r for (_, r) in transitions_by_status if r]

    recommendations: list[dict] = []
    if REASON_LOSS in reasons:
        recommendations.append(
            {
                "gate": "tighten intraday loss limit or drawdown multiplier",
                "triggered_by": "intraday-loss-limit transitions observed",
            }
        )
    if REASON_STALE in reasons:
        recommendations.append(
            {"gate": "review staleness threshold", "triggered_by": "stale-feed transitions observed"}
        )
    if big_gaps >= 3:
        recommendations.append(
            {"gate": "review min_gap_contracts / cooldown", "triggered_by": f"{big_gaps} big target gaps"}
        )

    return SessionReport(
        session_dir=str(d),
        n_decision_events=len(decisions),
        n_risk_transitions=len(transitions),
        timeline=[{"ts_ns": e.get("ts_ns"), "kind": e["_kind"], "fields": e} for e in events[:200]],
        target_flips=target_flips,
        big_gap_moves=big_gaps,
        risk_transition_counts={f"{s}:{r}": n for (s, r), n in transitions_by_status.items()},
        recommendations=recommendations,
    )
