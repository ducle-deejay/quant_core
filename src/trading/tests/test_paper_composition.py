"""Paper-runner composition + strategy save/load hook tests.

Covers the 2026-09-03 paper wiring in ``apps.trading.paper`` (feather
streaming subset, Redis cache backing, order/position snapshot flags,
``load_state``/``save_state``, per-session artifact paths) and the
``on_save``/``on_load`` state hooks on the bridge strategy and the risk
overlay actor. The hook contract was verified against the installed
nautilus_trader 1.231.0 wheel: the kernel calls ``Trader.save()/load()`` ->
``Cache.update_strategy/load_strategy`` -> the strategy's ``on_save``
(returns a plain dict) / ``on_load`` (receives the deserialized dict); the
hooks are NOT named ``on_save_state``/``on_load_state``.

Tests are derived from design intent, not current behaviour (ledger rule M4):
governing notes - DEC-008 (live wiring architecture), STG-6-TRADE-SCHEDULING
(force-close session state must survive a same-day restart), STG-7-RISK-OVERLAY
(an ACTIVE HALTED circuit breaker must survive restart; operator intervention
required, no silent re-arm).

Runs under pytest when available, and also as a plain assert runner:

    .venv/bin/python3 src/trading/tests/test_paper_composition.py
"""

from __future__ import annotations

import sys
import traceback
from datetime import datetime
from datetime import timezone
from pathlib import Path

from nautilus_trader.model.data import BarType
from nautilus_trader.serialization.arrow.serializer import list_schemas

_THIS_DIR = Path(__file__).resolve().parent
_SRC = _THIS_DIR.parents[2]  # src/trading/tests -> src
_REPO_ROOT = _THIS_DIR.parents[3]  # src/trading/tests -> repo root
sys.path.insert(0, str(_SRC))
sys.path.insert(0, str(_REPO_ROOT))

import apps.trading.paper as paper  # noqa: E402

from trading.portfolio import PortfolioOrchestrator  # noqa: E402
from trading.portfolio import default_seed_portfolio_config  # noqa: E402
from trading.risk.overlay import RiskOverlayActor  # noqa: E402
from trading.risk.overlay import RiskOverlayConfig  # noqa: E402
from trading.risk.overlay import apply_overlay_state  # noqa: E402
from trading.risk.overlay import format_overlay_state  # noqa: E402
from trading.risk.state import ACTIVE  # noqa: E402
from trading.risk.state import HALTED  # noqa: E402
from trading.risk.state import REASON_LOSS  # noqa: E402
from trading.risk.state import RiskConfig  # noqa: E402
from trading.risk.state import RiskLedger  # noqa: E402
from trading.strategies.bridge import BridgeConfig  # noqa: E402
from trading.strategies.bridge import BridgeStrategy  # noqa: E402
from trading.strategies.bridge import format_bridge_state  # noqa: E402
from trading.strategies.bridge import should_restore_session  # noqa: E402
from trading.strategies.bridge import vn_today_iso  # noqa: E402

UTC = timezone.utc

_BAR_TYPE = BarType.from_str("VN30F1M.HNX-1-MINUTE-LAST-EXTERNAL")


def _assert(cond: bool, msg: str) -> None:
    if not cond:
        raise AssertionError(msg)


def _make_bridge() -> BridgeStrategy:
    portfolio = PortfolioOrchestrator(config=default_seed_portfolio_config())
    return BridgeStrategy(
        BridgeConfig(
            instrument_id=str(_BAR_TYPE.instrument_id),
            bar_type=str(_BAR_TYPE),
            portfolio=portfolio,
            risk=None,
        ),
    )


def _make_actor() -> RiskOverlayActor:
    return RiskOverlayActor(RiskOverlayConfig(bar_type=_BAR_TYPE))


# --------------------------------------------------------------------------- #
# session artifact paths + node config wiring
# --------------------------------------------------------------------------- #


def test_session_artifacts_dir_path() -> None:
    expected = paper.ROOT / "data" / "logs" / "sessions" / paper.SESSION_DATE
    _assert(
        paper.session_artifacts_dir(paper.SESSION_DATE) == expected,
        f"session_artifacts_dir={paper.session_artifacts_dir(paper.SESSION_DATE)} "
        f"expected={expected}",
    )


def test_session_date_constant_is_2026_09_03() -> None:
    _assert(paper.SESSION_DATE == "2026-09-03", paper.SESSION_DATE)


def test_streamable_types_all_arrow_registered() -> None:
    # Every type in the streaming subset must have a registered Arrow schema
    # in the installed wheel, or the StreamingFeatherWriter cannot create a
    # writer for it (verified: all 11 are in the 54 registered schemas).
    schemas = list_schemas()
    missing = [cls.__name__ for cls in paper.STREAMABLE_TYPES if cls not in schemas]
    _assert(not missing, f"no Arrow schema registered for: {missing}")


