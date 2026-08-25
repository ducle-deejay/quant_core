---
doc_id: REF-TEMPLATE
title: Note Template and Authoring Rules
type: reference
owner: research
status: approved
version: 1.1
components: []
tags: [template]
source: "supersedes the old skeleton; aligned with REF-STYLE"
---

# Note Template and Authoring Rules

## 1. Purpose

One idea per note, one presentation standard everywhere. Copy the skeleton below for every new note.

## 2. Skeleton

```text
    ---
    doc_id:     CON-<DOMAIN>-<SLUG>
    title:      <Concept Name>
    type:       specification
    owner:      research
    status:     draft
    version:    0.1
    components: [<n>]
    tags:       [...]
    source:     "origin of the content"
    ---

    # <Concept Name>

    ## 1. Summary
    Two or three prose sentences. A reader stopping here still gets the point.

    ## 2. Specification
    Numbered clauses. Formulas in code blocks with variables defined beneath.
    Tables only for genuine numeric grids.

    ## 3. Failure modes
    Optional; numbered traps with preventions.

    ---
    ## Related notes
    - [[concepts/evaluation/post-mortem.md]] - one-line descriptor
```


## 3. Rules

3.1 File names kebab-case without dates. 3.2 Cross references use path-style wikilinks, paths relative to docs/enhanced, e.g. [[concepts/evaluation/post-mortem.md]]. Previewer must support path-style wikilinks and be rooted at docs/enhanced or a parent. 3.3 Provenance lives in source front matter; inline provenance reads "(from follow-up: topic)". 3.4 Never duplicate content that exists in another note - link instead. 3.5 Follow [[style-guide.md]] for notation, headings, and table policy.
