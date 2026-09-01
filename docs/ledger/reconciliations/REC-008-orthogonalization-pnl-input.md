---
doc_id: REC-008
title: Orthogonalization input contract - per-bar net PnL is canonical (score series amended)
type: reconciliation
owner: research
status: resolved
version: 1.0
components: [3]
tags: [orthogonalization, contract, reconciliation, quant-api]
source: "UAT 2026-08-31: portfolio researcher acceptance found the docs disagree on the orthogonalize input - runbook and docstring said score series, canon contract says pool PnLs; on real data the two give OPPOSITE verdicts for the same candidate-vs-pool pairs"
design: []
code: [src/quant_api/portfolio.py]
test: [src/quant_api/tests/test_portfolio.py]
---

# REC-008 - Orthogonalization input contract: per-bar net PnL is canonical

## 1. Conflict

The frozen canon (framework-lifecycle.md, Component 3 - Orthogonalization
contract) states: "candidate plus pool PnLs in -> residual verdict out".
The quant_api portfolio module docstring and the portfolio runbook said the
input is score series. On real VN30F1M data (UAT 2026-08-31) the two
representations give opposite verdicts for the same candidate-vs-pool
pairs: score input -> INCREMENTAL (residual Sharpe +0.01..+0.04), canonical
net PnL input -> REDUNDANT (-0.30..-3.13). The engine regression is OLS
through the origin, so nonzero-mean PnL residuals carry a large signed-mean
term that score residuals do not.

## 2. Verdict

The canon contract wins: the canonical input to `orthogonalize` is the
per-bar NET PNL series (the "residual dossiers" of the canon), not score
series. Code fix: `quant_api.portfolio.orthogonalize` docstring now states
the PnL contract and a new helper `quant_api.portfolio.pool_pnl` builds the
canonical per-bar net PnL for a pool folder (batch score -> sanitize ->
canonical position -> net PnL, mirroring the research pipeline); the
portfolio runbook uses the helper.

## 3. Consequence

A researcher following the runbook can no longer admit redundant alphas via
the score path; the score representation is not supported for the verdict.
The UAT finding that the two representations disagree stands as a warning:
verdicts must be read relative to the PnL input documented here.

## Related notes

- [DEC-017](DEC-017-quant-api-role-modules.md) - the quant_api contract
- [OBS-016](OBS-016-vol-estimate-annualization-convention.md) - vol
  convention observation from the same UAT wave