def test_make_node_config_wires_streaming_redis_and_state() -> None:
    _, _, routing, data_client_config, exec_client_config = paper._client_configs(
        dry_run=True,
    )
    cfg = paper.make_node_config(
        routing=routing,
        data_client_config=data_client_config,
        exec_client_config=exec_client_config,
        persistence=True,
    )
    _assert(cfg.environment == paper.NAUTILUS_RUNTIME, str(cfg.environment))

    # Feather streaming: catalog path + the verified include_types subset.
    _assert(
        cfg.streaming is not None and cfg.streaming.catalog_path == str(paper.ROOT / "data" / "live"),
        f"streaming.catalog_path={cfg.streaming and cfg.streaming.catalog_path}",
    )
    _assert(
        list(cfg.streaming.include_types) == paper.STREAMABLE_TYPES,
        f"include_types={cfg.streaming.include_types}",
    )

    # Redis cache backing.
    _assert(cfg.cache is not None and cfg.cache.database is not None, "cache database unset")
    _assert(cfg.cache.database.type == "redis", cfg.cache.database.type)
    _assert(cfg.cache.database.host == "127.0.0.1", cfg.cache.database.host)
    _assert(cfg.cache.database.port == 6379, cfg.cache.database.port)

    # Execution snapshots + reconciliation kept on.
    _assert(cfg.exec_engine.reconciliation is True, "reconciliation")
    _assert(cfg.exec_engine.snapshot_positions is True, "snapshot_positions")
    _assert(cfg.exec_engine.snapshot_orders is True, "snapshot_orders")

    # Strategy state save/load flags.
    _assert(cfg.load_state is True, "load_state")
    _assert(cfg.save_state is True, "save_state")


def test_build_composition_dry_run_succeeds_and_wires_session() -> None:
    node = paper.build_composition(dry_run=True)
    _assert(node._config.cache.database is None, "dry-run connected persistence")
    _assert(node._config.streaming is None, "dry-run opened stream persistence")
    _assert(node._config.load_state is False, "dry-run loads persisted state")
    _assert(node._config.save_state is False, "dry-run saves persisted state")

    strategies = node.trader.strategies()
    bridges = [s for s in strategies if isinstance(s, BridgeStrategy)]
    actors = [s for s in strategies if isinstance(s, RiskOverlayActor)]
    _assert(len(bridges) == 1, f"bridges={len(bridges)}")
    _assert(len(actors) == 1, f"actors={len(actors)}")

    artifacts = paper.session_artifacts_dir(paper.SESSION_DATE)
    bridge = bridges[0]
    _assert(
        bridge.bridge_config.force_close_dates == [paper.SESSION_DATE],
        bridge.bridge_config.force_close_dates,
    )
    _assert(
        bridge.bridge_config.decision_log_path == str(artifacts / "decisions.jsonl"),
        bridge.bridge_config.decision_log_path,
    )
    actor = actors[0]
    _assert(
        actor.config.transition_log_path == str(artifacts / "risk_transitions.jsonl"),
        actor.config.transition_log_path,
    )
    node.dispose()


# --------------------------------------------------------------------------- #
# bridge session save/load hooks
# --------------------------------------------------------------------------- #


def test_format_bridge_state_shape() -> None:
    state = format_bridge_state(
        session_date=datetime(2026, 9, 3, tzinfo=UTC).date(),
        session_closed=True,
        last_submit_ns=1_700_000_000_123_456_789,
    )
    _assert(
        state == {
            "session_date": "2026-09-03",
            "session_closed": True,
            "last_submit_ns": 1_700_000_000_123_456_789,
        },
        f"state={state}",
    )


def test_format_bridge_state_none_session_date() -> None:
    state = format_bridge_state(session_date=None, session_closed=False, last_submit_ns=None)
    _assert(
        state == {"session_date": None, "session_closed": False, "last_submit_ns": None},
        f"state={state}",
    )


def test_should_restore_session_same_day() -> None:
    _assert(should_restore_session("2026-09-03", "2026-09-03") is True, "same day")


def test_should_restore_session_new_day() -> None:
    _assert(should_restore_session("2026-09-02", "2026-09-03") is False, "previous day")
    _assert(should_restore_session(None, "2026-09-03") is False, "no saved session")


