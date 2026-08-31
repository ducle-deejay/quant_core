# HANDOFF-001 - quant_core session handoff (v2: goal + progress tracker)

Snapshot for a fresh conversation. Read this file + the repo, then continue.
Branch: `feat/nautilus-live-wiring` (HEAD: clean tree, all work committed).

## 1. GOAL (the north star - what "done" means)

**Collaboration contract (cách owner và agent làm việc - đọc kỹ trước khi làm):**

- Ngôn ngữ: tiếng Việt, xưng hô tao/mày; thuật ngữ quant/finance giữ tiếng Anh (owner đọc hiểu native, không dịch).
- Trả lời thẳng: câu đầu tiên trả lời đúng câu hỏi; không chào hỏi thừa, không restate yêu cầu, không closing summary trừ khi được hỏi.
- Ít jargon: từ viết tắt tối thiểu; abbreviation domain viết đầy đủ ở lần đầu tiên.
- Quy trình quyết định: agent đề xuất kèm rationale + số liệu -> owner duyệt -> mới thực thi. Không tự ý mở rộng scope, không tự quyết thay owner.
- Kỷ luật verify: mọi claim có evidence (test chạy, log, số liệu); chạy test suite + `sweep_ledger.py` trước khi báo "xong"; không báo xong khi chưa verify.
- Blocker: báo blocker kèm các giả thuyết đã loại + bước tiếp theo đề xuất; không im lặng, không đoán mò.
- Governance: `docs/enhanced/` FROZEN; ledger append-only (supersede, không sửa); sweep trước mọi commit; **commit chỉ khi owner ra lệnh trong phiên hiện tại**; commit convention DEC-010.
- Tiến độ: cập nhật Progress tracker (section 2) khi trạng thái đổi; tạo HANDOFF mới khi có thay đổi vật chất.
- Owner quyết định ưu tiên; agent hỏi khi mơ hồ thay vì đoán ý.

**Ultimate goal (north star, decision note DEC-014)**: a replicable, production-grade systematic-trading framework across assets and strategy styles - the framework is the product, VN30F1M is the current instantiation. Five invariants + anchor rule: top of AGENTS.md.

**Current instantiation path**: run quant_core in production per the frozen lifecycle
(`docs/enhanced/framework-lifecycle.md`) - Phase 4 (paper execution) then
Phase 5 (live small + risk minimum). Components 0-5 (research engine) are
done; Components 6-7 infrastructure is wired; the remaining work is
verification on the demo, acceptance, calibration, then live.

**Current milestone M1 - multi-alpha portfolio paper execution on entrade demo.
Definition of done (all five):**

