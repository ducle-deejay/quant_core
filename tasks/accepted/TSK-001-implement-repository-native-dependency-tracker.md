---
task_id: TSK-001
title: "Implement repository-native dependency tracker"
priority: P0
assignee: quantitative-developer-main
depends_on: []
exclusive_resources: [task-tracker, repository-governance]
requirement_refs: [OBS-022]
attempt: 3
opened_by: owner
opened_at: 2026-09-05T08:49:24Z
started_at: 2026-09-06T06:59:31Z
blocked_reason:
submitted_at: 2026-09-06T07:00:21Z
rework_reason: "restore removed task-selection behavior and rename labels only"
accepted_by: owner
accepted_at: 2026-09-06T07:06:27Z
---
# TSK-001 - Implement repository-native dependency tracker

## Outcome

Provide a repository-native Markdown task tracker that makes the OBS-022 dependency plan visible as a directed acyclic graph and guards task opening, assignment, review, and acceptance without Linear or Symphony.

## Scope

Add status-bucket directories, a task template and charter, tracker configuration, a standard-library Python command, a task-discipline skill, agent routing rules, and pre-commit integration.

## Non-goals

Do not add a web interface, external service, database, automatic agent spawning, Git worktree isolation, or automatic release of downstream tasks.

## Inputs

Observation OBS-022, the owner-approved tracker design from this session, existing ledger conventions, and Symphony's separation between tracker state and agent execution.

## Outputs

A version-controlled Kanban board under `tasks/`, dependency and resource-aware commands in `scripts/task_tracker.py`, a task-discipline skill, and repository enforcement instructions.

## Behavior

The task directory is authoritative status. Only accepted dependencies permit opening; Human Owner opening remains explicit; starts are atomic; exclusive resources prevent concurrent conflicting starts; submission requires checked acceptance and validation evidence; only Human Owner acceptance unlocks downstream tasks.

## Acceptance criteria

- [x] Status folders act as the only task status and are documented.
- [x] The checker rejects malformed IDs, references, missing dependencies, dependency cycles, illegal status gates, and resource collisions.
- [x] The graph view derives dependency waves and resource-compatible parallel batches.
- [x] Open, start, verify-assignment, submit, accept, rework, block, resume, and cancel transitions enforce their authority and evidence gates.
- [x] Agent policy and the task-discipline skill require a successful start before tracker-governed implementation or delegation and support continuation after handover through `verify-assignment`.
- [x] The pre-commit hook runs both ledger and task checks.

## Validation

- [x] Exercise creation, opening, starting, submission, review, dependency, and resource-lock behavior in a disposable repository copy.
- [x] Spawn a bounded subagent and verify that assignment policy permits the recorded actor and rejects a different actor without edits.
- [x] Run the pre-commit hook against valid state and deliberately invalid task state in a disposable repository copy.
- [x] Run `python3 scripts/task_tracker.py check`, `python3 scripts/task_tracker.py graph`, and `python3 scripts/sweep_ledger.py` in the working repository.

## Evidence

- Before the vocabulary rename, a disposable repository clone exercised the complete transition behavior without adding test code; the rename changed command and metadata labels only.
- CLI discovery exposes `ready-to-open`, `ready-to-start`, `open`, `start`, and `verify-assignment`; the original selection behavior remains under clearer names.
- Draft content and absent requirement references prevented release; an unaccepted dependency prevented downstream release; a wrong actor and an overlapping `risk` resource prevented claims.
- Direct corruption produced malformed identifier, unresolved requirement, missing dependency, dependency-cycle, incomplete-evidence, and missing-owner-acceptance failures.
- The pre-commit hook exited successfully on the working repository and exited unsuccessfully when the disposable board contained an invalid accepted task.
- A fresh `gpt-5.6-luna` subagent with low reasoning and no conversation context asserted the recorded claim, reconstructed the tracker purpose and workflow from repository policy, and made no edits.
- `python3 scripts/task_tracker.py check`, `python3 scripts/task_tracker.py graph`, and `python3 scripts/sweep_ledger.py` completed successfully in the working repository before submission.

## Work log











- 2026-09-05T08:49:00Z Human Owner approved the MVP, status buckets, DAG plus atomic claim plus resource locks, explicit owner release, and policy/hook changes in this session.
- 2026-09-05T08:49:00Z Bootstrap note: implementation files began before the approved tracker policy existed; task TSK-001 was created immediately after that policy became active.

- 2026-09-05T08:49:24Z released by owner

- 2026-09-05T08:49:25Z claimed by quantitative-developer-main for attempt 1

- 2026-09-06 owner removed builder-authored tracker tests and required direct CLI, subagent-policy, and hook validation instead.
- 2026-09-06 implementation aligned with the repository ledger pattern: Markdown state, configured checker and transitions, AGENTS policy, task-discipline skill, and pre-commit backstop.

- 2026-09-06T06:32:37Z submitted for Human Owner review by quantitative-developer-main

- 2026-09-06T06:50:53Z rework requested by owner: rename unclear release and claim commands; remove redundant computed labels

- 2026-09-06T06:50:53Z claimed by quantitative-developer-main for attempt 2

- 2026-09-06 renamed task vocabulary without changing transition guards or lifecycle behavior.

- 2026-09-06 restored the task-selection queries removed during the first rename attempt; only their public names changed.

- 2026-09-06T06:56:34Z submitted for Human Owner review by quantitative-developer-main

- 2026-09-06T06:59:31Z rework requested by owner: restore removed task-selection behavior and rename labels only

- 2026-09-06T06:59:31Z started by quantitative-developer-main for attempt 3

- 2026-09-06T07:00:21Z submitted for Human Owner review by quantitative-developer-main

- 2026-09-06T07:06:27Z accepted by Human Owner owner
