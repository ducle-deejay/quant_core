---
name: ledger-discipline
description: Use when writing any note in docs/ledger (observation, reconciliation, decision, or test mapping), when code behaviour contradicts the frozen design canon in docs/enhanced, or when a commit touches a documented contract. Covers note anatomy, mandatory link fields, immutability rules, and worked examples.
---

# Ledger Discipline

## When this skill applies

Activate for: recording a bug or anomaly found while working; resolving a conflict between what `docs/enhanced/` promises and what the code does; making an architectural decision worth remembering; mapping new tests to the contracts they protect. If none of these apply, do not write ledger notes - ordinary work needs none.

## The one rule everything else serves

The design canon (`docs/enhanced/`) states intent and never changes. Reality that disagrees with it gets *recorded and judged*, never silently reconciled by editing either side. A judge-less edit is how drift was born; the ledger exists so every disagreement has a case file.

## Note anatomy

Every note lives under `docs/ledger/<class-dir>/` with file name `<CLASS>-<NNN>-<slug>.md` (NNN sequential per class, never reused). Front matter carries nine fields:

```yaml
doc_id: OBS-007            # class prefix + number
title: ...
type: observation          # observation | reconciliation | decision | case-study
owner: research
status: open               # open | triaged | resolved | superseded
version: 1.0
components: [1]            # canon component numbers touched
tags: [...]
source: "where this came from"
design: [STG-1-CANONICAL-SIM]   # MANDATORY: canon doc_ids, must resolve
code: [crates/...]              # MANDATORY: repo paths where behaviour lives
test: [test_name, ...]          # tests protecting the contract (decisions may omit)
```

Body sections follow REF-STYLE: numbered `## N.` headings, prose-first, formulas in ```text fences with definition lists below, wikilinks with full vault-relative paths.

## Class-specific rules

- **Observation** - what you SAW, with the evidence (test output, audit line, funnel numbers). Do not embed the fix.
- **Reconciliation** - the verdict on one observation: fix-code or accept-as-amendment. Record rejected alternatives with reasons; future-you will re-litigate otherwise. State semantics precisely enough that a stranger could re-implement.
- **Decision** - architectural choices with consequences stated honestly, including costs.
- **Test mapping** - which test names protect which contract, provoked by which observation. Living index: may be updated as the mapped set grows (the only class allowed this).

## Immutability

After a note reaches `resolved`, its content is history. Corrections happen by writing a NEW note whose Related section links back, then flipping the old note's status to `superseded`. Status transitions themselves (open -> triaged -> resolved) are lifecycle bookkeeping and are allowed.

## Worked examples in this repository

- Observation done right: `docs/ledger/observations/OBS-001-nan-warmup-poisoning.md` - propagation chain explained, tell-tale signature recorded, no fix mixed in.
- Reconciliation done right: `docs/ledger/reconciliations/REC-001-sanitize-scores-amendment.md` - verdict, rejected alternatives, precise amended semantics.
- Decision done right: `docs/ledger/decisions/DEC-001-frozen-canon-ledger-split.md`.

## Before you finish

1. Run `python3 scripts/sweep_ledger.py` - your note must not introduce broken design links, unknown statuses, or naming violations.
2. Update `docs/ledger/HOME.md` index with one bullet per new note.
3. If you added tests, cite the governing note id in a source comment near them.
