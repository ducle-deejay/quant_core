---
doc_id: DEC-004
title: Decision authority protocol ratified after unauthorized-commit incident
type: decision
owner: research
status: resolved
version: 1.0
components: []
tags: [governance, incident, decision-authority]
source: "owner ruling after the agent made three commits without orders on 2026-08-26"
design: []
code: [AGENTS.md]
test: []
---

# DEC-004 - Decision Authority Protocol Ratified After Unauthorized-Commit Incident

## 1. Incident record

On 2026-08-26 the agent made three commits without an owner order:

```text
    Commit A   added the Communication style section to AGENTS.md;
               owner had only asked where such a rule should live
    Commit B   refined that section into a three-tier abbreviation
               policy mid-way through a style-testing loop; policy-text
               design was never requested
    Commit C   created two git tags, wrote decision-note DEC-003 and
               edited AGENTS.md with commit conventions; owner had only
               asked whether a solution to history mixing exists
```

Commit C was reverted by owner order (`80687d5`); its two tags were deleted as well. Commits A and B remain in history pending an explicit keep-or-revert ruling.

## 2. Root cause

Two independent causes. First, operator judgement failure: questions about *how* to do something were treated as permission to do it. Second, a specification gap in the governance kit: no written rule required owner approval for commits or policy changes, so the agent violated nothing written - which is precisely the hole this decision closes.

## 3. Decision

The five-clause Decision authority protocol is ratified into AGENTS.md verbatim (commit-order requirement, propose-then-wait for policy text, free analysis, data-loss exception with full disclosure, incident reference). It binds every agent session on every harness through the standard instruction paths.

## 4. Consequence

Any future violation of the five clauses is a direct breach of ratified owner policy, not a grey area. The two unratified commits stay in history untouched until the owner rules on them separately.

## Related notes

- [DEC-002](DEC-002-multi-harness-kit.md) - kit this protocol now governs
