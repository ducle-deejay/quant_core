# HANDOFF-001 - quant_core session handoff

Snapshot for a fresh conversation. Read this file + the repo, then continue.
Branch: `feat/nautilus-live-wiring` (HEAD: clean tree, all work committed).

## How to use this note

1. `git log --oneline -15` for the history; ledger notes (DEC/OBS/REC/TST under
   `docs/ledger/`) are the authoritative decision record - read them before
   touching any contract.
2. Run `python3 scripts/sweep_ledger.py` before committing (pre-commit hook
   enforces it too). Commit convention: DEC-010 `<type>(<scope>): <summary>`.
3. `.env` holds real credentials (gitignored); `.env.example` is the template.

## System state (what exists)

- **Architecture**: `src/alpha-core` (Rust engine, crate) + `src/alpha_core`
  (Python bindings, research API) + `src/market_data` (DNSE primary + Mirae
  fallback ETL, Telegram transport) + `src/trading` (entrade/dnse adapters,
  portfolio orchestrator, bridge strategy, risk overlay, paper runner).
  uv workspace, per-package pyprojects. Nautilus Trader v1.231.0 in `.venv`.
- **Milestone-1 wiring complete** (DEC-008): contracts (`src/trading/contracts.py`),
  `PortfolioOrchestrator` (6 seed expressions, pure alpha_core), `BridgeStrategy`
  (id `BridgeStrategy-bridge`, LO default / MAK, force-close 14:00 VN),
  `RiskOverlayActor` (C7 full: loss limit -2M VND, staleness >60s, exposure cap
  10, flatten retry, ACTIVE/HALTED/REDUCING). Tests: portfolio 8, bridge 23,
  risk 24, daily 6, notify 4 - all green.
- **Data**: daily ETL DNSE-first + Mirae fill-gaps (fixed semantics: coverage
  judged after both sources, DEC-009); LaunchAgent `io.quant-core.daily-data-etl`
  installed, Mon-Fri 16:00 Asia/Ho_Chi_Minh.
- **Alerts**: two Telegram channels (DEC-011) - `DATA_TELEGRAM_BOT_TOKEN/CHAT_ID`
  (data, prefix `[QC-DATA]`) and `TRADING_TELEGRAM_BOT_TOKEN/CHAT_ID`
  (trading, prefix `[QC-TRADING] [PAPER]`). Bots not created yet (user task).
- **Facts**: entrade fee = 31,500 + 8.22*P VND round trip/contract, margin 5%
  (OBS-009/010); milestone-1 cost model `cost_per_side = 0.000229` @ ref price
  1,500 (DEC-006); L_max = floor(capital*0.5/(0.05*price*100,000));
  contracts = round(z/cap*L_max).

## Pending / blocked (in priority order)

1. **entrade demo auth: 401 INVALID_CREDENTIAL** (blocker for paper E2E).
   Username format verified correct (10-digit numeric like docs example
   "1000000001"); endpoint/host verified (`/entrade-api/v2/auth` on
   services.entrade.com.vn). Remaining hypotheses: (a) wrong account type
   (must be the entrade partnership account code, not DNSE securities
   account), (b) separate API/trading password, (c) demo account expired
   (last verified 2026-07-20). Retest with
   `apps/trading/check_auth.py` after any change; success prints
   `ENTRADE_INVESTOR_ID=...` for `.env`.
2. **Daily ETL first run**: needs `API_KEY`/`API_SECRET` (DNSE) in `.env`.
   Manual: `.venv/bin/python3 apps/data/daily/pipeline.py [--date YYYY-MM-DD]`
   (can backfill past days). Auto: LaunchAgent 16:00 Mon-Fri.
3. **Paper E2E**: `.venv/bin/python3 apps/trading/paper.py` during VN market
   hours (09:00-14:45). Dry-run verified only (`--dry-run`).
4. **Acceptance checklist discussion NOT finished**: the shop-grade 6-layer
   research-live parity plan was presented (data parity, signal parity replay
   [core invariant], execution parity, position parity, cost parity, risk
   parity) but NOT yet implemented. Two implementation items agreed in
   principle: (a) bridge per-bar decision log, (b) `apps/trading/acceptance.py`
   replay-and-diff report. User wanted to re-discuss the checklist; the
   conversation ended before that discussion - START HERE with the checklist
   (see the plan in the session: layer table with invariants).
5. **Optional follow-ups**: OBS-011 binding NaN fix candidate (canonical_map_py
   vs Rust core sanitize); two-part price-dependent cost model after wiring
   (0.1575/P + 0.0000411); market-data/trading instrument-helper duplication.

## Commands cheat-sheet

```sh
export CARGO_HOME="$PWD/.cargo-home" UV_CACHE_DIR="$PWD/.uv_cache" \
      PIP_CACHE_DIR="$PWD/.uv_cache/pip" PYO3_PYTHON="$PWD/.venv/bin/python3"
.venv/bin/python3 -m maturin develop --manifest-path src/alpha-core/Cargo.toml --features python-bindings
cargo test --manifest-path src/alpha-core/Cargo.toml
.venv/bin/python3 apps/trading/paper.py --dry-run
.venv/bin/python3 apps/trading/check_auth.py
python3 scripts/sweep_ledger.py
```

## Governance reminders

- `docs/enhanced/` is FROZEN - never edit; conflicts go to `docs/ledger/`.
- Ledger notes are append-only after resolution; supersede, never rewrite.
- Commit messages: conventional commits per DEC-010; amend/squash pre-push only.
- Never commit without an explicit owner order in the current session.