| # | Criterion | Verify by |
|---|---|---|
| 1 | entrade demo auth works | `apps/trading/check_auth.py` -> `AUTH OK` + investor id (OK 2026-08-30, investor id 1000060107) |
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
| Telegram 2 channels + QC prefixes | DONE | DEC-011; bots NOT created yet (user) - alert delivery NOT tested yet |
| Telegram alert test | PENDING | user creates bots per approved convention: Data @quantcore_data_etl_bot, Trading @quantcore_trading_monitor_paper_bot (see .env.example), pastes token + chat id into .env, then test [QC-DATA]/[QC-TRADING] alerts - gate before next steps |
| Daily ETL LaunchAgent 16:00 Mon-Fri | DONE | installed, loaded |
| Commit convention + clean history | DONE | DEC-010 |
| entrade demo auth | DONE | AUTH OK 2026-08-30; investor id 1000060107; username = login email (not investor id) |
| Daily ETL first run | DONE | 2026-08-28: 241 bars / 89,565 trades / 593,874 book, gaps 0; Mirae backfill 473,773 bars (2018->2026-08-27); catalog populated; alert delivered 2026-08-30 |
| Telegram alert test | DONE | bots created per convention (Data @quantcore_data_etl_bot, Trading @quantcore_trading_monitor_paper_bot); chat ids fixed to 8214218868; smoke 9/9 delivered; unified format (DEC-012) |
| Alert coverage wave A | DONE | DEC-012/OBS-013/TST-009: bootstrap alerts, fail-loud entrypoint, heartbeat status + watcher LaunchAgent 16:10, smoke script |
| Paper E2E first session | READY | 2026-09-03 (thu 5): runbook docs/runbooks/paper-session-2026-09-03.md; pre-flight done (auth, dry-run, warmup window 7953 bars, smoke 9/9); manual start 08:45 VN |
| Acceptance checklist discussion | DONE | 6-layer checklist finalized 2026-08-30: parity (data, signal) vs engine audit (execution, position, cost, risk); owner-approved wording |
| Milestone-1 live corrections (DEC-013) | DONE | expiry-day force-close + 09-03 fake date, session windows, catalog warmup (7200/8000), decision log + risk transition log, Redis installed + backend verified (wheel has RedisCacheDatabase - no source build) |
| Acceptance implementation (decision log + acceptance.py) | DONE | bridge decision log + risk transition log + acceptance.py 6 checks + paper wiring (streaming/Redis/save-load); 178 tests green; runbook ready |
| North-star charter (AGENTS.md + DEC-014) | DONE | 2026-08-31: ultimate goal generalised to replicable framework across assets/strategy styles; five invariants + anchor rule; handoff protocol updated |
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
  `DATA_TELEGRAM_*` / `TRADING_TELEGRAM_*`; chat ids numeric (private
  8214218868), NOT bot usernames. Alert format unified (DEC-012): HTML
  parse-mode, header `<icon> QC-<DOMAIN> <EVENT> | <date> <time VN> | <verdict>`,
  inline `<code>` monospace body (no code box). Heartbeat status at
  `data/state/daily-etl-status.json`;
  watcher LaunchAgent `io.quant-core.daily-etl-watch` at 16:10 Mon-Fri.

## 4. Pending / blocked (priority order)

1. **Paper E2E first session**: market hours only - next trading day 2026-09-03
   (thu 5; VN holiday Mon 31-08 .. Wed 02-09). Runs `apps/trading/paper.py`;
   trading alerts (reject/deny/force-close/risk-state) get their first live
   test then.
2. **Acceptance**: (a) re-discuss checklist with user (start here - the 6-layer
   table above is the proposal), (b) then implement bridge per-bar decision
   log + `apps/trading/acceptance.py` (replay-diff report per layer).
3. **Alert wave B** (with acceptance): rolling volume baselines (30-day
   median), cross-source divergence DNSE vs Mirae, wrong-contract guard
   (DEC-012 deferred items).
4. Optional: OBS-011 binding NaN fix; two-part cost model (0.1575/P+0.0000411);
   instrument-helper dedup market_data/trading; quiet the catalog
   "already exists, skipping write" stdout noise.

## 5. Session start protocol (self-check before trusting this note)

```sh
# 0. Grounding check: read AGENTS.md Purpose + Ground truth sections; verify
#    goal statements against docs/enhanced/ before trusting any snapshot.
git status --short                     # expect empty
git log --oneline -4                   # expect c0efe02 ... (DEC-010 format)
python3 scripts/sweep_ledger.py        # expect SWEEP OK, 0 drift
.venv/bin/python3 src/trading/tests/test_portfolio.py && \
.venv/bin/python3 src/trading/tests/test_bridge.py && \
.venv/bin/python3 src/trading/tests/test_risk.py && \
.venv/bin/python3 src/trading/tests/test_notify.py && \
.venv/bin/python3 src/market_data/tests/test_daily.py && \
.venv/bin/python3 src/market_data/tests/test_notify.py && \
.venv/bin/python3 src/market_data/tests/test_heartbeat.py
launchctl print gui/$(id -u) | grep quant-core   # expect daily-data-etl + daily-etl-watch loaded
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
