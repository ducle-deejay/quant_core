---
doc_id: OBS-012
title: Daily ETL top-level config still points at the pre-restructure applications/ paths
type: observation
owner: research
status: resolved
version: 1.0
components: [6]
tags: [data, etl, config, restructure, launchagent, milestone-1]
source: "milestone-1 daily ETL first-run test, 2026-08-30"
design: [STG-1-CANONICAL-SIM]
code: [apps/data/daily/config/pipeline.json, apps/data/daily/pipeline.py, src/market_data/daily.py]
test: [src/market_data/tests/test_daily.py]
---

# OBS-012 - Daily ETL Config Still Points at Pre-Restructure `applications/` Paths

## 1. Finding

The daily ETL entrypoint could not load its child configs; two defects, both tracing to the repository
restructure (DEC-007, REC-007) which renamed `applications/` to `apps/`:

1. The top-level config `apps/data/daily/config/pipeline.json` still referenced the child configs as
   `applications/data/sources/{dnse,mirae}/config/pipeline.json` (pre-restructure paths; stale since the
   DEC-009 commit itself, which imported the nox sources with old paths and was never run).
2. The local `_resolve` helper in `apps/data/daily/pipeline.py` anchored relative paths at the config
   directory (`args.config.parent`), while the repo convention - including the sibling
   `_resolve_path` in `src/market_data/daily.py` - is repo-root-relative (`data/raw/...`, `data/catalog`).

Consequence: any run of `apps/data/daily/pipeline.py` (manual or via the `io.quant-core.daily-data-etl`
LaunchAgent at 16:00 Mon-Fri) crashed with `FileNotFoundError` at config load, before any source is reached
and before any Telegram alert is sent. Verified on 2026-08-30:

```text
FileNotFoundError: [Errno 2] No such file or directory:
'.../apps/data/daily/config/applications/data/sources/dnse/config/pipeline.json'
```

The LaunchAgent would have failed identically at its first scheduled 16:00 run; the bug was caught by the
manual first-run test before that happened.

## 2. Resolution

- `apps/data/daily/config/pipeline.json`: `applications/data/sources/...` -> `apps/data/sources/...` for
  both `dnse_config` and `mirae_config`.
- `apps/data/daily/pipeline.py`: `_resolve` now anchors at the repo root (`ROOT / path`), matching the
  `_resolve_path` convention; the `config.parent` anchor is removed.

No other live reference to `applications/` remains in the repo (the other matches are historical, inside
DEC-007 and REC-007).

## 3. Impact

- Manual ETL runs and the LaunchAgent now reach the actual DNSE + Mirae runners.
- The config path resolution is not protected by any test; a regression would surface only as a
  runtime crash. Candidate follow-up: a test asserting the two `*_config` paths resolve under
  `apps/data/sources/` (tracked here rather than silently added).
