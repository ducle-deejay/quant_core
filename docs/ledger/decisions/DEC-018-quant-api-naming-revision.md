---
doc_id: DEC-018
title: quant_api module naming revision - research renamed to alpha
type: decision
owner: research
status: resolved
version: 1.0
components: [0, 1, 2, 3, 4, 5, 6, 7]
tags: [api, naming, quant-api]
source: "owner feedback 2026-08-31: 'research' is too generic - alpha, portfolio, execution and risk APIs all serve research; alpha is the canon vocabulary for Component 0 outputs"
design: []
code: [src/quant_api]
test: [src/quant_api/tests/test_alpha.py]
---

# DEC-018 - quant_api module naming revision (research -> alpha)

## 1. Decision

The Quantitative Researcher module is renamed from `quant_api.research` to
`quant_api.alpha`, with the following renames applied across the package,
tests, notebooks and runbooks (best-practice naming review, 2026-08-31):

- module `src/quant_api/research.py` -> `src/quant_api/alpha.py`
- `ResearchConfig` -> `AlphaConfig` (the module now reads
  `quant_api.alpha.AlphaConfig`)
- `pool_scores` -> `score_pool` (verb-first, consistent with
  `refit_weights`, `orthogonalize`, `combine` in the portfolio module)
- test runner `src/quant_api/tests/test_research.py` ->
  `src/quant_api/tests/test_alpha.py` (test function names
  `test_score_pool_*` follow the renamed entry point)
- notebook `examples/notebooks/research_api.ipynb` ->
  `examples/notebooks/alpha_api.ipynb`
- runbook `docs/runbooks/research-workflow.md` ->
  `docs/runbooks/alpha-workflow.md`
- `quant_api.core` now exports a single `DEFAULT_POOL_DIR` (the duplicate
  `POOL_DIR` alias is removed)

## 2. Rationale

All four role modules serve research; "research" as a module name was
indistinguishable from the others. "Alpha" is the established canon
vocabulary (Component 0 - Alpha Mining produces alpha expressions) and
matches the sibling modules' domain-noun style (portfolio, execution, risk).

## 3. Consequence

This note supersedes the module-name references in DEC-017 and the
`test_research.py` path reference in TST-011 (both remain as historical
records, ledger rule M2 append-only). No behaviour change: same functions,
same contracts, renamed surface. Test evidence: test_alpha.py, all other
quant_api suites, and the integration chain re-run green after the rename.

## Related notes

- [DEC-017](DEC-017-quant-api-role-modules.md) - the API contract whose
  naming this note revises
- [TST-011](TST-011-quant-api-contract-tests.md) - test mapping (paths
  superseded by this note)
