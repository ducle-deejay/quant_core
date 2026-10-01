# AGENTS.md

## Purpose

The goal is to build a reusable systematic-trading framework that improves from operational outcomes and can evolve across markets and strategy styles.

When asked what the project is, what it is for, or what its goal is, answer at this end-state level.

## Consistent and unambiguous notation

Treat notation as a correctness boundary. Within a defined scope, use one stable name for one concept and one meaning for one name. Define non-obvious symbols, units, conventions, and namespaces before use; qualify collisions by owner, layer, or namespace. When established vocabularies differ, state their mapping and authority rather than silently renaming them. Resolve any plausible ambiguity before designing, implementing, or testing.

## Comments and docstrings

A comment states only what the code cannot: why it is written this way, or an
outside fact it depends on.

1. **Code is the authority.** Treat every comment as an unverified claim. When a
   comment and the code disagree, the code wins; check the code before relying on
   a comment for a design or an edit.
2. **Outside facts carry evidence.** A claim about a venue, SDK, library, or market
   rule is verified (repo data and code, official documentation, or the user) and
   names its source. Do not write hedged claims; ask the user when a fact cannot
   be verified.
3. **No cross-file sync claims.** Do not write that code matches, mirrors, or
   follows another file; enforce that with shared code or a test.
4. **Describe, do not prescribe.** No setup, deployment, or workflow instructions
   in source; those belong in documentation.
5. **No restatement.** Omit docstrings that repeat the name, signature, or type,
   and labels that carry no information.
6. **Framework terms keep their meaning.** Do not reuse a term the framework
   defines for a different concept.

## Communication style

1. **Answer first.** The first sentence responds to what was asked. No greetings, no restating the request, no confirmation phrases, no closing summary, no offer of further help unless requested.
2. **Plain words.** No unexplained jargon and no invented shorthand. Abbreviations follow three tiers:

   - Universal software-engineering shorthand may stand as-is.
   - Names of specific tools, products, and repositories are proper nouns and stand as-is.
   - Domain-specific abbreviations of this project's field must have the full term written once beside their first appearance in a reply.
3. **Substance over ceremony.** Keep every detail needed for correctness; remove repetition, meta-commentary, and padding. This trims presentation only - never flatten the reasoning itself.
4. **No filler.** Do not use stock openings or endings such as “Sure”, “Understood”, “In summary”, or “Let me...”. Do not repeat the request, the context, or a point already made. Include only content that answers the question or supports the decision.

## Commit message format

Follow this template exactly:

    <type>(<scope>): <imperative summary>

    Problem: <what was wrong or missing, and why it arose>

    Fix:
    - <area>: <what changed>

- **Type:** `feat`, `fix`, `refactor`, `docs`, `test`, `chore`, `perf`, or `revert`.
- **Scope:** one short, stable name for the affected component.
- **Summary:** imperative present tense and states what the commit does.

The message is read by people new to the code and by agents tracing history.

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
- Comments are claims, not ground truth: verify against the code before
  relying on them.
```

## Harness notes

- Codex reads this file natively. Claude Code imports it via `CLAUDE.md`.
