---
doc_id: REC-005
title: Proof-of-concept scripts moved from research to examples
type: reconciliation
owner: research
status: resolved
version: 1.0
components: [0]
tags: [restructure, examples, paths]
source: "owner decision: the research folder name misdescribes demonstration scripts"
design: [STG-0-ALPHA-MINING, CASE-SEED-DEMO]
code: [examples/alpha_ic_demo.py, examples/fitness_proxy_vs_canonical.py, examples/seed_alpha_demo.py, examples/verify_real_data.py]
test: []
---

# REC-005 - Proof-of-Concept Scripts Moved From research to examples

## 1. Verdict

The directory `research/` is renamed `examples/` via git move (history preserved). The name research misdescribed its contents: four standalone demonstration scripts that prove pipeline behaviour, not ongoing investigation. The new name matches what they are - runnable examples a newcomer can execute before touching the Rust core.

## 2. Path mapping

```text
    OLD                                   NEW
    research/alpha_ic_demo.py             examples/alpha_ic_demo.py
    research/fitness_proxy_vs_canonical.py  examples/fitness_proxy_vs_canonical.py
    research/seed_alpha_demo.py           examples/seed_alpha_demo.py
    research/verify_real_data.py          examples/verify_real_data.py
```

Run commands inside the scripts were updated to their new paths. Nothing else in the repository executes or imports them.

## 3. Frozen documents keep old paths by design

Three canon files mention the old location (the Component 0 hub, the vault index, and the seed-alpha-demo case study). Per the preservation rule they stay untouched; this note is the authoritative pointer. Any reader landing on an old path should read it as `examples/<same file name>`.

## Related notes

- [STG-0-ALPHA-MINING](../../enhanced/stages/stage-0-alpha-mining.md) - canon hub naming the companion script
