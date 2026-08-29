---
doc_id: DEC-007
title: Repo layout src/ monorepo with per-package packaging; Python package renamed alpha_core
type: decision
owner: research
status: resolved
version: 1.0
components: [0, 1, 2, 3, 4, 5]
tags: [architecture, naming, monorepo, packaging, nautilus-wiring]
source: "owner discussion 2026-08-30: monolithic repo structured for later microservice split, mirroring the nox_system src/ layout"
design: []
code: [crates/alpha-core, python/quantcore, Cargo.toml, pyproject.toml]
test: [examples/parity_full_surface.py]
---

# DEC-007 - Repo Layout: src/ Monorepo, Per-Package Packaging, alpha_core Rename

## 1. Decision

The repository is restructured for the Nautilus wiring phase into a monolith-with-microservice-boundaries layout:

```text
quant_core/
├── src/
│   ├── alpha_core/     # Rust engine crate (alpha-core) + Python bindings package (renamed from quantcore)
│   ├── market_data/    # data pipeline: DNSE -> transform -> Nautilus catalog (ported from nox)
│   └── trading/        # live platform wiring: entrade/dnse adapters, strategies, risk overlay,
│                       #   spec sheet, node entrypoints (ported from nox)
├── apps/               # entrypoints: research/, trading/ (paper|live), data/  (renamed from applications/)
├── operations/         # retained acceptance tooling (entrade demo audit, parity suites)
├── docs/ data/ scripts/ skills/
```

- The Python package `quantcore` (import name) is renamed to **`alpha_core`** to express its role as the Python surface of the alpha-core engine; the framework product name "quantcore" (repo, README) is retained.
- Packaging is **per-package** (uv workspace, members `src/*`), each package with its own pyproject: distributions `alpha-core`, `market-data`, `trading` - the nox pattern that makes a future microservice split a packaging-only change.
- The Rust crate moves from `crates/alpha-core` to `src/alpha-core`; `apps/` replaces the earlier `applications/` name.
- `operations/` holds acceptance tooling; no separate ops package under src/ (ops becomes a service only if it ever needs to).

## 2. Rationale

- The wiring phase adds live components (data pipeline, Nautilus adapters, risk, monitoring) to a research engine; one repository with clear package boundaries keeps the frozen-canon governance (ledger, sweep) over the whole system.
- Role-based package names (`alpha_core`, `market_data`, `trading`) describe what each package is, not a brand prefix.
- Per-package pyproject matches the proven nox layout and keeps each package independently installable/publishable.

## 3. Impact

- Import statements, examples, parity suite and README quick start change from `import quantcore as q` to `import alpha_core as q`.
- The pyo3 extension module is renamed to `alpha_core`.
- DEC-005 (python-first API) is unaffected in substance; its "quantcore" references to the Python package are superseded by this note.
- Ledger `code:` front-matter paths in earlier notes become historical; see REC-007.

## Related notes

- [DEC-005](DEC-005-python-first-api.md) - python-first API strategy (naming superseded in part)
- [REC-007](../reconciliations/REC-007-relocation-src-monorepo.md) - relocation executed
- [OBS-008](OBS-008-user-acceptance-production-gaps.md) - prior packaging gaps
