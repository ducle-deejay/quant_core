---
doc_id: REC-004
title: DSH enforcement stays commit-level backstop until bridge matures
type: reconciliation
owner: research
status: resolved
version: 1.0
components: []
tags: [governance, dsh, backstop, amendment]
source: "owner decision on OBS-007; Option B accepted over building a native cordis plugin"
design: []
code: [.githooks/pre-commit, scripts/sweep_ledger.py]
test: []
---

# REC-004 - DSH Enforcement Stays Commit-Level Backstop Until Bridge Matures

## 1. Verdict

Option B accepted. On the DSH harness, protection of the frozen canon relies on the git pre-commit gate alone (rejecting any staged change under `docs/enhanced/` plus a passing ledger sweep). Within-session edits are guarded by instructions only, and this weakness is accepted as documented reality rather than hidden.

## 2. Rationale

The project's hard guarantee - the official design history can never be polluted - already holds through the pre-commit layer on every harness. Building a native cordis plugin would spend maintenance effort to move the blocking point earlier within sessions, while the rc-stage bridge may gain working interception on its own, making that plugin redundant. Revisit when the bridge leaves release-candidate status or when multi-agent same-session workflows make mid-session blocking genuinely necessary.

## 3. Consequences

The web-profile wiring (bridge packages plus patch entry) stays installed deliberately: when a mature bridge arrives, activation costs one restart instead of a reinstall. Until then the loaded plugin does nothing, which is harmless. The guard script, session banner, and invocation log remain in the repository serving Claude Code and Codex unchanged.

## Related notes

- [OBS-007](../observations/OBS-007-dsh-bridge-no-interception.md) - finding this verdict closes
- [DEC-002](../decisions/DEC-002-multi-harness-kit.md) - kit whose L2-on-DSH expectation is amended here
