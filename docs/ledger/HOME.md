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
- [OBS-008](observations/OBS-008-user-acceptance-production-gaps.md) - shop-persona acceptance tests exposed Python boundary poison, Rust panics, packaging blockers and a memory-scale limitation.
- [OBS-009](observations/OBS-009-entrade-fee-and-margin-schedule.md) - verified entrade fee and margin schedule (5% margin; 31,500 + 8.1 x price VND round trip per contract; 5% profit tax) as the cost-model calibration reference; canon cost estimates are outdated.
- [OBS-010](observations/OBS-010-empirical-entrade-fee-verification.md) - seven demo deals verify every fee/margin component exactly; partnership fee measured at 8.22015/point vs published 8.1; tax is a symmetric 5% of gross PnL.
- [OBS-011](observations/OBS-011-canonical-map-binding-nan.md) - canonical_map_py binding rejects warmup NaN the Rust core sanitizes; orchestrator mirrors sanitize_scores on the Python side (parity contract for milestone 1).
- [OBS-012](observations/OBS-012-stale-pipeline-config-path.md) - daily ETL top-level config still pointed at pre-restructure `applications/` paths; would have crashed the first LaunchAgent 16:00 run, fixed to `apps/`.
- [OBS-013](observations/OBS-013-silent-alert-failure-gaps.md) - two silent-failure gaps: bootstrap crashes alerted nothing, undeliverable alerts were swallowed with exit 0; closed by DEC-012.


### Reconciliations

- [REC-001](reconciliations/REC-001-sanitize-scores-amendment.md) - Step A input contract amended to require finite scores; canonical_map sanitises first.
- [REC-002](reconciliations/REC-002-psr-probability-wired.md) - PSR-style spurious probability wired into the gate as the seventh check; T013 complete.
- [REC-003](reconciliations/REC-003-spearman-upgrade.md) - IC ladder upgraded to true Spearman; one-name-one-meaning restored.
- [REC-004](reconciliations/REC-004-backstop-only-dsh.md) - DSH enforcement stays commit-level backstop until the hooks bridge matures.
- [REC-005](reconciliations/REC-005-research-to-examples.md) - demonstration scripts moved to examples/; frozen docs keep old paths, this note is the authoritative pointer.
- [REC-006](reconciliations/REC-006-uat-fix-wave.md) - user-acceptance fix wave closes Python boundary, Rust panic and packaging blockers; accepted gaps remain explicit.
- [REC-007](reconciliations/REC-007-relocation-src-monorepo.md) - engine and bindings relocated under src/ per DEC-007; earlier ledger code paths are historical; verification chain re-passed.

### Decisions

- [DEC-001](decisions/DEC-001-frozen-canon-ledger-split.md) - enhanced stays frozen as design anchor; the ledger is the single living layer.
- [DEC-002](decisions/DEC-002-multi-harness-kit.md) - multi-harness enforcement kit: AGENTS.md routing, canon guard hook, git backstop, ledger-discipline skill.
- [DEC-004](decisions/DEC-004-decision-authority-ratified.md) - owner-ratified decision authority protocol for commits, policy changes and outside-workspace writes.
- [DEC-005](decisions/DEC-005-python-first-api.md) - Python-first public API strategy with phased full-surface bindings.
- [DEC-006](decisions/DEC-006-milestone-1-fee-model.md) - milestone-1 fee model keeps scalar cost_per_side (fee 1.461 + half-spread 0.333 + buffer 0.5 bp at reference price 1,500); two-part price-dependent model deferred after wiring.
- [DEC-007](decisions/DEC-007-repo-layout-and-rename.md) - src/ monorepo with per-package packaging (uv workspace); Python package renamed quantcore -> alpha_core; apps/ for entrypoints.
- [DEC-008](decisions/DEC-008-live-wiring-architecture.md) - milestone-1 wiring: contract-first (src/trading/contracts.py), three parallel workstreams (orchestration, bridge strategy, risk overlay), risk built to live standard from the paper phase; spec-sheet gauges deferred.
- [DEC-009](decisions/DEC-009-data-sources-and-telegram-alerts.md) - DNSE primary + Mirae fallback data sources with fixed coverage semantics (Mirae-resolved gaps succeed); Telegram alerts for data ingest and live trading via one env pair.
- [DEC-010](decisions/DEC-010-commit-convention.md) - commit messages follow conventional commits `<type>(<scope>): <imperative summary>` with fixed type and scope vocabulary; amend/squash pre-push only.
- [DEC-011](decisions/DEC-011-telegram-channel-separation.md) - two Telegram alert channels (DATA_/TRADING_ bot pairs) superseding the shared single pair; no hidden fallback.
- [DEC-012](decisions/DEC-012-alert-coverage-wave-a.md) - alert coverage wave A: unified HTML alert format, bootstrap failure alerts, fail-loud ETL entrypoint, heartbeat status file + watcher LaunchAgent; baselines deferred to wave B.




### Test mappings

- [TST-001](tests/TST-001-metrics-contract-tests.md) - canonical metrics: known answers plus scale/sign metamorphic relations.
- [TST-002](tests/TST-002-gate-contract-tests.md) - admission gate: deflation dynamics and independent fixed-limit enforcement.
- [TST-003](tests/TST-003-ic-ladder-contract-tests.md) - IC ladder: lead-lag world, sign mirror, horizon attachment, degeneracies.
- [TST-004](tests/TST-004-walk-forward-contract-tests.md) - walk-forward stability: regime-shift detection and block arithmetic.
- [TST-005](tests/TST-005-pool-and-grammar-contract-tests.md) - residual orthogonality invariant plus generator reproducibility.
- [TST-006](tests/TST-006-full-surface-parity-and-uat.md) - 21-check Python parity suite plus ten-persona UAT and three-persona closure round.
- [TST-007](tests/TST-007-milestone-1-wiring-contract-tests.md) - milestone-1 wiring contract tests: portfolio orchestrator (8), bridge strategy (23), risk overlay (24) against STG-1/5/6/7 and DEC-006/008.
- [TST-008](tests/TST-008-data-fallback-and-alert-tests.md) - data fallback and alert tests: daily orchestrator semantics (10) and Telegram transport failure safety (4) per DEC-009.
- [TST-009](tests/TST-009-alert-coverage-wave-a.md) - alert coverage wave A contract tests: unified format, bootstrap guard, fail-loud entrypoint, heartbeat lifecycle, HTML transport per DEC-012.

## Related notes

- [HOME](../enhanced/HOME.md) - frozen design canon anchor and vault entry point
- [style-guide](../enhanced/style-guide.md) - presentation standard reused by every ledger note
