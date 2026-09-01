"""quant_api.risk - Quant Risk Researcher module (decision note DEC-017).

The risk role OWNS the sizing model (vol-target stack + leverage cap +
drawdown overlay -> target position) and the risk-overlay policies. The
core entry point is ``backtest_portfolio``: a POSITION-LEVEL PORTFOLIO
BACKTEST (vocabulary per DEC-017 - not a "replay") measuring performance
before and after exposure adjustment, always paired with risk-process
metrics so sizing models are not judged on performance alone (overfit
guard, DEC-017).

Extension slots (DEC-017): ``sizing_methods`` and ``risk_policies``.
Defaults delegate to the engine / to the live ``RiskLedger``; practitioners
register research methods as Python functions and migrate them after
validation. Reports are in-memory (never auto-saved).
"""

from __future__ import annotations

import json
import math
from collections import Counter
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path

import alpha_core
import numpy as np

from quant_api.core.artifacts import write_risk_overlay_config
from quant_api.core.config import DataConfig
from quant_api.core.data import close_volume, load_bars
from quant_api.core.registry import Registry
from trading.contracts import HarnessParams
from trading.risk.state import RiskConfig, RiskLedger

# --------------------------------------------------------------------------- #
# Extension registries
# --------------------------------------------------------------------------- #

#: Sizing slot. UNIFORM call convention for every method (engine defaults
#: and python-registered alike):
#: ``fn(z_scores, vol_est, target_vol, drawdowns=None, floor=None) -> list[float]``
sizing_methods = Registry("sizing_methods")


def _vol_target(z_scores, vol_est, target_vol, drawdowns=None, floor=None):
    """Engine-backed vol targeting (Component 5 - Position Construction)."""
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


sizing_methods.register("vol_target", _vol_target, source="engine")
sizing_methods.register("drawdown_overlay", _drawdown_overlay, source="engine")
sizing_methods.register("vol_target_drawdown", _vol_target_drawdown, source="engine")

#: Risk-policy slot. Custom policy contract (documented):
#: ``fn(policy_input: dict) -> dict`` with policy_input {"ts", "position",
#: "session_pnl", "target", "config"} returning {"status", "reason",
#: "allowed_position"}.
risk_policies = Registry("risk_policies")


def _trigger_matrix_policy(policy_input: dict) -> dict:
    """Offline policy application reusing the live ``RiskLedger`` trigger
    matrix (Component 7 - Risk Overlay and Monitoring layer 2/3).

    The ledger is driven per bar: fills for position deltas (realized PnL
    in VND), mark at the close, bar arrival, then ``decide()`` (loss limit,
    staleness - staleness cannot fire offline on a continuous bar feed -
    exposure cap) and ``gate()`` semantics: HALTED flattens, REDUCING only
    reduces, ACTIVE allows capped targets.
    """
    ledger: RiskLedger = policy_input["ledger"]
    ts: datetime = policy_input["ts"]
    price: float = policy_input["price"]
    target: int = policy_input["target"]

    ledger.on_bar(ts)
    ledger.mark(price, ts)
    state = ledger.decide()
    current = ledger.position

    if state.status == "HALTED":
        allowed = 0  # flatten
        reason = state.reason
    elif state.status == "REDUCING":
        allowed = min(abs(current), ledger.config.max_contracts) * (1 if current >= 0 else -1)
        reason = state.reason
    else:
        allowed_ok, gate_reason = ledger.gate(target, current)
        allowed = target if allowed_ok else current
        # Surface gate denials (exceeds-max-contracts / reducing-only) so
        # trigger_counts reflects every intervention, not just status changes.
        reason = gate_reason or state.reason

    delta = allowed - current
    if delta != 0:
        ledger.record_fill(price, delta, ts)
    return {"status": state.status, "reason": reason, "allowed_position": allowed}


risk_policies.register(
    "trigger_matrix",
    _trigger_matrix_policy,
    source="python",
    description="live RiskLedger trigger matrix (trading.risk.state)",
)


# --------------------------------------------------------------------------- #
# Configuration
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class RiskBacktestConfig:
    """Configuration for ``backtest_portfolio``."""

    harness: HarnessParams = field(default_factory=HarnessParams)
    vol_target: float = 0.1
    vol_floor: float | None = None
    risk: RiskConfig = field(default_factory=RiskConfig)
    capital_vnd: float = 100_000_000.0
    safety_factor: float = 0.5
    margin_rate: float = 0.05
    max_contracts: int = 10
    data: DataConfig | None = None


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def _close_returns(close: list[float]) -> list[float]:
    r = [0.0] * len(close)
    for t in range(1, len(close)):
        r[t] = close[t] / close[t - 1] - 1.0
    return r


