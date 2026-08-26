---
doc_id: DEC-005
title: Python-first API strategy with phased full-surface bindings
type: decision
owner: research
status: resolved
version: 1.0
components: [0, 1, 2, 3, 4, 5]
tags: [python, bindings, architecture]
source: "owner vision: every pipeline stage consumed from Python; Rust remains the engine"
design: []
code: [crates/alpha-core/src/python_bindings.rs, python/quantcore]
test: []
---

# DEC-005 - Python-First API Strategy With Phased Full-Surface Bindings

## 1. Decision

The Python surface becomes the primary user-facing API across all components; the Rust public API stays for engine work only. The bindings expand in dependency order so the bridge is de-risked before investment:

```text
    Phase 0   build verification - maturin into .venv, import quantcore,
              parity check of existing canonical_map and compute_pnl
    Phase 1   thin layers - metrics, screening, orthogonalization,
              combination, sizing (each follows the established wrapper
              pattern: input validation, GIL release, ValueError errors)
    Phase 2   evaluation complete - ic_ladder, walk_forward,
              evaluate_gate accepting a trial ledger, deflated Sharpe pair
    Phase 3   mining - parser, DAG builder, batch executor returning a
              matrix, GA loop entry point
    Phase 4   parity suite over the whole surface plus usage docs in
              python/quantcore/__init__.py
```

## 2. Rationale

Researchers operate in Python notebooks; requiring them to touch Rust contradicts the product intent recorded in plan task T030. The two existing wrappers already demonstrate the quality pattern, so expansion is replication, not invention.

## 3. Consequence

`python_bindings.rs` is restructured into a directory module so per-component binding files can be authored in parallel without merge conflicts. Task T030 closes at Phase 4 when import-parity holds for the entire surface.

## Related notes

- [DEC-002](DEC-002-multi-harness-kit.md) - governance kit under which this work runs
