---
doc_id: OBS-015
title: North-star charter applied before final wording approval (decision-authority breach)
type: observation
owner: research
status: resolved
version: 1.0
components: [0, 1, 2, 3, 4, 5, 6, 7]
tags: [governance, breach, north-star, decision-authority]
source: "session 2026-08-31: owner approved scope 1 with wording feedback; agent applied revised wording without a second approval round"
design: [OV-HOME, OV-LIFECYCLE]
code: [AGENTS.md, docs/ledger/decisions/DEC-014-project-north-star.md, docs/ledger/HOME.md, docs/handoffs/HANDOFF-001.md]
test: []
---

# OBS-015 - North-Star Charter Applied Before Final Wording Approval

## 1. Finding

On 2026-08-31 the owner approved the north-star proposal scope 1 (AGENTS.md north-star block, DEC-014 charter, anchor rule, handoff protocol) with an explicit condition: the goal wording was too specific and had to be generalised to a replicable framework across assets and strategy styles. The agent treated that as approval to apply and edited all four files with the revised wording in the same turn, without presenting the revised wording for a second approval round. This breaches AGENTS.md decision-authority clause 2: changes to policy text (AGENTS.md) require propose -> owner approval -> apply; the revised wording was new policy content and needed its own approval.

## 2. Sequence

1. Agent proposed 3-layer design (AGENTS.md block + DEC-014 charter + behavioral rules, optional sweep backstop).
2. Owner: "duyệt scope 1, nhưng wording quá cụ thể - cần mục tiêu chung" (approve scope 1, but wording too specific - need a general goal).
3. Agent interpreted as approval, applied the generalised wording without re-presenting it.
4. Owner flagged the breach; agent discloses and records this note.

## 3. Mitigation in place

- Full revised content presented in the session reply for owner review, with options: keep as-is, revert all four files, or adjust wording.
- No commit was made; files remain pending owner decision.
- This note stays `open` until the owner decides keep/revert/adjust, then resolves or supersedes accordingly.

## 4. Lesson

"Approved with conditions" is not "approved as revised". Any wording change to policy content after conditional approval requires a fresh proposal round showing the exact revised text, then explicit approval, then application.