def _rolling_vol(close: list[float], window: int, bars_per_day: int) -> list[float]:
    """Annualized rolling realized vol (same convention as the live
    orchestrator: ddof=1 sample std, sqrt(bars_per_day) scaling, 0.0 for
    windows with fewer than two samples)."""
    rets = _close_returns(close)
    scale = math.sqrt(bars_per_day)
    out: list[float] = []
    for t in range(len(rets)):
        win = rets[max(0, t - window + 1) : t + 1]
        if len(win) < 2:
            out.append(0.0)
            continue
        mean = sum(win) / len(win)
        var = sum((v - mean) * (v - mean) for v in win) / (len(win) - 1)
        out.append(math.sqrt(var) * scale)
    return out


def _drawdowns_from_pnl(pnl: list[float], close: list[float], capital_vnd: float) -> list[float]:
    """Proxy drawdown series: equity = 1 + cumsum(bar pnl in VND) / capital,
    drawdown = 1 - equity / running peak. Documented proxy for the ladder
    input (drawdown multiplier interprets fractions of initial equity)."""
    equity = 1.0
    peak = 1.0
    out: list[float] = []
    for bar_pnl, px in zip(pnl, close):
        equity += bar_pnl * px * 100_000.0 / capital_vnd
        peak = max(peak, equity)
        out.append(max(0.0, 1.0 - equity / peak) if peak > 0 else 0.0)
    return out


def _to_contracts(z_series: list[float], close: list[float], cfg: RiskBacktestConfig) -> list[int]:
    """DEC-008 conversion with the CANON no-trade band (Component 1 step C:
    dead-zone WITH hysteresis - hold the previous position while
    |new - prev| <= band; canonical_map applies the same rule in z units,
    this mirrors it in contract units). L_max =
    floor(capital*safety/(margin*price*100k)); contracts =
    round(z/cap*L_max) clipped to +/-max_contracts."""
    out: list[int] = []
    prev = 0
    for z, price in zip(z_series, close):
        if not math.isfinite(z) or price <= 0.0:
            out.append(prev)
            continue
        l_max = math.floor(
            cfg.capital_vnd * cfg.safety_factor / (cfg.margin_rate * price * 100_000.0)
        )
        band_c = max(1, round(cfg.harness.band / cfg.harness.cap * l_max))
        raw = round(z / cfg.harness.cap * l_max)
        if abs(raw - prev) > band_c:
            prev = max(-cfg.max_contracts, min(cfg.max_contracts, raw))
        out.append(prev)
    return out


def _performance(pnl: list[float], bars_per_day: int) -> dict:
    daily = [sum(pnl[i : i + bars_per_day]) for i in range(0, len(pnl), bars_per_day)]
    return {
        "net_sharpe": alpha_core.sharpe_py(daily, bars_per_day=bars_per_day),
        "max_drawdown": alpha_core.max_drawdown_py(daily),
        "total_net_pnl": sum(daily),
    }


# --------------------------------------------------------------------------- #
# Entry points
# --------------------------------------------------------------------------- #


