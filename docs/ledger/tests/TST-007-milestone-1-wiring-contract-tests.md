---
doc_id: TST-007
title: Milestone-1 wiring contract tests - portfolio orchestrator, bridge strategy, risk overlay
type: test-mapping
owner: research
status: resolved
version: 1.0
components: [5, 6, 7]
tags: [tests, wiring, milestone-1, contracts]
source: "test suites written by the three milestone-1 workstreams, 2026-08-30"
design: [STG-1-CANONICAL-SIM, STG-5-POSITION-CONSTRUCTION, STG-6-TRADE-SCHEDULING, STG-7-RISK-OVERLAY]
code: [src/trading/portfolio.py, src/trading/strategies/bridge.py, src/trading/risk/state.py, src/trading/risk/overlay.py, src/trading/contracts.py]
test: [src/trading/tests/test_portfolio.py, src/trading/tests/test_bridge.py, src/trading/tests/test_risk.py]
---

# TST-007 - Milestone-1 Wiring Contract Tests

## 1. What is protected

| Suite | Count | Protects |
|---|---|---|
| `src/trading/tests/test_portfolio.py` | 8 | DEC-008 contract mapping (`z/cap * L_max`, bounds), STG-1 parity (one `execute_batch_py` call, canonical mapping per alpha, Python-side sanitize mirroring OBS-011), STG-5 vol targeting, seed-expression validity |
| `src/trading/tests/test_bridge.py` | 23 | STG-6 decision order (force-close -> target -> gate -> cooldown -> gap -> no-stacking), LO/MAK construction semantics, deterministic client order ids, warmup window, force-close 14:00 boundary + day rollover |
| `src/trading/tests/test_risk.py` | 24 | STG-7 trigger matrix (intraday loss limit -2,000,000 VND, stale feed > 60 s, exposure cap 10 contracts), gate semantics under ACTIVE/HALTED/REDUCING, flatten retry loop, session helpers |

Tests are pytest-compatible plain assert runners (pytest is not installed in the project venv); canonical invocation: `.venv/bin/python3 src/trading/tests/test_<suite>.py`.

## 2. Governing notes

- DEC-008 (wiring architecture), DEC-006 (cost model), OBS-009/OBS-010 (entrade margin 5%, multiplier 100,000), OBS-011 (sanitize mirror), canon STG-1/5/6/7.
- Test source comments cite the governing note ids per ledger rule M4.

## Related notes

- [DEC-008](DEC-008-live-wiring-architecture.md)
- [OBS-011](OBS-011-canonical-map-binding-nan.md)
