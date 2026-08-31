---
doc_id: DEC-015
title: AGENTS.md instruction style v2 - purpose statement plus ground-truth discovery rules
type: decision
owner: research
status: resolved
version: 1.0
components: [0, 1, 2, 3, 4, 5, 6, 7]
tags: [agents, governance, goal, discovery, anti-anchoring]
source: "owner-approved rewrite 2026-08-31 after review of the north-star section (OBS-015 follow-up)"
design: [OV-HOME, OV-LIFECYCLE]
code: [AGENTS.md, docs/handoffs/HANDOFF-001.md, docs/ledger/decisions/DEC-014-project-north-star.md]
---

# DEC-015 - AGENTS.md Instruction Style v2

## 1. Decision

Rewrite the goal guidance in AGENTS.md from the "North star - ultimate goal" section (jargon heading, five numbered invariants, anchor rule) to two plain sections: **Purpose** (end-state description of the project, owner-editable) and **Ground truth - verify before you trust** (authority order plus discovery rule). The north-star charter itself (DEC-014) is unchanged and remains the authoritative record; AGENTS.md no longer duplicates it or points to ledger files as ground truth.

## 2. Rationale

- The v1 section was abstract jargon ("north star") with no verifiable referent in the repo, duplicated DEC-014, and its prescriptive phrasing ("optimise for the framework", anchor rule) biased agent reasoning instead of informing it - the failure mode observed as premature satisficing at the wrong abstraction level (agent answered the goal question at milestone/current-state level).
- Best practice for agent instruction files: short, high-signal, concrete; no restating of what an agent can explore; no vague or conflicting directives.
- Ledger files are living claims, not ground truth; pointing agents at them as authoritative invites drift when notes age. Canon (`docs/enhanced/`) is the frozen ground truth for design and goal questions; handoffs are volatile snapshots and never a source for the goal.
- Purpose is written at end-state level so goal questions are answered at the right abstraction level by default.

## 3. Content of the v2 sections (summary)

- Purpose: the repo builds a systematic trading platform - a pipeline turning market data into tested strategies and executing them, designed to be replicated across markets and strategy styles, not tied to one instrument. Current build: VN30F1M intraday futures, paper-trading stage. Goal questions are answered at this end-state level; milestones/handoffs describe current state, not the goal. Wording is an owner-editable slot.
- Ground truth: authority order 1) frozen canon, 2) ledger notes (claims to read, may contradict canon or each other), 3) handoffs (snapshots), 4) code (final arbiter for behaviour, not intent). Discovery rule: a task depending on goal/design/contract is not finished until the relevant canon document is read; the first plausible-looking answer (milestone table, handoff section, README line) is not ground truth; canon/code disagreement is reported and recorded, never silently resolved; ambiguous answer levels are declared explicitly.

## 4. Status of related records

DEC-014 stays resolved and unchanged; its presentation pointer to "the north star at the top of AGENTS.md" is superseded by this note's wording. No canon document was edited.
