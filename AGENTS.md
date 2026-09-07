# AGENTS.md

Routing rules for any agent working in this repository (Claude Code, Codex, DSH, or others). Read once at session start; follow without re-deriving.

## Purpose

> Owner-authored goal slot: replace the draft below with your wording when you have it.

This repo builds a systematic trading framework: a continuous loop in which market data feeds tested strategies that are executed and whose live results recalibrate the system itself - designed to be replicated across markets and strategy styles, not tied to one instrument. The current build targets VN30F1M (Vietnamese index futures) intraday trading and sits at the paper-trading phase; the goal is the framework itself, not the current instrument or any single milestone.

When asked what the project is, what it is for, or what its goal is, answer at this end-state level. Milestones, sessions, and handoff notes describe where the project is now, not what it is for.

## Ground truth - verify before you trust

Statements about this project have an authority order; the first match you find is not necessarily the answer:

1. `docs/enhanced/` - frozen design canon. States intent, formulas, contracts; never changes. Design and goal questions end here.
2. `docs/ledger/` - living records (observations, reconciliations, decisions, test mappings). Notes are claims to read, not ground truth: they can contradict the canon or each other, and old notes may be superseded.
3. `docs/handoffs/` - session snapshots: current milestone, pending work, system state. Volatile by design; never a source for what the goal is.
4. Code - what the system actually does. Final arbiter for behaviour, not for intent.

Discovery rule: if your task depends on the goal, the design, or a contract, and you have not read the relevant canon document, you have not finished exploring. Do not stop at the first plausible-looking answer - a milestone table, a handoff section, or a README line is a snapshot, not ground truth. If canon and code disagree, say so explicitly and record it per the rules below; do not silently pick a side. If a question's expected answer level is ambiguous (goal vs current state), state which level you are answering at.

## Consistent and unambiguous notation

Treat notation as a correctness boundary. Within a defined scope, use one stable name for one concept and one meaning for one name. Define non-obvious symbols, units, conventions, and namespaces before use; qualify collisions by owner, layer, or namespace. When established vocabularies differ, state their mapping and authority rather than silently renaming them. Resolve any plausible ambiguity before designing, implementing, or testing.

## Project map

- `docs/enhanced/` - **frozen design canon**. States intent, formulas, contracts. NEVER edit, never delete. There is no exception for agents.
- `docs/ledger/` - **the only living documentation layer**. Observations, reconciliations, decisions, test mappings.
- `docs/ledger/HOME.md` - ledger charter and index; read before writing any note.
- `ledger.config.json` - kit parameters (protected paths, note classes, statuses).
- `scripts/canon_guard.py` - PreToolUse guard blocking edits into the canon.
- `scripts/sweep_ledger.py` - drift-debt report; must pass before every commit.

## Rules (condensed from docs/ledger/HOME.md)

1. Never write inside `docs/enhanced/`. If code behaviour contradicts the design there, record an observation note in `docs/ledger/observations/` and a reconciliation verdict in `docs/ledger/reconciliations/`.
2. Any change touching a documented contract adds or updates a ledger note in the same change, referencing the canon doc_id.
3. Ledger notes are append-only after resolution: supersede with a new note, never rewrite history.
4. Tests derived from design intent, never from current behaviour. Cite the governing note id in a source comment near the test.
5. Run `python3 scripts/sweep_ledger.py` before committing; a failing sweep is a blocked commit.

## Communication style

1. **Answer first.** The first sentence responds to what was asked. No greetings, no restating the request, no confirmation phrases, no closing summary, no offer of further help unless requested.
2. **Plain words.** No unexplained jargon and no invented shorthand. Abbreviations follow three tiers: (a) universal software-engineering shorthand (the kind every developer reads daily) may stand as-is; (b) names of specific tools, products, and repositories are proper nouns and stand as-is; (c) domain-specific abbreviations of this project's field must have the full term written once beside their first appearance in a reply. When naming a tracked artifact by identifier, pair it with a word for what it is at least once per reply - pattern `<kind> <identifier>`; the kind words come from the `note_classes` mapping in `ledger.config.json`.
3. **Substance over ceremony.** Keep every detail needed for correctness; remove repetition, meta-commentary, and padding. This trims presentation only - never flatten the reasoning itself.

## Subagent handoff preamble

When delegating to a subagent, paste this block at the top of its task prompt:

```text
You are working in a repo with governance:
- docs/enhanced/ is FROZEN: never edit it. Blocked edits are expected.
- Behaviour/design conflicts go to docs/ledger/ as notes
  (see docs/ledger/HOME.md for anatomy).
- Run python3 scripts/sweep_ledger.py before any commit.
- Reply style: first sentence answers the question; no filler, no
  restating the request, no invented shorthand. Abbreviation tiers:
  universal engineering shorthand and tool proper nouns stand as-is;
  project-domain abbreviations take the full term once beside first
  use. Pair any artifact identifier with a word for what it is at
  least once (pattern: "<kind> <identifier>"; kinds live in
  ledger.config.json).
- Notation discipline: within a defined scope, one concept has one stable
  name and one name has one meaning; define or qualify ambiguity before use.
```

## Decision authority

1. Never run `git commit`, `git tag`, or any command writing outside the workspace unless the owner explicitly ordered that exact action in the current session.
2. Changes to policy text (this file, hooks configuration, `scripts/`, `skills/`, `ledger.config.json`): propose the change with rationale first; apply only after the owner approves.
3. Answering questions, analysis, and read-only investigation are always free - a question about *how* to do something is not permission to do it.
4. Exception for active data-loss risk: act minimally to stop the damage, then disclose fully and immediately.
5. Breaches of these clauses are policy breaches, not style issues: disclose fully and immediately, and record them in the ledger where the affected project keeps one.

## Harness notes

- Codex reads this file natively. Claude Code imports it via `CLAUDE.md`.
- The file-level guard runs on Claude Code and on DSH through the official `dsh-hooks-claude-code` bridge (both consume `.claude/hooks.json`). Codex uses its own `[hooks]` config pointing at the same script.
- The git pre-commit hook (`.githooks/pre-commit`) is the final backstop on every harness: it rejects staged canon changes and failing ledger or task-tracker checks regardless of model behaviour.
