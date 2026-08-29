---
doc_id: REC-007
title: Relocation - engine and bindings moved under src/; earlier ledger code paths are historical
type: reconciliation
owner: research
status: resolved
version: 1.0
components: [0, 1, 2, 3, 4, 5]
tags: [relocation, monorepo, migration, paths]
source: "owner approved layout 2026-08-30 (DEC-007)"
design: [STG-0-ALPHA-MINING, STG-1-CANONICAL-SIM, STG-2-EVALUATION, STG-3-ORTHOGONALIZATION, STG-4-COMBINATION, STG-5-POSITION-CONSTRUCTION]
code: [src/alpha-core, src/alpha_core, src/market_data, src/trading, apps]
test: [examples/parity_full_surface.py]
---

# REC-007 - Relocation: Engine and Bindings Moved Under src/

## 1. Verdict

The relocation landed and the full verification chain passes: Rust test suite, Python parity suite, and ledger sweep. The repository now follows the src/ monorepo layout of DEC-007.

## 2. Path mapping (old -> new)

| Old | New |
|---|---|
| crates/alpha-core | src/alpha-core |
| python/quantcore (package `quantcore`) | src/alpha_core (package `alpha_core`, extension module alpha_core) |
| - (new) | src/market_data (ported from nox_system: nox_data/sources/dnse + application data entrypoints) |
| - (new) | src/trading (ported from nox_system: adapters/entrade, adapters/dnse, engines/data instruments, live node) |
| applications/ (planned) | apps/ |
| pyproject.toml (single maturin project) | uv workspace root; per-package pyproject under src/* |

## 3. Consequences for ledger history

- The sweep script does not validate `code:` front-matter paths, so older notes remain valid documents of where behaviour lived at the time; no resolved note is edited (append-only rule M2).
- New work references the new paths; readers of older notes should apply this mapping.

## 4. Verification

- `cargo test` (alpha-core): 226 passed, 0 failed.
- Parity suite after rename (`import alpha_core`): 21/21 passed.
- `python3 scripts/sweep_ledger.py`: OK, drift debt 0.
- Environment rebuild documented in README (CARGO_HOME, PYO3_PYTHON, UV_CACHE_DIR/PIP_CACHE_DIR inside the repo).

## Related notes

- [DEC-007](../decisions/DEC-007-repo-layout-and-rename.md) - the approved layout
- [DEC-005](../decisions/DEC-005-python-first-api.md) - python-first API (superseded in part)
