---
doc_id: REF-STYLE
title: Documentation Style Guide
type: reference
owner: research
status: approved
version: 1.0
components: []
tags: [style-guide, conventions]
source: "discussion: readability reform of the knowledge vault"
---

# Documentation Style Guide

## 1. Purpose

All documents in this vault follow one presentation standard so that any reader
can scan them fast, print them cleanly, diff them safely, and hand them to
another person without translation loss. Content meaning never changes during
formatting; frozen material stays in `docs/original/`.

## 2. Document classes and required front matter

Every file carries YAML front matter with exactly these fields:

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

Identifier scheme: hubs use `STG-<n>-<SLUG>`; concept notes use
`CON-<DOMAIN>-<SLUG>`; cross-cutting documents use `REF-*` and case studies
`CASE-*`.

## 3. Headings

3.1 Second-level headings are numbered and descriptive:
`## 1. Summary`, `## 2. Component contract`, `## 3. Specification`,
`## 4. Worked example`, `## 5. Failure modes`, `## 6. Related notes`.

3.2 Third-level structure uses numbered bold lead-ins (`3.1 Short name.`)
followed by prose, not deeper heading levels.

3.3 Blog vocabulary is banned. "TL;DR" becomes "Summary". Colloquialisms stay
out of headings.

## 4. Formulas and notation

4.1 Every formula lives in an indented or fenced code block on its own line,
written in ASCII-safe symbols.

4.2 Standard symbol set (defined once here, reused everywhere):

    p(t)         position at bar t, in multiples of capital (notional)
    z(t)         standardized score at bar t
    r(t)         asset return over bar t
    c            cost per unit notional per side (fee + half-spread [+ buffer])
    L            leverage cap policy, in multiples of capital
    vol_target   declared volatility target, converted to bar frequency
    vol_est(t)   estimated volatility at bar t
    TO(t)        turnover at bar t, equal to abs(p(t) - p(t-1))
    IC(h)        Information Coefficient at horizon h
    h_star       estimated holding period
    N_eff        effective number of independent trials
    w(i)         weight of alpha i
    m            de-risking multiplier in [0, 1]

4.3 Replacement rules for special characters:

    arrow            ->  (or the word "to" in prose)
    multiplication   *   (or "x" in plain quantities such as "3 x capital")
    plus-minus       +/-
    comparisons      >= and <=
    summation        written out: "sum of absolute position changes"
    hat accents      spelled as suffix _est (sigma_hat becomes vol_est)
    greek letters    spelled out inside formulas (gamma, beta, lambda);
                     single capitals allowed in prose (z, L, c)
    check/cross      replaced by the words PASS and FAIL

4.4 Every variable used in a formula is defined immediately below the block as
an indented list.

## 5. Tables

5.1 A table is allowed only for genuine numeric comparison grids (for example,
method-versus-Sharpe results).

5.2 All descriptive matrices become hierarchical bullets using the pattern
`Name - statement`, or numbered clauses when order matters.

## 6. Prose rules

6.1 Every section opens with one to three complete sentences before any list.
6.2 Paragraphs stay short; one idea per paragraph.
6.3 Rules worth enforcing are stated as imperative sentences ("Do X", "Never Y").
6.4 Clarifications of frozen original text appear in a paragraph starting
"Clarification:" and always point back to the original passage location.

## 7. Cross references

Cross references use wikilinks containing the vault-root-relative path with the
.md extension:

    [[concepts/combination/supplementary-techniques.md]]
    [[stages/stage-1-canonical-simulation.md]]

Requirement: the previewer or vault must be rooted at docs/enhanced (or a parent
folder) and must support path-style wikilinks. Plain markdown viewers do not
navigate these; clicking an unresolvable link creates an empty note instead.
Never write a bare-name wikilink without its path.

Each document ends with a "Related notes" section listing linked notes with a
one-line descriptor.

## 8. Conversion status

Conversion of the vault to this standard is tracked in one place: all 40 files
listed in [[HOME.md]] count as converted once they carry the front matter defined
in section 2.

---
## Related notes
- [[HOME.md]] - vault entry point and index
- [[glossary.md]] - terminology distinctions and stable English terms
