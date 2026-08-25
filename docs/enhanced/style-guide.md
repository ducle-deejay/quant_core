---
doc_id: REF-STYLE
title: Documentation Style Guide
type: reference
owner: research
status: approved
version: 1.1
components: []
tags: [style-guide, conventions]
source: "discussion: readability reform of the knowledge vault"
---

# Documentation Style Guide

## 1. Purpose

All documents in this vault follow one presentation standard so that any reader can scan them fast, print them cleanly, diff them safely, and hand them to another person without translation loss. Content meaning never changes during formatting; frozen material stays in `docs/original/`.

## 2. Document classes and required front matter

Every file carries YAML front matter with exactly these fields:

```text
    ---
    doc_id:     STG-1-CANONICAL-SIM      # unique id, see scheme below
    title:      Canonical Simulation
    type:       specification            # specification | overview | reference | case-study | index
    owner:      research
    status:     approved                 # draft | approved | deprecated
    version:    1.0
    components: [1]                      # related component numbers, empty for cross-cutting docs
    tags:       [simulation]
    source:     "docs/original/pipeline_stages/... ; follow-up discussion: ..."
    ---
```

Identifier scheme: hubs use `STG-<n>-<SLUG>`; concept notes use `CON-<DOMAIN>-<SLUG>`; cross-cutting documents use `REF-*` and case studies `CASE-*`.

## 3. Headings

3.1 Second-level headings are numbered and descriptive: `## 1. Summary`, `## 2. Component contract`, `## 3. Specification`, `## 4. Worked example`, `## 5. Failure modes`, `## 6. Related notes`.

3.2 Third-level structure uses numbered bold lead-ins (`3.1 Short name.`) followed by prose, not deeper heading levels.

3.3 Blog vocabulary is banned. "TL;DR" becomes "Summary". Colloquialisms stay out of headings.

## 4. Formulas and notation

4.1 Every formula lives in its own code block, written in ASCII-safe symbols.

4.2 Immediately below every formula block sits an indented definition list: one line per symbol in the pattern `symbol   meaning - unit/source`. Constants count as symbols and carry provenance (source paper or convention).

4.3 The authoritative symbol registry is [notation](reference/notation.md).

```text
    Rule A   one symbol, one meaning vault-wide
    Rule B   local reuse of a symbol for a different sense requires an inline
             declaration at first use
    Rule C   a new symbol in a formula means a new row in the registry, added
             in the same change
```

4.4 Replacement rules for special characters:

```text
    arrow            ->  (or the word "to" in prose)
    multiplication   *   (or "x" in plain quantities such as "3 x capital")
    plus-minus       +/-
    comparisons      >= and <=
    summation        written out: "sum of absolute position changes"
    hat accents      spelled as suffix _est (sigma_hat becomes vol_est)
    greek letters    spelled out inside formulas (gamma, beta, lambda_s,
                     lambda_w); single capitals allowed in prose (z, L, c)
    check/cross      replaced by the words PASS and FAIL
```

## 5. Tables

5.1 A table is allowed only for genuine numeric comparison grids (for example, method-versus-Sharpe results).

5.2 All descriptive matrices become hierarchical bullets using the pattern `Name - statement`, or numbered clauses when order matters.

## 6. Prose rules

6.1 Every section opens with one to three complete sentences before any list. 6.2 Paragraphs stay short; one idea per paragraph. 6.3 Rules worth enforcing are stated as imperative sentences ("Do X", "Never Y"). 6.4 Clarifications of frozen original text appear in a paragraph starting "Clarification:" and always point back to the original passage location.

## 7. Cross references

Cross references use wikilinks containing the vault-root-relative path with the .md extension:

```text
    [supplementary-techniques](concepts/combination/supplementary-techniques.md)
    [stage-1-canonical-simulation](stages/stage-1-canonical-simulation.md)
```

Requirement: the previewer or vault must be rooted at docs/enhanced (or a parent folder) and must support path-style wikilinks. Plain markdown viewers do not navigate these; clicking an unresolvable link creates an empty note instead. Never write a bare-name wikilink without its path.

Each document ends with a "Related notes" section listing linked notes with a one-line descriptor.

## 8. Conversion status

Conversion of the vault to this standard is tracked in one place: all 40 files listed in [HOME](HOME.md) count as converted once they carry the front matter defined in section 2.

---
## Related notes
- [HOME](HOME.md) - vault entry point and index
- [glossary](glossary.md) - terminology distinctions and stable English terms

## 9. Layout, wrapping, and lists

9.1 Soft-wrap. A paragraph is ONE logical line: never hard-wrap prose at a fixed column. Viewers wrap to window width. Exceptions where newlines are literal: front matter, code blocks, tables.

9.2 Real lists. Every enumeration uses markdown list syntax at column zero - "- item" for bullets, "1. item" for ordered steps. Never fake a list with four-space indentation: markdown renders indentation as a code block, which strips styling and disables links inside the items.

9.3 Indentation is reserved for code-like content only: formulas, contract INPUT/OUTPUT blocks, diagrams, state machines, phase plans, and registry-style definition listings. Such blocks MUST be wrapped in a fenced block with the language tag "text" so viewers apply highlighting and a copy button:

    ```text
    INPUT : ...
    OUTPUT: ...
    ```
