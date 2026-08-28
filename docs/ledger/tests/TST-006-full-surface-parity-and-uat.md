---
doc_id: TST-006
title: Full-surface Python parity and shop-persona acceptance tests
type: case-study
owner: research
status: resolved
version: 1.0
components: [0, 1, 2, 3, 4, 5]
tags: [test-mapping, python, user-acceptance, parity]
source: "DEC-005 Phase 4 plus ten-persona UAT round 1 and three-persona closure round 2"
design: [STG-0-ALPHA-MINING, STG-1-CANONICAL-SIM, STG-2-EVALUATION, STG-3-ORTHOGONALIZATION, STG-4-COMBINATION, STG-5-POSITION-CONSTRUCTION]
code: [examples/parity_full_surface.py, crates/alpha-core/src/python_bindings]
test: [examples/parity_full_surface.py, cargo-test-alpha-core-lib, clean-wheel-import, adversarial-boundary-probes]
---

# TST-006 - Full-Surface Python Parity and Shop-Persona Acceptance Tests

## 1. Mapping

The parity script exercises all 18 Python functions and six result classes against hand-computed or Rust-test anchors: canonical mapping, PnL anti-lookahead, Sharpe, drawdown, IC ladder, walk-forward, screening, deflated Sharpe, expression validation, DAG batch execution, GA evolution, orthogonalization, combination and sizing. It currently passes 21 of 21 checks on Python 3.14.

Ten user personas then exercised real shop workflows on real VN30F1M data and hostile inputs. Three previously failing personas returned after the fix wave: boundary poison and packaging blockers closed; the risk officer retained only deliberately deferred live-sign-off evidence as a known gap.

## 2. Reproduction

```text
    cargo test -p alpha-core --lib
    .venv/bin/python3 examples/parity_full_surface.py
    PYO3_PYTHON=$(pwd)/.venv/bin/python3 \
        .venv/bin/python3 -m maturin build --out /tmp/quantcore-wheel
```

## Related notes

- [OBS-008](../observations/OBS-008-user-acceptance-production-gaps.md) - findings that produced the fix wave
- [REC-006](../reconciliations/REC-006-uat-fix-wave.md) - closure verdict