def test_vn_today_iso_crosses_midnight() -> None:
    # 2026-09-03 00:30 VN == 2026-09-02 17:30 UTC.
    _assert(
        vn_today_iso(datetime(2026, 9, 2, 17, 30, tzinfo=UTC)) == "2026-09-03",
        "VN midnight crossing",
    )
    # 2026-09-03 06:30 VN == 2026-09-02 23:30 UTC.
    _assert(
        vn_today_iso(datetime(2026, 9, 2, 23, 30, tzinfo=UTC)) == "2026-09-03",
        "VN morning",
    )
    _assert(
        vn_today_iso(datetime(2026, 9, 2, 1, 30, tzinfo=UTC)) == "2026-09-02",
        "VN previous evening",
    )


def test_bridge_on_save_on_load_round_trip_same_day() -> None:
    today = vn_today_iso()
    strategy = _make_bridge()
    strategy._session_date = datetime.fromisoformat(today).date()
    strategy._session_closed = True
    strategy._last_submit_ns = 42

    saved = strategy.on_save()
    _assert(saved["session_date"] == today, saved)
    _assert(saved["session_closed"] is True, saved)
    _assert(saved["last_submit_ns"] == 42, saved)

    fresh = _make_bridge()
    fresh.on_load(saved)
    _assert(fresh._session_date == datetime.fromisoformat(today).date(), fresh._session_date)
    _assert(fresh._session_closed is True, fresh._session_closed)
    _assert(fresh._last_submit_ns == 42, fresh._last_submit_ns)


def test_bridge_on_load_stale_session_starts_fresh() -> None:
    fresh = _make_bridge()
    fresh.on_load(
        {
            "session_date": "1999-01-01",
            "session_closed": True,
            "last_submit_ns": 7,
        },
    )
    _assert(fresh._session_date is None, fresh._session_date)
    _assert(fresh._session_closed is False, fresh._session_closed)
    _assert(fresh._last_submit_ns is None, fresh._last_submit_ns)


def test_bridge_on_load_garbage_never_raises() -> None:
    fresh = _make_bridge()
    for state in (
        {"session_date": "not-a-date", "session_closed": True, "last_submit_ns": 1},
        {},
        None,
        {"session_date": "2026-09-03", "session_closed": "yes", "last_submit_ns": "x"},
    ):
        fresh.on_load(state)  # must not raise


# --------------------------------------------------------------------------- #
# risk overlay state save/load hooks
# --------------------------------------------------------------------------- #


def test_format_overlay_state_shape() -> None:
    ledger = RiskLedger(RiskConfig())
    ledger.status = HALTED
    ledger.reason = REASON_LOSS
    ledger.realized_pnl_vnd = -2_500_000.0
    ledger.position = 3
    ledger.avg_entry = 1_300.5
    ledger.last_price = 1_295.0
    ledger.last_bar_ts = datetime(2026, 9, 3, 7, 0, tzinfo=UTC)
    ledger.intraday_start_ts = datetime(2026, 9, 3, 0, 0, tzinfo=UTC)

    state = format_overlay_state(ledger, halted_latch=True)
    _assert(state["status"] == HALTED, state)
    _assert(state["reason"] == REASON_LOSS, state)
    _assert(state["halted_latch"] is True, state)
    _assert(state["realized_pnl_vnd"] == -2_500_000.0, state)
    _assert(state["marked_pnl_vnd"] == 0.0, state)
    _assert(state["position"] == 3, state)
    _assert(state["avg_entry"] == 1_300.5, state)
    _assert(state["last_price"] == 1_295.0, state)
    _assert(state["last_bar_ts"] == "2026-09-03T07:00:00+00:00", state)
    _assert(state["intraday_start_ts"] == "2026-09-03T00:00:00+00:00", state)


def test_apply_overlay_state_halted_latches() -> None:
    ledger = RiskLedger(RiskConfig())
    status, reason, halted = apply_overlay_state(
        ledger,
        {
            "status": HALTED,
            "reason": REASON_LOSS,
            "realized_pnl_vnd": -2_500_000.0,
            "position": 2,
        },
    )
    _assert(status == HALTED and reason == REASON_LOSS, (status, reason))
    _assert(halted is True, halted)
    _assert(ledger.status == HALTED, ledger.status)
    _assert(ledger.realized_pnl_vnd == -2_500_000.0, ledger.realized_pnl_vnd)
    _assert(ledger.position == 2, ledger.position)


def test_apply_overlay_state_active_no_latch() -> None:
    ledger = RiskLedger(RiskConfig())
    status, reason, halted = apply_overlay_state(ledger, {"status": ACTIVE, "reason": ""})
    _assert((status, reason, halted) == (ACTIVE, "", False), (status, reason, halted))
    _assert(ledger.status == ACTIVE, ledger.status)


