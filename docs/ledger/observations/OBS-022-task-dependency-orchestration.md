---
doc_id: OBS-022
title: Task planning and agent orchestration workflow
type: observation
owner: research
status: open
version: 1.0
components: [0, 1, 2, 3, 4, 5, 6, 7]
tags: [agentic-engineering, task-planning, dependencies, orchestration, verification]
source: "owner-approved annotated response 2026-09-04: collaboration workflow for task planning, agent orchestration, and validation"
design: [OV-LIFECYCLE]
code: [AGENTS.md, docs/ledger/decisions/DEC-025-required-operating-supporting-artifacts.md]
test: []
---

# OBS-022 - Task Planning and Agent Orchestration Workflow

## 1. Finding

The implementation method needs an explicit collaboration workflow for turning the DEC-025 operating model into tasks, dependencies, an execution order, and validated releases. In this note, Human Owner means the project owner, and Requirements Agent means the agent collaborating with the Human Owner to plan and validate the work.

## 2. Task Planning

The Human Owner and Requirements Agent read the operating model, divide the work, and identify dependencies. The Requirements Agent proposes the execution order, including:

- which tasks can run in parallel;
- which tasks must wait;
- what each parallel task group must complete;
- which condition must be met before the next task is opened;
- where integration and review are needed before continuing.

## 3. GitHub Issue Creation

After the Human Owner and Requirements Agent agree on the plan, the Requirements Agent creates the GitHub Issues. Each issue must state:

- the required outcome;
- the scope and what will not be done;
- the input and output;
- the task blocking it;
- the tasks that depend on it;
- the behavior it must satisfy under DEC-025;
- the required tests or evidence;
- the conditions for completion.

## 4. Project Coordination and Agent Execution

The Human Owner uses the GitHub Projects interface to drag and drop tasks, set priorities, and assign tasks to agents. Symphony coordinates agents to execute the tasks that have been opened.

## 5. Completion Validation

When an agent reports completion, the Human Owner and Requirements Agent follow this sequence:

1. Use tests as a fast initial check.
2. Review the issue, code, and evidence together.
3. Compare the result with DEC-025 and the relevant canon.
4. Open the next dependent task only after the result is accepted.

## 6. Execution Sequence

The following example shows a parallel group, its integration task, and the next parallel group:

```text
Task A ---+
Task B ---+--- run in parallel
Task C ---+
           |
           v after all three are reviewed and accepted
Task D ------- integration
           |
           v
Task E and Task F run in parallel
```

## 7. Resolution Condition

This observation remains open until the selected engineering method incorporates this task-planning, orchestration, dependency, and validation workflow.

## Related Notes

The following notes define the operating model and the current engineering-method proposal to which this workflow applies:

- [DEC-025](../decisions/DEC-025-required-operating-supporting-artifacts.md) - triaged operating model from which tasks and dependencies will be derived.
- [OBS-021](OBS-021-agentic-requirements-engineering.md) - open proposal for converting the operating model into implementation requirements and verified work.
