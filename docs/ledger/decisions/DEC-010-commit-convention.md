---
doc_id: DEC-010
title: Commit convention - conventional commits with fixed type and scope vocabulary
type: decision
owner: research
status: resolved
version: 1.0
components: []
tags: [convention, git, commits, audit]
source: "owner discussion 2026-08-30: history must be scannable by type/scope/summary; adopted over generic 'squash process commits' advice because the ledger already preserves architectural decisions durably"
design: []
code: []
test: []
---

# DEC-010 - Commit Convention: Conventional Commits

## 1. Decision

Every commit message follows `<type>(<scope>): <imperative summary>` (conventional commits):

- **Type** (fixed vocabulary, no inventions): `feat`, `fix`, `refactor`, `docs`, `test`, `chore`, `perf`, `revert`.
- **Scope** (fixed vocabulary, one per commit): `alpha-core` (Rust engine + bindings), `market-data` (pipeline, ETL, notification transport), `trading` (live platform: adapters, bridge, risk, node, paper runner), `ledger` (docs/ledger notes), `repo` (repository-level config and structure).
- **Summary**: imperative present tense, explains what the commit does (add, port, relocate, fix...), may cite the governing ledger note id (e.g. `(DEC-007)`).

## 2. History rules

- Pre-push: amend/squash freely; a follow-up fix belonging to an unpushed commit is folded into it, never left as a standalone "fix fix" pair.
- Post-push: never rewrite; corrections become new commits.
- Rewrite history only with a concrete goal (wrong grouping, convention migration); never rebase periodically "for cleanliness".
- Architectural decisions are preserved by the ledger (DEC/OBS/REC/TST notes are append-only and do not reference commit hashes), so squashing commits never loses decision history.

## 3. Rationale

- `git log --grep="^feat"` / `^fix` / scope filters give fast scanning; changelog generation is possible without tooling.
- A fixed scope vocabulary keeps filters stable; ad-hoc scopes destroy the benefit.
- The imperative summary answers "what did this commit actually do" without opening the diff.

## Related notes

- [HOME](HOME.md) - ledger index; commit discipline is part of the kit
