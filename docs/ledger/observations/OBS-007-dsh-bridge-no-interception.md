---
doc_id: OBS-007
title: DSH hooks bridge rc.5 loads but never intercepts harness-native file edits
type: observation
owner: research
status: resolved
version: 1.0
components: []
tags: [governance, dsh, hooks, compatibility]
source: "controlled headless + web experiments across three agent contexts and two restarts; full evidence in note body"
design: []
code: [.claude/hooks.json, scripts/canon_guard.py, scripts/session_banner.py]
test: []
---

# OBS-007 - DSH Hooks Bridge rc.5 Loads But Never Intercepts Harness-Native File Edits

## 1. Summary

The official `@deepseek-ai/dsh-hooks-claude-code@0.0.1-rc.5` bridge was fully wired into the web profile (insert-list patch, verified in the composed config tree) and the headless profile (same overlay). The plugin imports cleanly at runtime after installing its peer dependency `@deepseek-ai/dsh-hook-protocol`. Despite this, across every tested context - the main web session, a spawned subagent, and two isolated headless boots with natural completion - an agent editing a file under the frozen canon was never blocked, and the guard script's invocation log recorded zero hook executions.

## 2. Evidence

Elimination table from the experiments:

```text
    package import            IMPORT OK: [Config, apply, inject, name]
    composed tree             insert entry present with absolute configPath
    boot health               exit 0 on headless; web boots to serving line
    matcher hypothesis        broadened to (?i).*(edit|write|patch).*
    config format hypothesis  both settings-wrapped and bare shapes tested
    invocation log            /tmp/canon_guard.log stayed at baseline
                              through all probes
    outcome                   agents freely appended lines inside the
                              canon; each write required manual revert
```

No loader warning, parse warning, or registration message ever appeared in any captured output; headless stdout carries only the final agent answer, so the bridge fails silently by design ("contained failure" behaviour).

## 3. Proposed verdicts (triaged, decision open)

- Option A: build a minimal NATIVE cordis plugin subscribing directly to `tools/pre-execute` (the official interception note states native plugins can do everything the bridge does, more powerfully). Estimated as a small TypeScript package; removes the rc bridge from the trust surface.
- Option B: stay on the git pre-commit backstop for DSH until the bridge leaves release-candidate status, accepting that within-session edits are instruction-guarded only.

Either resolution closes this note; Option A additionally supersedes part of DEC-002's harness notes.

## Related notes

- [DEC-002](../decisions/DEC-002-multi-harness-kit.md) - kit whose L2 layer is affected

## Resolution

Closed by [REC-004](../reconciliations/REC-004-backstop-only-dsh.md): Option B accepted - commit-level backstop only on DSH until the bridge matures.
