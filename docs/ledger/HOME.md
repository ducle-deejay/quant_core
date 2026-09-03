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
- [OBS-014](observations/OBS-014-daily-force-close-bug.md) - bridge force-closed the position every day at 14:00 instead of only on the contract expiry day; fixed by DEC-013 expiry semantics.
- [OBS-015](observations/OBS-015-north-star-approval-breach.md) - decision-authority breach: north-star charter applied with revised wording before a second approval round; mitigation: content re-presented, no commit, note open until owner decides.
- [OBS-016](observations/OBS-016-vol-estimate-annualization-convention.md) - vol estimate scaled by sqrt(bars_per_day) is per-day, not per-year (~15.8x); parity with live orchestrator kept, label/calibration tracked for harness review.
- [OBS-017](observations/OBS-017-drawdown-boundary-roundtrip.md) - drawdown ladder exact-boundary round-trip missed the kill line at exactly 20% (1-dd inexact); engine raw_drawdown snapped to 12 decimals; boundaries verified 0.05/0.10/0.15/0.20.
- [OBS-018](observations/OBS-018-operating-model-contract-leakage.md) - DEC-019/DEC-020 expressed researcher activities and component flows as premature implementation methods; resolved by DEC-021's actor-, artifact-, and capability-level operating model.


### Reconciliations

- [REC-001](reconciliations/REC-001-sanitize-scores-amendment.md) - Step A input contract amended to require finite scores; canonical_map sanitises first.
- [REC-002](reconciliations/REC-002-psr-probability-wired.md) - PSR-style spurious probability wired into the gate as the seventh check; T013 complete.
- [REC-003](reconciliations/REC-003-spearman-upgrade.md) - IC ladder upgraded to true Spearman; one-name-one-meaning restored.
- [REC-004](reconciliations/REC-004-backstop-only-dsh.md) - DSH enforcement stays commit-level backstop until the hooks bridge matures.
- [REC-005](reconciliations/REC-005-research-to-examples.md) - demonstration scripts moved to examples/; frozen docs keep old paths, this note is the authoritative pointer.
- [REC-006](reconciliations/REC-006-uat-fix-wave.md) - user-acceptance fix wave closes Python boundary, Rust panic and packaging blockers; accepted gaps remain explicit.
- [REC-007](reconciliations/REC-007-relocation-src-monorepo.md) - engine and bindings relocated under src/ per DEC-007; earlier ledger code paths are historical; verification chain re-passed.
- [REC-008](reconciliations/REC-008-orthogonalization-pnl-input.md) - orthogonalize input contract reconciled: per-bar net PnL is canonical (canon Component 3), score-series docstring/runbook amended; pool_pnl helper added.
- [REC-009](reconciliations/REC-009-combination-standardized-scores.md) - combination weights apply to standardized scores (canon stage-4 section 2); API standardizes rows before combining, weights from raw risk; engine raw variant retained for parity.
- [REC-010](reconciliations/REC-010-execution-consistency.md) - execution consistency findings: urgency gap-scaled convention (worked-example interpretation), order-state gaps + pessimistic fill stance deferred, provenance honesty, catalog-leak guard, realized-PnL stats, TWAP time-gating.

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
- [DEC-013](decisions/DEC-013-milestone-1-live-corrections.md) - milestone-1 live corrections: expiry-day force-close semantics, VN session windows, warmup from the research catalog, per-bar decision log + risk transition log, Redis state persistence.
- [DEC-014](decisions/DEC-014-project-north-star.md) - project north star: the product is a replicable systematic-trading framework across assets and strategy styles, not one instrument; five correctness invariants; anchor rule for agents; supersedes milestone-only goal framings.
- [DEC-015](decisions/DEC-015-agents-md-instruction-style-v2.md) - AGENTS.md instruction style v2: plain Purpose section at end-state level plus Ground-truth authority order and discovery rule; replaces the north-star section presentation; DEC-014 unchanged.
- [DEC-016](decisions/DEC-016-purpose-loop-vocabulary.md) - Purpose wording corrected to loop vocabulary ("continuous loop ... recalibrate", not "pipeline that turns ... into"); supersedes the DEC-015 section-3 quote.
- [DEC-017](decisions/DEC-017-quant-api-role-modules.md) - quant_api role-scoped Python API: one module per practitioner role, core with catalog/artifacts/pool/registries, additive ga_breed_py binding; sizing owned by the risk role; Nautilus backtest reused for execution.
- [DEC-018](decisions/DEC-018-quant-api-naming-revision.md) - quant_api module naming revision: research renamed to alpha (AlphaConfig, score_pool, test/notebook/runbook renames); supersedes DEC-017/TST-011 name references.
- [DEC-019](decisions/DEC-019-systematic-trading-lifecycle-operating-model.md) - systematic-trading operating model: vocabulary, module ownership, data/storage, alpha lifecycle, operating invariants, lifecycle algorithm and method table.
- [DEC-020](decisions/DEC-020-systematic-trading-operating-model-correction.md) - runtime-ownership correction that delegated existing primitives to Rust and runtime state to Nautilus; superseded by DEC-021 after its method-shaped operating model exposed contract leakage.
- [DEC-021](decisions/DEC-021-actor-artifact-capability-operating-model.md) - approved operating model: actors, activities, artifacts, capability ownership, lifecycle, and feedback without premature API contracts; supersedes DEC-020.




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
- [TST-010](tests/TST-010-milestone-1-live-corrections.md) - milestone-1 live corrections contract tests: expiry gating, session windows, decision log, catalog warmup, risk transition log per DEC-013.
- [TST-011](tests/TST-011-quant-api-contract-tests.md) - quant_api role-module contract tests: 48 tests + integration chain over the four role modules and shared core per DEC-017.

## Related notes

- [HOME](../enhanced/HOME.md) - frozen design canon anchor and vault entry point
- [style-guide](../enhanced/style-guide.md) - presentation standard reused by every ledger note
