# Repository Task Tracker

This directory is operational task state, not a second documentation authority. Design intent remains in `docs/enhanced/`, living governance records remain in `docs/ledger/`, and task files describe bounded work derived from those sources.

The tracker is repository-native so task state stays with the code, works across agent harnesses, and survives chat loss, context reset, or agent handover without depending on Linear or Symphony availability.

## Board

Each task is one Markdown file under exactly one status directory. The directory is the only authoritative task status; task front matter must not contain a `status` field.

```text
backlog        planned, but not opened by the Human Owner
ready          opened by the Human Owner and available to start
in_progress    assigned to one agent and being worked
human_review   implementation and evidence await Human Owner review
rework         Human Owner rejected the current result; another attempt is required
blocked        an external blocker prevents progress
accepted       Human Owner accepted the result; satisfies downstream dependencies
cancelled      terminal without satisfying downstream dependencies
```

A task waiting for another task remains in `backlog`; `blocked` is reserved for external blockers such as missing access, secrets, permissions, or owner decisions.

## Dependency and concurrency model

- `depends_on` is the only stored dependency direction. Reverse edges, topological order, and parallel waves are derived.
- Only `accepted` satisfies a dependency.
- Completing dependencies does not automatically move a backlog task to `ready`; the Human Owner explicitly opens it.
- `exclusive_resources` names logical write or integration boundaries. Tasks sharing a resource cannot occupy `in_progress`, `human_review`, `rework`, or `blocked` simultaneously.
- An integration task depends on every task in the parallel group it integrates.

## Task workflow

```bash
python3 scripts/task_tracker.py check
python3 scripts/task_tracker.py board
python3 scripts/task_tracker.py graph
python3 scripts/task_tracker.py ready-to-open
python3 scripts/task_tracker.py ready-to-start
python3 scripts/task_tracker.py new --title "..." --priority P1
python3 scripts/task_tracker.py open TSK-001 --by owner
python3 scripts/task_tracker.py start TSK-001 --actor agent-a
python3 scripts/task_tracker.py verify-assignment TSK-001 --actor agent-a
python3 scripts/task_tracker.py submit TSK-001 --actor agent-a
python3 scripts/task_tracker.py accept TSK-001 --by owner
```

Use `block`, `resume`, `rework`, or `cancel` for exceptional transitions. Run `python3 scripts/task_tracker.py <command> --help` for command arguments.

## Human and agent authority

- The Human Owner and Requirements Agent plan tasks and dependencies together.
- Only the Human Owner opens, accepts, rejects for rework, or cancels tasks. The script records the configured owner actor but is a coordination control, not an authentication system.
- Read-only inspection and planning do not require assignment; editing tracker-governed implementation does.
- A main agent must start a task before editing or delegating it. After a handover or context reset, the succeeding main agent resumes by verifying the recorded task and actor with `verify-assignment`. A delegated agent must verify that same task and actor before editing.
- An agent submission is not completion. Only the move to `accepted` unlocks dependent work.

## Commit gate

`python3 scripts/task_tracker.py check` validates identifiers, front matter, requirement references, dependency existence, cycles, status gates, resource collisions, review evidence, and acceptance evidence. Pending work does not fail the check; structural or lifecycle violations do.
