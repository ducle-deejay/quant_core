---
doc_id: DEC-016
title: Purpose wording corrected to loop vocabulary - supersedes the DEC-015 section-3 quote
type: decision
owner: research
status: resolved
version: 1.0
components: [0, 1, 2, 3, 4, 5, 6, 7]
tags: [agents, vocabulary, goal, wording, governance]
source: "owner-ordered correction 2026-08-31: AGENTS.md Purpose must not describe the system as a linear pipeline"
design: [OV-HOME, OV-LIFECYCLE]
code: [AGENTS.md]
---

# DEC-016 - Purpose Wording Correction: Loop Vocabulary

## 1. Decision

The AGENTS.md Purpose sentence is corrected from pipeline framing ("a systematic trading platform: a pipeline that turns market data into tested strategies and executes them") to loop framing: "a systematic trading framework: a continuous loop in which market data feeds tested strategies that are executed and whose live results recalibrate the system itself - designed to be replicated across markets and strategy styles, not tied to one instrument." This supersedes the wording quoted in DEC-015 section 3, which is historical; the DEC-015 decision itself (instruction style v2) is unchanged.

## 2. Rationale

Per OV-LIFECYCLE, the system is components with input/output contracts running as a continuous loop with feedback edges, not a straight line. "Pipeline" framing primes linear one-directional reasoning and drops the feedback recalibration that is a core invariant; it also reintroduces the vocabulary confusion the canon resolves. "Pipeline" survives only as data-flow ordering inside the loop (the canon itself speaks of "pipeline components"), never as a description of the system as a whole.
