---
doc_id: OBS-011
title: canonical_map_py binding rejects warmup NaN that the Rust core sanitizes by contract
type: observation
owner: research
status: resolved
version: 1.0
components: [0, 1]
tags: [python-bindings, nan, warmup, parity, live-wiring]
source: "workstream A (portfolio orchestration) during milestone-1 wiring, 2026-08-30"
design: [STG-1-CANONICAL-SIM]
code: [src/alpha-core/src/python_bindings/canonical.rs, src/alpha-core/src/canonical/mapping.rs, src/trading/portfolio.py]
test: [src/trading/tests/test_portfolio.py]
---

# OBS-011 - canonical_map_py Rejects Warmup NaN the Rust Core Sanitizes

## 1. Finding

The Python binding `canonical_map_py` raises `ValueError` on any non-finite score (its `ensure_all_finite` input check), while the Rust core contract (`canonical_map` -> `sanitize_scores` in `canonical/mapping.rs`) forward-fills warmup NaN by design, and the batch executor (`execute_batch_py`) emits NaN for the first `window - 1` bars by its documented contract. The binding is therefore stricter than the engine contract: a score series with legitimate operator-warmup NaN cannot be passed to `canonical_map_py` at all.

## 2. Resolution

The milestone-1 orchestrator (`src/trading/portfolio.py`) mirrors the engine's `sanitize_scores` (forward-fill; all-NaN -> zeros) on the Python side before each `canonical_map_py` call, so research/live parity is preserved through identical sanitization semantics at the Python layer. This is the accepted parity contract for milestone 1; relaxing the binding to sanitize before its finiteness check (matching the Rust core) is a candidate follow-up, tracked here rather than silently fixed.

## 3. Impact

- Behavior is correct with the Python-side sanitize; no live-path bug.
- The binding/core inconsistency is a maintenance hazard: a future caller of `canonical_map_py` without sanitizing will hit an unexpected ValueError.

## Related notes

- [DEC-008](DEC-008-live-wiring-architecture.md) - wiring phase this was found in
- Future reconciliation/amendment if the binding is relaxed
