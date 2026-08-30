# HANDOFF-001 - quant_core session handoff (v2: goal + progress tracker)

Snapshot for a fresh conversation. Read this file + the repo, then continue.
Branch: `feat/nautilus-live-wiring` (HEAD: clean tree, all work committed).

## 1. GOAL (the north star - what "done" means)

**Overarching goal**: run quant_core in production per the frozen lifecycle
(`docs/enhanced/framework-lifecycle.md`) - Phase 4 (paper execution) then
Phase 5 (live small + risk minimum). Components 0-5 (research engine) are
done; Components 6-7 infrastructure is wired; the remaining work is
verification on the demo, acceptance, calibration, then live.

**Current milestone M1 - multi-alpha portfolio paper execution on entrade demo.
Definition of done (all five):**

| # | Criterion | Verify by |
|---|---|---|
| 1 | entrade demo auth works | `apps/trading/check_auth.py` -> `AUTH OK` + investor id (BLOCKED now: 401) |
| 2 | Daily ETL first successful run | `apps/data/daily/pipeline.py` -> catalog populated, `[QC-DATA]` alert received |
| 3 | Paper run >= 1 full session, market hours | `apps/trading/paper.py` -> bars in, LO/MAK orders on demo, force-close 14:00, reconciliation clean, `[QC-TRADING]` alerts received |
| 4 | Acceptance report, 6 layers, PASS/FAIL with numbers | `apps/trading/acceptance.py` (NOT BUILT - see pending #4) |
| 5 | Cost parity: actual demo fees vs model | per-deal fee vs `cost_per_side=0.000229` (DEC-006) - first calibration point of the 7->1 loop |

**The 6-layer acceptance checklist (shop-grade research-live parity, agreed
in discussion, not yet implemented)** - one invariant per layer, measured
automatically:

- L0 data parity: live feed == research data (bars/gaps/dupes)
- L1 signal parity (CORE): same bars -> same decisions; live decision log
  diffed against offline replay through `PortfolioOrchestrator`; any diff = bug
- L2 execution parity: every target change -> exactly one order; throttle/
  cooldown/no-stacking respected; slippage per order
- L3 position parity: executed path follows target with <=1 order lag; flat
  after force-close; broker reconciliation clean
- L4 cost parity: actual fees vs model (DEC-006)
- L5 risk parity: state transitions per trigger matrix; flatten not stuck;
  alerts received

**After M1**: M2 = acceptance hardening + cost-model calibration; M3 = Phase 5
(live small + risk minimum - risk overlay is already built to live standard).

## 2. PROGRESS TRACKER (update as you work)

| Item | Status | Notes |
|---|---|---|
| Repo restructure (src/, rename alpha_core, per-package) | DONE | DEC-007, REC-007 |
| Milestone-1 wiring (contract, portfolio, bridge, risk) | DONE | DEC-008; tests 8/23/24 |
| Data sources DNSE + Mirae fallback | DONE | DEC-009; tests 6 |
| Telegram 2 channels + QC prefixes | DONE | DEC-011; bots NOT created yet (user) |
| Daily ETL LaunchAgent 16:00 Mon-Fri | DONE | installed, loaded |
| Commit convention + clean history | DONE | DEC-010 |
| entrade demo auth | BLOCKED | 401 INVALID_CREDENTIAL - see pending #1 |
| Daily ETL first run | PENDING | needs DNSE keys in .env |
| Paper E2E first session | PENDING | needs auth + market hours |
| Acceptance checklist discussion | IN PROGRESS | plan agreed; user wanted to re-discuss - continue here |
| Acceptance implementation (decision log + acceptance.py) | PENDING | agreed in principle |
| Cost calibration (7->1) | PENDING | after M1 |
| Live preparation (Phase 5) | FUTURE | C7 already live-standard |

## 3. System state (key facts)

- **Architecture**: `src/alpha-core` (Rust) + `src/alpha_core` (bindings) +
  `src/market_data` (DNSE+mirae ETL, Telegram transport) + `src/trading`
  (adapters, `PortfolioOrchestrator`, `BridgeStrategy` id `BridgeStrategy-bridge`,
  `RiskOverlayActor`). uv workspace; Nautilus v1.231.0 in `.venv`.
- **Facts**: entrade fee = 31,500 + 8.22*P VND round trip/contract, margin 5%
  (OBS-009/010); cost model `0.000229`/side @ ref 1,500 (DEC-006);
  `L_max = floor(capital*0.5/(0.05*price*100,000))`; contracts = round(z/cap*L_max);
  force-close 14:00 VN; bridge logs decisions only as log lines (structured
  per-bar decision log NOT yet added - needed for L1).
- **Env**: `.env` gitignored; `.env.example` template. Telegram pairs:
  `DATA_TELEGRAM_*` / `TRADING_TELEGRAM_*`.

## 4. Pending / blocked (priority order)

1. **entrade demo 401** (blocker): username format verified (10-digit numeric);
   endpoint/host verified. Hypotheses: wrong account type (entrade partnership
   account code, not DNSE securities account) / separate API-trading password /
   demo account expired (last verified 2026-07-20). Retest: `check_auth.py`.
2. **Daily ETL first run**: needs `API_KEY`/`API_SECRET`; manual run or wait
   for LaunchAgent 16:00.
3. **Paper E2E**: market hours only; dry-run verified.
4. **Acceptance**: (a) re-discuss checklist with user (start here - the 6-layer
   table above is the proposal), (b) then implement bridge per-bar decision
   log + `apps/trading/acceptance.py` (replay-diff report per layer).
5. Optional: OBS-011 binding NaN fix; two-part cost model (0.1575/P+0.0000411);
   instrument-helper dedup market_data/trading.

## 5. Session start protocol (self-check before trusting this note)

```sh
git status --short                     # expect empty
git log --oneline -4                   # expect c2415b8 ... (12 commits, DEC-010 format)
python3 scripts/sweep_ledger.py        # expect SWEEP OK, 0 drift
.venv/bin/python3 src/trading/tests/test_portfolio.py && \
.venv/bin/python3 src/trading/tests/test_bridge.py && \
.venv/bin/python3 src/trading/tests/test_risk.py && \
.venv/bin/python3 src/market_data/tests/test_daily.py && \
.venv/bin/python3 src/market_data/tests/test_notify.py
launchctl list | grep quant-core       # expect io.quant-core.daily-data-etl loaded
```
If any check fails, reconcile with the ledger (DEC/OBS/REC/TST) and git log
before proceeding; record findings as ledger notes per the governance rules.

## 6. Commands cheat-sheet

```sh
export CARGO_HOME="$PWD/.cargo-home" UV_CACHE_DIR="$PWD/.uv_cache" \
      PIP_CACHE_DIR="$PWD/.uv_cache/pip" PYO3_PYTHON="$PWD/.venv/bin/python3"
.venv/bin/python3 -m maturin develop --manifest-path src/alpha-core/Cargo.toml --features python-bindings
cargo test --manifest-path src/alpha-core/Cargo.toml
.venv/bin/python3 apps/trading/paper.py --dry-run
.venv/bin/python3 apps/trading/check_auth.py
.venv/bin/python3 apps/data/daily/pipeline.py [--date YYYY-MM-DD]
python3 scripts/sweep_ledger.py
```

## 7. Governance reminders

- `docs/enhanced/` is FROZEN - never edit; conflicts go to `docs/ledger/`.
- Ledger notes append-only after resolution; supersede, never rewrite.
- Commit convention DEC-010; amend/squash pre-push only.
- Never commit without an explicit owner order in the current session.
- Conversation handoffs are snapshots: update THIS file when state changes
  materially (new HANDOFF-002 for the next handover).