def test_apply_overlay_state_garbage_falls_back_active() -> None:
    for state in ({"status": "BOGUS"}, {}, None):
        ledger = RiskLedger(RiskConfig())
        status, reason, halted = apply_overlay_state(ledger, state)  # never raises
        _assert((status, reason, halted) == (ACTIVE, "", False), (status, reason, halted))
    # Garbage numeric values fall back to defaults without raising; a valid
    # HALTED status still latches.
    ledger = RiskLedger(RiskConfig())
    status, reason, halted = apply_overlay_state(
        ledger,
        {"status": HALTED, "position": "x", "realized_pnl_vnd": "y"},
    )
    _assert((status, reason, halted) == (HALTED, "", True), (status, reason, halted))
    _assert(ledger.position == 0 and ledger.realized_pnl_vnd == 0.0, "numeric fallback")


def test_risk_on_save_on_load_round_trip() -> None:
    actor = _make_actor()
    actor._ledger.status = HALTED
    actor._ledger.reason = REASON_LOSS
    actor._ledger.realized_pnl_vnd = -2_500_000.0
    actor._ledger.position = 4
    actor._ledger.avg_entry = 1_300.0
    actor._ledger.last_price = 1_290.0
    actor._halted_latch = True

    saved = actor.on_save()
    _assert(saved["status"] == HALTED and saved["halted_latch"] is True, saved)

    fresh = _make_actor()
    fresh.on_load(saved)
    _assert(fresh._halted_latch is True, fresh._halted_latch)
    _assert(fresh._ledger.status == HALTED, fresh._ledger.status)
    _assert(fresh._ledger.reason == REASON_LOSS, fresh._ledger.reason)
    _assert(fresh._ledger.realized_pnl_vnd == -2_500_000.0, fresh._ledger.realized_pnl_vnd)
    _assert(fresh._ledger.position == 4, fresh._ledger.position)
    _assert(fresh._ledger.avg_entry == 1_300.0, fresh._ledger.avg_entry)
    _assert(fresh._ledger.last_price == 1_290.0, fresh._ledger.last_price)


def test_risk_on_load_halted_stays_halted_after_evaluate() -> None:
    # A persisted loss halt whose loss is *below* the limit: the pure core's
    # decide() would re-arm to ACTIVE, but the restored latch must pin HALTED
    # (operator intervention required - no silent re-arm after restart).
    actor = _make_actor()
    actor.on_load(
        {
            "status": HALTED,
            "reason": REASON_LOSS,
            "realized_pnl_vnd": -1_000_000.0,  # below the 2% x 100M loss limit
        },
    )
    _assert(actor._halted_latch is True, actor._halted_latch)
    _assert(actor._ledger.status == HALTED, actor._ledger.status)

    # Prove the underlying ledger would re-arm on its own (decide() mutates
    # the ledger, which is exactly what the latch must override).
    _assert(actor._ledger.decide().status == ACTIVE, "ledger.decide() re-armed")

    actor._evaluate()
    _assert(actor._ledger.status == HALTED, f"status after evaluate: {actor._ledger.status}")
    _assert(actor._last_state.status == HALTED, actor._last_state.status)

    # The gate must keep denying everything while latched.
    allowed, reason = actor.gate(paper_portfolio_target())
    _assert(allowed is False, f"gate allowed: {reason}")


def test_risk_on_load_garbage_never_raises() -> None:
    actor = _make_actor()
    for state in (None, {}, {"status": "BOGUS"}):
        actor.on_load(state)  # must not raise
    _assert(actor._halted_latch is False, actor._halted_latch)
    # Garbage numeric values never raise; a valid HALTED status still latches.
    actor.on_load({"status": HALTED, "position": "x", "realized_pnl_vnd": "y"})
    _assert(actor._halted_latch is True, actor._halted_latch)
    _assert(actor._ledger.position == 0 and actor._ledger.realized_pnl_vnd == 0.0, "numeric fallback")


def paper_portfolio_target():
    """A TargetPosition for gate tests (flat -> 1 long)."""
    from trading.contracts import TargetPosition

    return TargetPosition(
        ts=datetime(2026, 9, 3, 7, 0, tzinfo=UTC),
        target_contracts=1,
        z_target=0.5,
        reason="test",
    )


# --------------------------------------------------------------------------- #
# plain assert runner (pytest is not installed in .venv)
# --------------------------------------------------------------------------- #


def _run_all() -> int:
    tests = [
        (name, fn)
        for name, fn in sorted(globals().items())
        if name.startswith("test_") and callable(fn)
    ]
    failures = 0
    for name, fn in tests:
        try:
            fn()
            print(f"PASS {name}")
        except Exception:  # noqa: BLE001 - plain runner reports every failure
            failures += 1
            print(f"FAIL {name}")
            traceback.print_exc()
    total = len(tests)
    print(f"\n{total - failures}/{total} tests passed")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(_run_all())
