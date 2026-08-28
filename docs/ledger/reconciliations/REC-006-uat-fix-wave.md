---
doc_id: REC-006
title: User-acceptance fix wave closes Python boundary, Rust panic, and packaging blockers
type: reconciliation
owner: research
status: resolved
version: 1.0
components: [0, 1, 2, 3, 4, 5]
tags: [user-acceptance, fixes, production-readiness]
source: "owner approved all three fix batches after UAT round 1"
design: [STG-0-ALPHA-MINING, STG-1-CANONICAL-SIM, STG-2-EVALUATION, STG-3-ORTHOGONALIZATION, STG-4-COMBINATION, STG-5-POSITION-CONSTRUCTION]
code: [crates/alpha-core/src/python_bindings, crates/alpha-core/src/canonical/mapping.rs, crates/alpha-core/src/orthogonalization.rs, crates/alpha-core/src/combination.rs, pyproject.toml, README.md]
test: [examples/parity_full_surface.py]
---

# REC-006 - User-Acceptance Fix Wave

## 1. Verdict

All three approved fix batches landed in the working tree and passed closure testing. Python rejects every tested non-finite series at the boundary with a ValueError naming the field and index; Rust returns safe deterministic results for empty/ragged inputs; and a root-level build produces a CPython 3.14 wheel that installs and imports from a clean virtual environment outside the repository.

## 2. Verified outcomes

```text
    Rust suite          226 passed, 0 failed
    Python parity       21 of 21 checks passed
    External package    root build -> cp314 wheel -> clean /tmp venv ->
                        import quantcore -> functional Sharpe call passed
    Adversarial probes  NaN/inf, zero/negative bars_per_day and IC length
                        mismatch all raise clean ValueError
    Controlled state    random-expression batch still yields zero survivors;
                        this is an honest no-trade state, not an engine fault
```

## 3. Accepted gaps

- Production risk sign-off evidence (live performance, realized costs, drawdown and trial-adjustment pack) remains future work; the ledger sweep checks documentation drift only.
- Batch execution retains full-length intermediate columns and may peak near 2 GiB for 100 expressions over the full VN30F1M history; streaming/chunking is deferred.
- A virtual environment created without pip is an environment convention, not a wheel defect; installation with uv or a standard pip-enabled environment works.
- Root builds on machines with multiple Python interpreters must set `PYO3_PYTHON` explicitly; README.md records the command.

## Related notes

- [OBS-008](../observations/OBS-008-user-acceptance-production-gaps.md) - findings this verdict closes
- [DEC-004](../decisions/DEC-004-decision-authority-ratified.md) - owner authority under which fixes were approved
