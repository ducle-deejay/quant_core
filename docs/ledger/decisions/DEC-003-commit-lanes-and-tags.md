---
doc_id: DEC-003
title: Commit lanes, restoration tags, and no-rewrite history policy
type: decision
owner: research
status: resolved
version: 1.0
components: []
tags: [governance, git, recovery]
source: "owner concern: interleaved framework/kit commits make rollback confusing for future agents"
design: []
code: [.githooks/pre-commit, AGENTS.md]
test: []
---

# DEC-003 - Commit Lanes, Restoration Tags, and No-Rewrite History Policy

## 1. Decision

History stays append-only and unsplit; recoverability is achieved by path ownership plus permanent milestone tags instead of rewriting the past.

```text
    Lane prefixes   every commit message starts with one of:
                    [core]   product code (crates/, python/, examples/, Cargo files)
                    [kit]    governance tooling (AGENTS.md, .claude/, .githooks/,
                             scripts/, skills/, ledger.config.json)
                    [ledger] changes under docs/ledger/
                    [docs]   other docs/ content
    Milestone tags  git tag at every all-green state of a work stream;
                    existing: baseline-pre-kit, v0.2-governance-complete
    No rewrite      never rebase/force-push/filter published history;
                    restore forward via git checkout <ref> -- <paths>
```

## 2. Rationale

Path-level restore (`git checkout <ref> -- crates/`) already separates product from kit during recovery regardless of how interleaved commits look in `git log`. Prefixes make each lane filterable; tags remove the guesswork of finding a known-good point; the no-rewrite rule protects the audit trail that the ledger's credibility rests on.

## 3. Consequences

Future agents must pick the correct lane prefix and never rewrite history; both are now standing instructions in AGENTS.md. A physical off-machine backup (remote) is still recommended and remains an owner action. When the governance kit stabilises across projects, extracting it into its own repository is the long-term fix that removes the mixing at the source.

## Related notes

- [DEC-002](../decisions/DEC-002-multi-harness-kit.md) - kit whose commit stream this policy organises
