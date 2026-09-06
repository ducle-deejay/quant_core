---
name: task-discipline
description: Use when planning, creating, opening, starting, delegating, updating, reviewing, or accepting repository tasks under tasks/. Enforces the repository-native dependency, ownership, and exclusive-resource workflow.
---

# Task Discipline

The task file and its status directory are durable coordination state. This repository-native tracker is used so work survives chat loss, context reset, agent handover, or unavailable external coordination services; Linear, Symphony, and agent memory are not required to resume it.

## Before implementation

Read-only inspection and planning do not require assignment. Before editing, read `tasks/HOME.md`, then inspect the task and its dependencies. Do not edit implementation files until the task is in `ready` and `start` succeeds. For an `in_progress` task resumed after handover or context reset, use `verify-assignment` with the recorded actor.

A main agent must start or resume the task before delegating it. Give every delegated agent the task id and actor; that agent must run `verify-assignment` before editing. A failed start or verification means stop rather than bypassing the tracker.

## Planning and execution

- Create planned work in `backlog`; do not open it automatically.
- Give every opened task at least one governing requirement reference, a bounded outcome, explicit non-goals, dependencies, exclusive resources, observable behavior, and completion evidence.
- Only the Human Owner opens, requests rework, accepts, or cancels tasks.
- The configured owner actor records authority for coordination; it is not identity authentication.
- Only `accepted` satisfies a dependency.
- Do not start tasks concurrently when their `exclusive_resources` overlap.
- Edit task content only for the task assigned to you. Use `scripts/task_tracker.py` for status transitions so assignment and resource checks remain atomic.

## Completion

Record concrete evidence in the task, check only criteria actually demonstrated, and submit it for Human Owner review. An agent submission is not completion; dependent tasks remain closed until owner acceptance.

Run `python3 scripts/task_tracker.py check` before handing off or committing. Run `python3 scripts/task_tracker.py graph` when planning execution order or parallel work.
