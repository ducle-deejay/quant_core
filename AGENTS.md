# AGENTS.md

## Purpose

The goal is to build a reusable systematic-trading framework that improves from operational outcomes and can evolve across markets and strategy styles.

When asked what the project is, what it is for, or what its goal is, answer at this end-state level.

## Consistent and unambiguous notation

Treat notation as a correctness boundary. Within a defined scope, use one stable name for one concept and one meaning for one name. Define non-obvious symbols, units, conventions, and namespaces before use; qualify collisions by owner, layer, or namespace. When established vocabularies differ, state their mapping and authority rather than silently renaming them. Resolve any plausible ambiguity before designing, implementing, or testing.

## Communication style

1. **Answer first.** The first sentence responds to what was asked. No greetings, no restating the request, no confirmation phrases, no closing summary, no offer of further help unless requested.
2. **Plain words.** No unexplained jargon and no invented shorthand. Abbreviations follow three tiers:

   - Universal software-engineering shorthand may stand as-is.
   - Names of specific tools, products, and repositories are proper nouns and stand as-is.
   - Domain-specific abbreviations of this project's field must have the full term written once beside their first appearance in a reply.
3. **Substance over ceremony.** Keep every detail needed for correctness; remove repetition, meta-commentary, and padding. This trims presentation only - never flatten the reasoning itself.

## Commit message format

Use `<type>(<scope>): <imperative summary>`.

- **Type:** `feat`, `fix`, `refactor`, `docs`, `test`, `chore`, `perf`, or `revert`.
- **Scope:** one short, stable name for the affected component.
- **Summary:** imperative present tense and states what the commit does.

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

## Harness notes

- Codex reads this file natively. Claude Code imports it via `CLAUDE.md`.
