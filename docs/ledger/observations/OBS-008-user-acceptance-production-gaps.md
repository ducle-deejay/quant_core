---
doc_id: OBS-008
title: Shop-persona acceptance tests exposed boundary poison, Rust panics, and packaging blockers
type: observation
owner: research
status: resolved
version: 1.0
components: [0, 1, 2, 3, 4, 5]
tags: [user-acceptance, production-readiness, python, rust]
source: "ten shop-persona agents in UAT round 1, followed by three closure personas in round 2"
design: [STG-0-ALPHA-MINING, STG-1-CANONICAL-SIM, STG-2-EVALUATION, STG-3-ORTHOGONALIZATION, STG-4-COMBINATION, STG-5-POSITION-CONSTRUCTION]
code: [crates/alpha-core/src/python_bindings, crates/alpha-core/src/canonical/mapping.rs, crates/alpha-core/src/orthogonalization.rs, crates/alpha-core/src/combination.rs, pyproject.toml]
test: [examples/parity_full_surface.py]
---

# OBS-008 - Shop-Persona Acceptance Tests Exposed Production Gaps

## 1. Summary

Ten independent agents used the framework as real quant researchers, portfolio managers, risk officers, Rust developers, Python newcomers, adversarial testers, performance engineers, senior quants, platform engineers, and gate reviewers. They found three classes of production blockers: Python wrappers silently accepted non-finite data, Rust core functions panicked on malformed shapes, and a fresh clone could not build the Python wheel from the repository root.

## 2. Confirmed findings

```text
    Python boundary   NaN/inf reached compute_pnl, walk_forward and IC outputs;
                      zero/negative bars_per_day produced inconsistent errors;
                      mismatched IC lengths returned neutral-looking results
    Rust core         empty canonical score, short orthogonalization pool and
                      ragged combination matrices could panic
    Packaging         root maturin build targeted the virtual Cargo workspace;
                      feature python-bindings was not selected automatically;
                      no README existed for a fresh user
    Scale             100 expressions x 472k bars peaked around 2 GiB memory;
                      correct but a future streaming API is desirable
```

## 3. Resolution

The first three classes were fixed and independently re-tested; see [REC-006](../reconciliations/REC-006-uat-fix-wave.md). The scale item remains an accepted performance characteristic rather than a correctness defect.

## Related notes

- [REC-006](../reconciliations/REC-006-uat-fix-wave.md) - fix verdict and accepted gaps
- [DEC-005](../decisions/DEC-005-python-first-api.md) - Python-first surface this acceptance round tested
