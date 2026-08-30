---
doc_id: DEC-013
title: Milestone-1 live corrections - expiry semantics, session windows, catalog warmup, observability logs, Redis persistence
type: decision
owner: research
status: resolved
version: 1.0
components: [5, 6, 7]
tags: [expiry, warmup, catalog, session, decision-log, redis, milestone-1]
source: "owner-approved milestone-1 review wave, 2026-08-30"
design: [STG-5-POSITION-CONSTRUCTION, STG-6-TRADE-SCHEDULING, STG-7-RISK-OVERLAY]
code: [src/trading/strategies/bridge.py, src/trading/adapters/dnse/data.py, src/trading/adapters/dnse/config.py, src/trading/risk/overlay.py, apps/trading/paper.py]
test: [src/trading/tests/test_bridge.py, src/trading/tests/test_dnse_data.py, src/trading/tests/test_risk_overlay_log.py]
---

# DEC-013 - Milestone-1 Live Corrections

## 1. Decision

Five corrections land together for the milestone-1 paper run (owner-approved,
2026-08-30):

1. **Expiry-day semantics** (OBS-014): force-close only on configured expiry
   dates (`force_close_dates`, VN-local ISO dates; empty = never); on an
   expiry day before 14:00 only position-reducing orders are allowed
   (`is_expiry_day_entry_blocked`: blocked iff
   `abs(current + delta) >= abs(current)`); same-day re-entry is blocked by the
   session-closed flag; the next VN day re-arms normally. The 2026-09-03 paper
   session declares `force_close_dates=["2026-09-03"]` to exercise the expiry
   path without waiting for the real contract expiry.
2. **Session windows**: new orders only inside VN windows
   `[09:00, 11:30)` and `[13:00, 14:30)` (`session_windows` config, half-open)
   - no orders into the opening auction, lunch break, or closing auction. The
   force-close branch runs before the window check and is unaffected.
3. **Warmup from the research catalog**: `historical_source="catalog"`
   (default) on the DNSE data client serves `request_bars` history from
   `ParquetDataCatalog` (data/catalog) - the same canonical data research uses,
   avoiding the holey DNSE history API; empty/failed catalog reads fall back to
   the API with a warning. Warmup depth raised to 7200 bars (30 sessions) with
   `buffer_bars=8000` so the sliding window holds a full month of 1-minute
   bars. Verified: catalog and API paths timestamp bars at bar-open UTC with
   identical ts_event semantics (0/16 sample mismatches).
4. **Observability logs** for the acceptance layers: a per-bar decision log
   (`decision_log_path`, JSONL: ts_event_ns, clock_ns, close, target,
   current_contracts, action, reason) on every bridge exit path, and a
   risk-state transition log (`transition_log_path`, JSONL: ts_ns, previous,
   current, reason) anchored by a startup record. Both are best-effort writers
   that never raise.
5. **State persistence via Redis** (restart must not clear a circuit breaker):
   the installed nautilus wheel already contains the Redis backend
   (`nautilus_pyo3.RedisCacheDatabase` - verified; `RedisMessageBus` does not
   exist in the wheel, so the message bus stays in-memory). Redis server
   installed via Homebrew (owner choice; Nautilus docs recommend Docker, not
   available on this machine). Paper wiring: `CacheConfig(database=
   DatabaseConfig(type="redis", host, port))`, order/position snapshots, and
   kernel load/save-state hooks so bridge session flags and the risk state
   machine (including an active circuit breaker) survive a process restart.

## 2. Rationale

- Futures shops manage expiry calendar-driven: flatten before settlement, block
  new entries on the expiring contract, re-enter the next contract next
  session. The daily 14:00 flatten was a wiring regression (OBS-014).
- Warmup from the canonical catalog makes the input level of research/live
  parity trivially true (same bars) and removes the holey-API risk.
- Redis state persistence is the debt item from the previous wiring: a restart
  mid-crisis must not forget a loss-limit halt.

## 3. Impact

- Bridge: no daily flatten; expiry-day reduce-only entries; window-gated
  submissions; decision log per bar.
- Data client: warmup defaults to catalog with API fallback.
- Risk overlay: transition log only (no behavior change).
- Phase-2 wiring (paper.py) and the acceptance report consume these artifacts.
