---
doc_id: LED-HOME
title: Implementation Ledger - Home
type: index
owner: research
status: approved
version: 1.0
components: []
tags: [ledger, moc, drift-control]
source: "discussion: second-brain ledger anchored on the frozen design canon; reformatted per REF-STYLE"
---

# Implementation Ledger - Home

## 1. Purpose

This ledger is the only living documentation layer of the project. The design canon rooted at [HOME](../enhanced/HOME.md) is frozen: it states intent, formulas, and contracts and does not change again. Whenever code behaviour and canon disagree, the disagreement is recorded here, triaged, and resolved either by correcting the code or by recording an accepted amendment - never by editing the canon and never silently. A reader who wants to know how the running system relates to the stated design starts here, not in git history.

## 2. Note classes

Every ledger note covers exactly one idea (atomicity). Four classes exist:

- Observations - `observations/OBS-NNN-slug.md` - a finding about actual code or system behaviour: bugs discovered, audit results, anomalies seen in batch runs.
- Reconciliations - `reconciliations/REC-NNN-slug.md` - a verdict on one design-versus-code conflict; the outcome is a code fix or a recorded accepted amendment.
- Decisions - `decisions/DEC-NNN-slug.md` - an accepted architectural or methodological choice made during implementation, recorded ADR-style.
- Test mappings - `tests/TST-NNN-slug.md` - which test protects which canon contract and which observation provoked it.

Numbering per class is sequential starting at 001 and identifiers are never reused.

## 3. Front matter and lifecycle

Ledger notes reuse the nine-field front matter defined in [style-guide](../enhanced/style-guide.md) with two adaptations. First, `doc_id` follows the note class scheme (`OBS-001`, `REC-001`, and so on) plus a short slug in the file name. Second, `status` draws from the ledger lifecycle vocabulary below instead of draft/approved/deprecated:

```text
    open        finding or conflict recorded, not yet judged
    triaged     verdict proposed, waiting on code change or amendment
    resolved    fix landed and verified, or amendment recorded
    superseded  replaced by a newer note linked from this one
```

Three link fields are mandatory inside front matter for all classes except pure decisions (which may omit `test`):

```text
    design      doc_id values in the frozen canon that this note touches
    code        repository paths where the behaviour lives
    test        test names protecting the contract (empty until B3 lands)
```

## 4. Drift control rules

```text
    M1   any change touching a contract stated in the canon must add or
         update a ledger note in the same change, referencing the doc_id
    M2   append-only: a wrong note is superseded by a newer note linked
         from it; existing notes are never edited after resolution
    M3   the sweep script reports counts by status; the open count is the
         visible drift debt of the project
    M4   every test protecting a canon contract cites its note id in a
         source comment so code, tests, and design stay traceable
```

The sweep script lives at `scripts/sweep_ledger.py` and exits non-zero when any referenced design doc_id does not resolve inside docs/enhanced.

## 5. Index

### Observations

- [OBS-001](observations/OBS-001-nan-warmup-poisoning.md) - warmup NaN from rolling operators silently flattened every time-series alpha to a zero position.
- [OBS-002](observations/OBS-002-zscore-catastrophic-cancellation.md) - unanchored E[x^2] - mean^2 variance lost precision for scores riding on large offsets.
- [OBS-003](observations/OBS-003-phantom-trade-counting.md) - trades_per_day counted band triggers at the cap instead of executed position changes.
- [OBS-004](observations/OBS-004-gate-dead-inputs.md) - gate input carried skewness, kurtosis and sample length that evaluate_gate ignored; PSR probability now wired.
- [OBS-005](observations/OBS-005-duplicate-rank-ic-name.md) - duplicate rank_ic_block name with different statistics; ladder upgraded to true Spearman.
- [OBS-006](observations/OBS-006-formatting-version-request.md) - governance drill: formatting-version request denied by design; canon untouched.
- [OBS-007](observations/OBS-007-dsh-bridge-no-interception.md) - DSH hooks bridge rc.5 loads but never intercepts harness-native file edits; closed by owner decision: commit-level backstop only on DSH until bridge matures.

### Reconciliations

- [REC-001](reconciliations/REC-001-sanitize-scores-amendment.md) - Step A input contract amended to require finite scores; canonical_map sanitises first.
- [REC-002](reconciliations/REC-002-psr-probability-wired.md) - PSR-style spurious probability wired into the gate as the seventh check; T013 complete.
- [REC-003](reconciliations/REC-003-spearman-upgrade.md) - IC ladder upgraded to true Spearman; one-name-one-meaning restored.
- [REC-004](reconciliations/REC-004-backstop-only-dsh.md) - DSH enforcement stays commit-level backstop until the hooks bridge matures.
- [REC-005](reconciliations/REC-005-research-to-examples.md) - demonstration scripts moved to examples/; frozen docs keep old paths, this note is the authoritative pointer.

### Decisions

- [DEC-001](decisions/DEC-001-frozen-canon-ledger-split.md) - enhanced stays frozen as design anchor; the ledger is the single living layer.
- [DEC-002](decisions/DEC-002-multi-harness-kit.md) - multi-harness enforcement kit: AGENTS.md routing, canon guard hook, git backstop, ledger-discipline skill.

### Test mappings

- [TST-001](tests/TST-001-metrics-contract-tests.md) - canonical metrics: known answers plus scale/sign metamorphic relations.
- [TST-002](tests/TST-002-gate-contract-tests.md) - admission gate: deflation dynamics and independent fixed-limit enforcement.
- [TST-003](tests/TST-003-ic-ladder-contract-tests.md) - IC ladder: lead-lag world, sign mirror, horizon attachment, degeneracies.
- [TST-004](tests/TST-004-walk-forward-contract-tests.md) - walk-forward stability: regime-shift detection and block arithmetic.
- [TST-005](tests/TST-005-pool-and-grammar-contract-tests.md) - residual orthogonality invariant plus generator reproducibility.

## Related notes

- [HOME](../enhanced/HOME.md) - frozen design canon anchor and vault entry point
- [style-guide](../enhanced/style-guide.md) - presentation standard reused by every ledger note
