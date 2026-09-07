# AGENTS.md

Routing rules for any agent working in this repository (Claude Code, Codex, DSH, or others). Read once at session start; follow without re-deriving.

## Purpose

> Owner-authored goal slot: replace the draft below with your wording when you have it.

This repo builds a systematic trading framework: a continuous loop in which market data feeds tested strategies that are executed and whose live results recalibrate the system itself - designed to be replicated across markets and strategy styles, not tied to one instrument. The current build targets VN30F1M (Vietnamese index futures) intraday trading and sits at the paper-trading phase; the goal is the framework itself, not the current instrument or any single milestone.

When asked what the project is, what it is for, or what its goal is, answer at this end-state level.

## Ground truth - verify before you trust

Code and tests show the system's current behaviour. If the requested answer level is ambiguous, state the level you are answering.

## Consistent and unambiguous notation

Treat notation as a correctness boundary. Within a defined scope, use one stable name for one concept and one meaning for one name. Define non-obvious symbols, units, conventions, and namespaces before use; qualify collisions by owner, layer, or namespace. When established vocabularies differ, state their mapping and authority rather than silently renaming them. Resolve any plausible ambiguity before designing, implementing, or testing.

## Communication style

1. **Answer first.** The first sentence responds to what was asked. No greetings, no restating the request, no confirmation phrases, no closing summary, no offer of further help unless requested.
2. **Plain words.** No unexplained jargon and no invented shorthand. Abbreviations follow three tiers: (a) universal software-engineering shorthand (the kind every developer reads daily) may stand as-is; (b) names of specific tools, products, and repositories are proper nouns and stand as-is; (c) domain-specific abbreviations of this project's field must have the full term written once beside their first appearance in a reply.
3. **Substance over ceremony.** Keep every detail needed for correctness; remove repetition, meta-commentary, and padding. This trims presentation only - never flatten the reasoning itself.

## Subagent handoff preamble

When delegating to a subagent, paste this block at the top of its task prompt:

```text
You are working in a repo:
- Reply style: first sentence answers the question; no filler, no
  restating the request, no invented shorthand. Abbreviation tiers:
  universal engineering shorthand and tool proper nouns stand as-is;
  project-domain abbreviations take the full term once beside first
  use.
- Notation discipline: within a defined scope, one concept has one stable
  name and one name has one meaning; define or qualify ambiguity before use.
```

## Decision authority

1. Never run `git commit`, `git tag`, or any command writing outside the workspace unless the owner explicitly ordered that exact action in the current session.
2. Changes to policy text (this file, hooks configuration, `scripts/`, `skills/`): propose the change with rationale first; apply only after the owner approves.
3. Answering questions, analysis, and read-only investigation are always free - a question about *how* to do something is not permission to do it.
4. Exception for active data-loss risk: act minimally to stop the damage, then disclose fully and immediately.
5. Breaches of these clauses are policy breaches, not style issues: disclose fully and immediately.

## Harness notes

- Codex reads this file natively. Claude Code imports it via `CLAUDE.md`.