def backtest_portfolio(
    composite: list[float],
    data: DataConfig | None = None,
    sizing: str = "vol_target_drawdown",
    policy: str = "trigger_matrix",
    config: RiskBacktestConfig | None = None,
) -> dict:
    """PORTFOLIO BACKTEST (position level): sizing -> policy -> PnL, run
    "before" (sizing only) and "after" (policy applied).

    Returns an in-memory report (never auto-saved): {"before", "after",
    "interventions", "metrics_before_after_diff"} - each side carries
    performance metrics AND risk-process metrics (overfit guard, DEC-017).
    """
    cfg = config or RiskBacktestConfig()
    eff_data = data or cfg.data or DataConfig()
    h = cfg.harness
    try:
        sizing_methods.get(sizing)
        risk_policies.get(policy)
    except KeyError as exc:
        raise ValueError(str(exc)) from None

    df = load_bars(eff_data)
    close, _ = close_volume(df)
    ts = df["ts"].dt.to_pydatetime().tolist()
    n = len(close)
    if len(composite) != n:
        raise ValueError(
            f"composite length {len(composite)} != data bars {n};"
            " composite must be aligned with the data window"
        )

    returns = _close_returns(close)
    vol_est = _rolling_vol(close, 20, h.bars_per_day)

    # Sizing pass 1 (no overlay): position proxy for the drawdown estimate.
    z = sizing_methods.call(sizing, list(composite), vol_est, cfg.vol_target, None, cfg.vol_floor)
    if len(z) != n:
        raise ValueError(f"sizing method {sizing!r} returned {len(z)} values (expected {n})")
    proxy = _to_contracts(z, close, cfg)
    proxy_pnl = alpha_core.compute_pnl_py(proxy, returns, h.cost_per_side, h.bars_per_day).net
    dd = _drawdowns_from_pnl(list(proxy_pnl), close, cfg.capital_vnd)

    # Sizing pass 2 WITH the drawdown overlay: the full sizing stack is
    # "before" (what the portfolio would do, no risk policy).
    z2 = sizing_methods.call(
        sizing, list(composite), vol_est, cfg.vol_target, dd, cfg.vol_floor
    )
    before = _to_contracts(z2, close, cfg)
    before_pnl = alpha_core.compute_pnl_py(before, returns, h.cost_per_side, h.bars_per_day).net

    # Policy pass ("after"): risk lets a subset of the sized target through.
    ledger = RiskLedger(cfg.risk)
    after: list[int] = []
    interventions: list[dict] = []
    policy_reasons: Counter = Counter()
    prev_status = "ACTIVE"
    for t in range(n):
        result = risk_policies.call(
            policy,
            {
                # Documented custom-policy keys (DEC-017 contract):
                "ts": ts[t],
                "position": ledger.position,
                "session_pnl": ledger.realized_pnl_vnd + ledger.marked_pnl_vnd,
                "target": before[t],
                "config": asdict(cfg.risk),
                # Internal keys used by the trigger_matrix policy:
                "ledger": ledger,
                "price": close[t],
            },
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

    after_pnl = alpha_core.compute_pnl_py(after, returns, h.cost_per_side, h.bars_per_day).net

    # Risk-process metrics (practitioner-review fixes):
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
    policy_cost = (
        sum(d * h.cost_per_side * close[t] * 100_000.0 for d, t in zip(fill_deltas, range(1, len(after))))
    )

    def _side(pnl_series, series, is_after: bool) -> dict:
        return {
            "performance": _performance(list(pnl_series), h.bars_per_day),
            "risk_process": {
                "n_interventions": len(interventions) if is_after else 0,
                "intervention_cost_estimate_vnd": policy_cost if is_after else 0.0,
                "mean_abs_tracking_error": (
                    float(np.mean(tracking)) if (is_after and tracking) else 0.0
                ),
                "max_abs_position": max((abs(p) for p in series), default=0),
                "trigger_counts": dict(policy_reasons) if is_after else {},
            },
        }

    report = {
        "before": _side(before_pnl, before, is_after=False),
        "after": _side(after_pnl, after, is_after=True),
        "interventions": interventions,
        "metrics_before_after_diff": {
            "net_sharpe": _side(after_pnl, after, True)["performance"]["net_sharpe"]
            - _side(before_pnl, before, False)["performance"]["net_sharpe"],
            "max_drawdown": _side(after_pnl, after, True)["performance"]["max_drawdown"]
            - _side(before_pnl, before, False)["performance"]["max_drawdown"],
        },
        "units": {
            "performance": "canonical PnL units (position x return per bar);"
            " net_sharpe/max_drawdown are scale-free ratios",
            "risk_process": "VND for costs; contracts for positions; counts for"
            " interventions/triggers",
        },
        "provenance": {
            "sizing": sizing,
            "sizing_source": sizing_methods.get(sizing).source,
            "policy": policy,
            "policy_source": risk_policies.get(policy).source,
            "engine_version": getattr(alpha_core, "__version__", "unknown"),
        },
    }
    return report


def divergence_gauges(expected: dict, live: dict) -> dict:
    """Component 7 - Risk Overlay and Monitoring gauges (section 3.4).

    Each gauge is computed only from the inputs present; missing inputs
    yield None with a reason. Bands (practitioner-review redesign):
    gauge 1 uses standard-error bands (warning |v-e| > 2.5*se, critical
    > 4*se, se = 1/sqrt(n)) so the monitor's noise floor tracks the
    estimator's sampling noise; gauge 2 uses ratio bands vs the cost model;
    gauge 3 treats the bound as an UPPER LIMIT (healthy = value <= bound);
    gauge 4 is a LOWER-bound fill rate (0 fills = critical).
    """
    gauges: dict[str, dict] = {}

    # Gauge 1: rolling PREDICTIVE IC vs spec expectation (spec-sheet IC is
    # score_t vs forward returns t+1..t+h, per the engine ic_ladder; a
    # contemporaneous correlation would false-critical healthy signals).
    score = live.get("score")
    returns = live.get("returns")
    horizon = int(expected.get("ic_horizon", 1))
    if score is not None and returns is not None and len(score) == len(returns):
        if len(score) - horizon < 8:
            gauges["gauge_1"] = {
                "value": None,
                "status": "n/a",
                "note": "series too short for the requested horizon",
            }
        else:
            # Window: at least 480 bars, growing with the series so longer
            # samples reduce sampling noise (canon: multiple of holding
            # period / 10 sessions).
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
                exp = float(expected.get("spec_ic", 0.0))
                n = int(finite.sum())
                se = 1.0 / math.sqrt(n) if n > 0 else 1.0
                diff = abs(value - exp)
                status = "ok" if diff <= 2.5 * se else ("warning" if diff <= 4.0 * se else "critical")
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

    # Gauge 2: implementation shortfall vs cost model, in basis points of the
    # reference price (shortfall = (fill - mid) * side / mid * 10000).
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
                "implementation shortfall (bp)", value, float(expected.get("cost_model_bps", 2.294))
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
        bound = float(expected.get("tracking_error_bound", 1.0))
        status = "ok" if value <= bound else ("warning" if value <= 2.0 * bound else "critical")
        gauges["gauge_3"] = {"value": value, "expected": bound, "status": status, "note": "bound is an upper limit"}
    else:
        gauges["gauge_3"] = {"value": None, "status": "n/a", "note": "position series missing"}

    # Gauge 4: fill rate (LOWER limit): 0 fills = critical operational
    # failure; below half the expected rate = critical.
    orders = live.get("orders")
    feed_gaps = int(live.get("feed_gaps", 0))
    if orders:
        n_orders = len(orders)
        n_fills = int(live.get("n_fills", sum(1 for f in fills or [])))
        exp = float(expected.get("fill_rate_expected", 0.95))
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

    statuses = [g["status"] for g in gauges.values() if g.get("status") in ("ok", "warning", "critical")]
    escalation = "critical" if "critical" in statuses else ("warning" if "warning" in statuses else "none")
    return {"gauges": gauges, "escalation": escalation}


def _gauge(name: str, value: float | None, expected: float) -> dict:
    if value is None:
        return {"value": None, "status": "n/a", "note": f"{name}: no data"}
    if expected == 0:
        status = "ok" if abs(value) <= 0.5 else ("warning" if abs(value) <= 1.0 else "critical")
    else:
        ratio = abs(value - expected) / abs(expected)
        status = "ok" if ratio <= 0.5 else ("warning" if ratio <= 1.0 else "critical")
    return {"value": value, "expected": expected, "status": status, "note": ""}


def post_mortem(session_dir: str, expected: dict | None = None) -> dict:
    """Session dissection (canon Component 7 feedback): reads the session's
    decision log and risk transition log under ``session_dir`` and returns a
    structured timeline, loss-attribution notes and candidate recommendations
    (data only - never auto-applied)."""
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
    if "intraday-loss-limit" in reasons:
        recommendations.append(
            {"gate": "tighten intraday loss limit or drawdown multiplier",
             "triggered_by": "intraday-loss-limit transitions observed"}
        )
    if "stale-feed" in reasons:
        recommendations.append(
            {"gate": "review staleness threshold", "triggered_by": "stale-feed transitions observed"}
        )
    if big_gaps >= 3:
        recommendations.append(
            {"gate": "review min_gap_contracts / cooldown", "triggered_by": f"{big_gaps} big target gaps"}
        )

    return {
        "session_dir": str(d),
        "n_decision_events": len(decisions),
        "n_risk_transitions": len(transitions),
        "timeline": [{"ts_ns": e.get("ts_ns"), "kind": e["_kind"], "fields": e} for e in events[:200]],
        "target_flips": target_flips,
        "big_gap_moves": big_gaps,
        "risk_transition_counts": {f"{s}:{r}": n for (s, r), n in transitions_by_status.items()},
        "recommendations": recommendations,
    }


def build_overlay_config(
    risk: RiskConfig | None = None,
    harness: HarnessParams | None = None,
    save: bool = True,
    root=None,
) -> dict:
    """Produce the validated live overlay payload (handoff artifact): the
    file is consumed by the live overlay wiring (DEC-017)."""
    payload = {
        "risk": asdict(risk or RiskConfig()),
        "harness": asdict(harness or HarnessParams()),
        "generated": datetime.now(timezone.utc).isoformat(),
        "provenance": {
            "engine_version": getattr(alpha_core, "__version__", "unknown"),
            "source": "quant_api.risk.build_overlay_config",
        },
    }
    if save:
        write_risk_overlay_config(payload, root=root)
    return payload
