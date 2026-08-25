---
doc_id: DEC-002
title: Multi-harness ledger kit adopted as repo governance
type: decision
owner: research
status: resolved
version: 1.0
components: []
tags: [governance, drift-control, tooling]
source: "discussion: enforcing ledger rules across sessions, subagents, and harnesses without token waste"
design: []
code: [ledger.config.json, scripts/canon_guard.py, scripts/sweep_ledger.py, .claude/hooks.json, .claude/settings.json, .githooks/pre-commit, AGENTS.md, CLAUDE.md, skills/ledger-discipline]
test: []
---

# DEC-002 - Multi-Harness Ledger Kit Adopted as Repo Governance

## 1. Decision

Governance enforcement is layered by cost, so that following the ledger costs almost no context and violating it is expensive at every level:

```text
    L1   AGENTS.md (CLAUDE.md imports it) - routing rules, ~once per session
    L2   .claude/hooks.json + canon_guard.py - blocks canon edits pre-write;
         identical script serves Claude Code, Codex config, and the official
         dsh-hooks-claude-code bridge on DSH
    L3   skills/ledger-discipline - full note-writing procedure, loaded only
         when actually writing notes (progressive disclosure)
    L4   subagent handoff preamble in AGENTS.md - pasted into delegated tasks
    Backstop: .githooks/pre-commit runs sweep_ledger.py and rejects any
    staged change under the canon; process-level, works on every harness
```

All project-specific values (protected paths, note classes, statuses) live in `ledger.config.json`; the kit ports to another project by copying files and editing that one config.

## 2. Known operating conditions (from the official bridge README)

The DSH hook bridge parses its config once per boot with process-level paths: use an absolute `configPath` or always launch from the project root. It executes shell-command hooks only. A broken hook configuration logs a warning and degrades to no-hooks rather than failing loudly - which is precisely why the git backstop is mandatory, not optional.

## 3. Consequences

Every future session and every subagent meets the same rules through whichever layer its harness supports; nothing depends on model memory or goodwill. The cost is one config file plus a small standing context tax (~a few hundred tokens) per session.

## Related notes

- [DEC-001](DEC-001-frozen-canon-ledger-split.md) - the frozen-canon split this kit enforces mechanically
