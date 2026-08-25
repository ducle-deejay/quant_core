# AGENTS.md

Routing rules for any agent working in this repository (Claude Code, Codex, DSH, or others). Read once at session start; follow without re-deriving.

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

## Subagent handoff preamble

When delegating to a subagent, paste this block at the top of its task prompt:

```text
You are working in a repo with governance:
- docs/enhanced/ is FROZEN: never edit it. Blocked edits are expected.
- Behaviour/design conflicts go to docs/ledger/ as notes
  (see docs/ledger/HOME.md for anatomy).
- Run python3 scripts/sweep_ledger.py before any commit.
```

## Harness notes

- Codex reads this file natively. Claude Code imports it via `CLAUDE.md`.
- The file-level guard runs on Claude Code and on DSH through the official `dsh-hooks-claude-code` bridge (both consume `.claude/hooks.json`). Codex uses its own `[hooks]` config pointing at the same script.
- The git pre-commit hook (`.githooks/pre-commit`) is the final backstop on every harness: it rejects staged canon changes and failing sweeps regardless of model behaviour.
