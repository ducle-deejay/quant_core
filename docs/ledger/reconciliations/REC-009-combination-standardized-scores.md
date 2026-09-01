---
doc_id: REC-009
title: Combination weights apply to standardized scores - API resolves the canon-vs-engine divergence
type: reconciliation
owner: research
status: resolved
version: 1.0
components: [4]
tags: [combination, standardization, reconciliation, quant-api]
source: "practitioner review 2026-09-01: stage-4-combination section 2 requires weights on standardized scores; the engine InverseVol and the API mirror combined raw sanitized scores, letting an alpha's native scale dominate the risk budget (worst alpha got 29% weight on real data)"
design: []
code: [src/quant_api/portfolio.py, src/alpha-core/src/strategies/combination/inverse_vol.rs]
test: [src/quant_api/tests/test_portfolio.py]
---

# REC-009 - Combination weights apply to standardized scores

## 1. Conflict

Canon stage-4-combination section 2: weights are a risk-budget allocation
applied to STANDARDIZED scores, "undistorted by each alpha's native scale".
The engine `InverseVol` (inverse_vol.rs) and the API mirror computed weights
from - and applied them to - raw sanitized score series. On real VN30F1M
data the distortion is material: return-scale alphas (score std ~0.002)
took 96% of the budget while z/price-scale alphas (std 0.2-1.4) were
crushed to the floor, and the WORST standalone alpha received the
second-highest weight purely because its raw scores are small.

## 2. Verdict

Canon wins. The API (`quant_api.portfolio.combine`) now standardizes every
score row (z-score; zero-variance rows -> zeros) before combining:
equal_weight -> 1/N on standardized rows; inverse_vol -> weights from the
capped-simplex of 1/std of the RAW series (the risk measure) applied to the
standardized rows via the engine `composite_score_py` (research/live
parity kept - the live path already combines canonical z-unit positions).
The engine's raw-input `inverse_vol_combine_py` is retained unchanged for
the parity suite and engine-level callers. The weighting-ladder wording
(weights proportional to PnL volatility rather than score std) is left to
the phase-2 evaluation harness.

## 3. Consequence

`weights.json` (the weekly refit handoff artifact) now reflects risk-budget
weights undistorted by native scale. The refit weights derivation is
unchanged (capped-simplex of 1/std of raw scores) and is applied to
standardized rows, matching the combine path.

## Related notes

- [DEC-017](DEC-017-quant-api-role-modules.md) - the quant_api contract
- [REC-008](REC-008-orthogonalization-pnl-input.md) - orthogonalization
  input contract from the same review wave
