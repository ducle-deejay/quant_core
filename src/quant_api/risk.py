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
    elif state.status == "REDUCING":
        allowed = min(abs(current), ledger.config.max_contracts) * (1 if current >= 0 else -1)
    else:
        allowed_ok, reason = ledger.gate(target, current)
        allowed = target if allowed_ok else current

    delta = allowed - current
    if delta != 0:
        ledger.record_fill(price, delta, ts)
    return {"status": state.status, "reason": state.reason, "allowed_position": allowed}


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
    """DEC-008 conversion: L_max = floor(capital*safety/(margin*price*100k)),
    contracts = round(z/cap*L_max) clipped to +/-max_contracts."""
    out: list[int] = []
    for z, price in zip(z_series, close):
        if not math.isfinite(z) or price <= 0.0:
            out.append(0)
            continue
        l_max = math.floor(
            cfg.capital_vnd * cfg.safety_factor / (cfg.margin_rate * price * 100_000.0)
        )
        raw = z / cfg.harness.cap * l_max
        out.append(max(-cfg.max_contracts, min(cfg.max_contracts, round(raw))))
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

    # Sizing -> z, then raw contracts ("before" = sizing only).
    z = sizing_methods.call(sizing, list(composite), vol_est, cfg.vol_target, None, cfg.vol_floor)
    if len(z) != n:
        raise ValueError(f"sizing method {sizing!r} returned {len(z)} values (expected {n})")
    before = _to_contracts(z, close, cfg)
    before_pnl = alpha_core.compute_pnl_py(before, returns, h.cost_per_side, h.bars_per_day).net
    dd = _drawdowns_from_pnl(list(before_pnl), close, cfg.capital_vnd)

    # Re-apply sizing WITH drawdowns (the overlay needs the PnL proxy).
    z2 = sizing_methods.call(
        sizing, list(composite), vol_est, cfg.vol_target, dd, cfg.vol_floor
    )
    target_series = _to_contracts(z2, close, cfg)

    # Policy pass ("after").
    ledger = RiskLedger(cfg.risk)
    after: list[int] = []
    interventions: list[dict] = []
    prev_status = "ACTIVE"
    for t in range(n):
        result = risk_policies.call(
            policy,
            {
                "ledger": ledger,
                "ts": ts[t],
                "price": close[t],
                "target": target_series[t],
                "session_pnl": 0.0,
            },
        )
        if result["status"] != prev_status:
            interventions.append(
                {
                    "ts": ts[t].isoformat(),
                    "previous": prev_status,
                    "current": result["status"],
                    "reason": result["reason"],
                }
            )
            prev_status = result["status"]
        after.append(result["allowed_position"])
    if interventions and interventions[-1]["reason"] == "":
        interventions[-1]["reason"] = "startup" if len(interventions) == 1 else ""

    after_pnl = alpha_core.compute_pnl_py(after, returns, h.cost_per_side, h.bars_per_day).net

    # Risk-process metrics.
    tracking = [abs(a - b) for a, b in zip(after, before)]
    triggers = Counter(i["reason"] for i in interventions if i["reason"])
    policy_cost = sum(
        abs(a - b) * h.cost_per_side * close[t] * 100_000.0
        for t, (a, b) in enumerate(zip(after, before))
    )

    def _side(pnl_series) -> dict:
        return {
            "performance": _performance(list(pnl_series), h.bars_per_day),
            "risk_process": {
                "n_interventions": len(interventions),
                "intervention_cost_estimate_vnd": policy_cost,
                "mean_abs_tracking_error": float(np.mean(tracking)) if tracking else 0.0,
                "max_abs_position": max((abs(p) for p in after), default=0),
                "trigger_counts": dict(triggers),
            },
        }

    report = {
        "before": _side(before_pnl),
        "after": _side(after_pnl),
        "interventions": interventions,
        "metrics_before_after_diff": {
            "net_sharpe": _side(after_pnl)["performance"]["net_sharpe"]
            - _side(before_pnl)["performance"]["net_sharpe"],
            "max_drawdown": _side(after_pnl)["performance"]["max_drawdown"]
            - _side(before_pnl)["performance"]["max_drawdown"],
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
    yield None with a reason. First-pass bands (documented heuristics):
    warning when |value - expected| > 0.5 * expected, critical when
    > 1.0 * expected (absolute bands when expected is 0).
    """
    gauges: dict[str, dict] = {}

    # Gauge 1: rolling IC vs spec expectation.
    score = live.get("score")
    returns = live.get("returns")
    if score is not None and returns is not None and len(score) == len(returns):
        window = min(480, len(score))
        x = np.asarray(score[-window:], dtype=float)
        y = np.asarray(returns[-window:], dtype=float)
        finite = np.isfinite(x) & np.isfinite(y)
        if int(finite.sum()) >= 8:
            rx = np.argsort(np.argsort(x[finite])).astype(float)
            ry = np.argsort(np.argsort(y[finite])).astype(float)
            rx -= rx.mean()
            ry -= ry.mean()
            denom = math.sqrt(float((rx * rx).sum() * (ry * ry).sum()))
            value = float((rx * ry).sum()) / denom if denom else 0.0
            exp = float(expected.get("spec_ic", 0.0))
            gauges["gauge_1"] = _gauge("rolling IC", value, exp)
        else:
            gauges["gauge_1"] = {"value": None, "status": "n/a", "note": "too few finite pairs"}
    else:
        gauges["gauge_1"] = {"value": None, "status": "n/a", "note": "score/returns missing"}

    # Gauge 2: implementation shortfall vs cost model.
    fills = live.get("fills")
    if fills:
        shortfalls = [
            (float(f["price"]) - float(f["decision_mid"])) * (1 if f["side"] > 0 else -1) * 10_000.0
            for f in fills
            if "decision_mid" in f
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

    # Gauge 3: position tracking error vs design bound.
    current = live.get("current_positions")
    target = live.get("target_positions")
    if current is not None and target is not None and len(current) == len(target):
        value = float(np.mean([abs(c - t) for c, t in zip(current, target)]))
        gauges["gauge_3"] = _gauge(
            "position tracking error (contracts)", value, float(expected.get("tracking_error_bound", 1.0))
        )
    else:
        gauges["gauge_3"] = {"value": None, "status": "n/a", "note": "position series missing"}

    # Gauge 4: fill rate / rejects / latency / feed gaps.
    orders = live.get("orders")
    feed_gaps = int(live.get("feed_gaps", 0))
    if orders:
        n_orders = len(orders)
        n_fills = int(live.get("n_fills", sum(1 for f in fills or [])))
        value = n_fills / n_orders if n_orders else None
        exp = float(expected.get("fill_rate_expected", 0.95))
        g4 = _gauge("fill rate", value, exp)
        g4["feed_gaps"] = feed_gaps
        gauges["gauge_4"] = g4
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
