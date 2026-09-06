#!/usr/bin/env python3
"""Repository-native task tracker for OBS-022.

Task Markdown files are DAG nodes. Their parent status directory is the sole
status source. This tool validates the graph, derives execution waves, and
performs guarded atomic transitions so blocked or colliding tasks cannot be
started.
"""

from __future__ import annotations

import argparse
import contextlib
import fcntl
import json
import os
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator, Sequence

ROOT = Path(__file__).resolve().parent.parent
CONFIG_NAME = "tracker.config.json"
VERSION = "1.0.0"
FRONT_MATTER = re.compile(r"\A---\s*\n(.*?)\n---\s*\n", re.DOTALL)
HEADING = re.compile(r"^##\s+(.+?)\s*$", re.MULTILINE)
CHECKBOX = re.compile(r"^\s*[-*]\s+\[([ xX])\]\s+.+$", re.MULTILINE)
TASK_ID = re.compile(r"^[A-Z][A-Z0-9]*-\d{3,}$")
SAFE_SCALAR = re.compile(r"^[A-Za-z0-9._/@+-]+$")
PLACEHOLDERS = {"todo", "tbd", "pending"}


class TrackerError(RuntimeError):
    """Expected tracker or transition failure."""


@dataclass(frozen=True)
class Task:
    task_id: str | None
    path: Path
    status: str
    fields: dict[str, str]
    text: str
    sections: dict[str, str]

    @property
    def title(self) -> str:
        return scalar(self.fields.get("title", ""))

    @property
    def priority(self) -> str:
        return scalar(self.fields.get("priority", ""))

    @property
    def assignee(self) -> str:
        return scalar(self.fields.get("assignee", ""))

    @property
    def depends_on(self) -> list[str]:
        return split_list(self.fields.get("depends_on", ""))

    @property
    def resources(self) -> list[str]:
        return split_list(self.fields.get("exclusive_resources", ""))

    @property
    def requirement_refs(self) -> list[str]:
        return split_list(self.fields.get("requirement_refs", ""))

    @property
    def attempt(self) -> int | None:
        raw = scalar(self.fields.get("attempt", ""))
        try:
            return int(raw)
        except ValueError:
            return None


@dataclass
class Snapshot:
    tasks: list[Task]
    by_id: dict[str, Task]
    errors: list[str]


def scalar(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
        return value[1:-1]
    return value


def split_list(value: str) -> list[str]:
    value = value.strip().strip("[]")
    if not value:
        return []
    return [scalar(part.strip()) for part in value.split(",") if part.strip()]


def format_scalar(value: str) -> str:
    return value if SAFE_SCALAR.fullmatch(value) else json.dumps(value, ensure_ascii=False)


def parse_front_matter(text: str) -> dict[str, str]:
    match = FRONT_MATTER.match(text)
    if not match:
        return {}
    fields: dict[str, str] = {}
    for line in match.group(1).splitlines():
        if ":" not in line or line.strip().startswith("#"):
            continue
        key, _, value = line.partition(":")
        fields[key.strip()] = value.strip()
    return fields


def parse_sections(text: str) -> dict[str, str]:
    matches = list(HEADING.finditer(text))
    sections: dict[str, str] = {}
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        sections[match.group(1).strip()] = text[match.end() : end].strip()
    return sections


def update_front_matter(text: str, updates: dict[str, str]) -> str:
    match = FRONT_MATTER.match(text)
    if not match:
        raise TrackerError("task has no front matter")
    lines = match.group(1).splitlines()
    positions: dict[str, int] = {}
    for index, line in enumerate(lines):
        if ":" in line and not line.strip().startswith("#"):
            positions[line.partition(":")[0].strip()] = index
    for key, value in updates.items():
        rendered = f"{key}: {value}" if value else f"{key}:"
        if key in positions:
            lines[positions[key]] = rendered
        else:
            positions[key] = len(lines)
            lines.append(rendered)
    replacement = "---\n" + "\n".join(lines) + "\n---\n"
    return replacement + text[match.end() :]


def append_work_log(text: str, entry: str) -> str:
    matches = list(HEADING.finditer(text))
    for index, match in enumerate(matches):
        if match.group(1).strip().lower() != "work log":
            continue
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        existing = text[match.end() : end].strip()
        content = f"{existing}\n\n- {entry}" if existing else f"- {entry}"
        suffix = text[end:]
        return text[: match.end()] + "\n\n" + content + "\n\n" + suffix.lstrip("\n")
    raise TrackerError("task has no 'Work log' section")


def meaningful(content: str) -> bool:
    for line in content.splitlines():
        stripped = line.strip().lstrip("-* ").strip()
        if stripped and stripped.lower() not in PLACEHOLDERS:
            return True
    return False


def checklist(content: str) -> list[bool]:
    return [match.group(1).lower() == "x" for match in CHECKBOX.finditer(content)]


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def slugify(title: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    return slug[:72].rstrip("-") or "task"


class TaskTracker:
    REQUIRED_FIELDS = {
        "task_id",
        "title",
        "priority",
        "assignee",
        "depends_on",
        "exclusive_resources",
        "requirement_refs",
        "attempt",
    }

    def __init__(self, root: Path = ROOT):
        self.root = root.resolve()
        self.config_path = self.root / CONFIG_NAME
        self.config = self._load_config()
        self.task_root = self.root / self.config["task_root"]
        self.statuses: list[str] = self.config["statuses"]
        self.owner: str = self.config["human_owner"]
        self.satisfied_statuses = set(self.config["dependency_satisfied_statuses"])
        self.gated_statuses = set(self.config["dependency_gated_statuses"])
        self.resource_holding_statuses = set(self.config["resource_holding_statuses"])
        self.required_sections: list[str] = self.config["required_sections"]

    def _load_config(self) -> dict:
        try:
            config = json.loads(self.config_path.read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise TrackerError(f"tracker config missing: {self.config_path}") from exc
        except json.JSONDecodeError as exc:
            raise TrackerError(f"tracker config is invalid JSON: {exc}") from exc
        required = {
            "task_root",
            "task_prefix",
            "id_digits",
            "human_owner",
            "statuses",
            "priorities",
            "dependency_satisfied_statuses",
            "dependency_gated_statuses",
            "resource_holding_statuses",
            "required_sections",
        }
        missing = sorted(required - config.keys())
        if missing:
            raise TrackerError(f"tracker config missing keys: {', '.join(missing)}")
        if len(set(config["statuses"])) != len(config["statuses"]):
            raise TrackerError("tracker config contains duplicate statuses")
        return config

    @contextlib.contextmanager
    def lock(self) -> Iterator[None]:
        with self.config_path.open("r", encoding="utf-8") as handle:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    def snapshot(self) -> Snapshot:
        tasks: list[Task] = []
        errors: list[str] = []
        for status in self.statuses:
            status_dir = self.task_root / status
            if not status_dir.is_dir():
                errors.append(f"missing status directory: {status_dir.relative_to(self.root)}")
                continue
            for path in sorted(status_dir.glob("*.md")):
                text = path.read_text(encoding="utf-8")
                fields = parse_front_matter(text)
                tasks.append(
                    Task(
                        task_id=scalar(fields.get("task_id", "")) or None,
                        path=path,
                        status=status,
                        fields=fields,
                        text=text,
                        sections=parse_sections(text),
                    )
                )

        by_id: dict[str, Task] = {}
        duplicate_ids: set[str] = set()
        for task in tasks:
            if task.task_id is None:
                continue
            if task.task_id in by_id:
                duplicate_ids.add(task.task_id)
            else:
                by_id[task.task_id] = task
        for task_id in sorted(duplicate_ids):
            errors.append(f"duplicate task_id: {task_id}")

        document_ids = self._collect_document_ids()
        for task in tasks:
            errors.extend(self._validate_task(task, by_id, document_ids))
        errors.extend(self._cycle_errors(by_id))
        errors.extend(self._resource_collision_errors(tasks))
        return Snapshot(tasks=tasks, by_id=by_id, errors=sorted(set(errors)))

    def _collect_document_ids(self) -> set[str]:
        ids: set[str] = set()
        for relative in ("docs/enhanced", "docs/ledger"):
            directory = self.root / relative
            if not directory.is_dir():
                continue
            for path in directory.rglob("*.md"):
                fields = parse_front_matter(path.read_text(encoding="utf-8"))
                doc_id = scalar(fields.get("doc_id", ""))
                if doc_id:
                    ids.add(doc_id)
        return ids

    def _validate_task(
        self, task: Task, by_id: dict[str, Task], document_ids: set[str]
    ) -> list[str]:
        label = task.task_id or task.path.name
        errors: list[str] = []
        if not task.fields:
            return [f"{label}: missing front matter"]
        missing_fields = sorted(self.REQUIRED_FIELDS - task.fields.keys())
        if missing_fields:
            errors.append(f"{label}: missing fields {', '.join(missing_fields)}")
        if "status" in task.fields:
            errors.append(f"{label}: status belongs to the directory, not front matter")
        if task.task_id is None:
            errors.append(f"{task.path.name}: missing task_id")
        else:
            prefix = self.config["task_prefix"]
            digits = self.config["id_digits"]
            expected = re.compile(rf"^{re.escape(prefix)}-\d{{{digits},}}$")
            if not TASK_ID.fullmatch(task.task_id) or not expected.fullmatch(task.task_id):
                errors.append(f"{label}: invalid task_id")
            if not task.path.name.startswith(f"{task.task_id}-"):
                errors.append(f"{label}: file name must start with '{task.task_id}-'")
        if not task.title:
            errors.append(f"{label}: title is empty")
        if task.priority not in self.config["priorities"]:
            errors.append(f"{label}: priority '{task.priority}' is invalid")
        if not task.assignee:
            errors.append(f"{label}: assignee is empty")
        if task.attempt is None or task.attempt < 0:
            errors.append(f"{label}: attempt must be a non-negative integer")

        for field_name, values in (
            ("depends_on", task.depends_on),
            ("exclusive_resources", task.resources),
            ("requirement_refs", task.requirement_refs),
        ):
            duplicates = sorted({item for item in values if values.count(item) > 1})
            if duplicates:
                errors.append(f"{label}: duplicate {field_name} values {', '.join(duplicates)}")

        if task.task_id and task.task_id in task.depends_on:
            errors.append(f"{label}: task cannot depend on itself")
        for dependency in task.depends_on:
            if dependency not in by_id:
                errors.append(f"{label}: dependency '{dependency}' does not exist")
        for ref in task.requirement_refs:
            if ref not in document_ids:
                errors.append(f"{label}: requirement ref '{ref}' does not exist")

        for section in self.required_sections:
            if section not in task.sections:
                errors.append(f"{label}: missing section '{section}'")

        if task.status in self.gated_statuses:
            errors.extend(self._open_content_errors(task))
            for dependency in task.depends_on:
                dependency_task = by_id.get(dependency)
                if dependency_task and dependency_task.status not in self.satisfied_statuses:
                    errors.append(
                        f"{label}: status '{task.status}' requires dependency "
                        f"'{dependency}' to be accepted"
                    )
            if scalar(task.fields.get("opened_by", "")) != self.owner:
                errors.append(f"{label}: opened_by must be '{self.owner}'")

        claimed_statuses = self.resource_holding_statuses | {"in_progress", "human_review"}
        if task.status in claimed_statuses:
            if task.assignee == "unassigned":
                errors.append(f"{label}: status '{task.status}' requires an assignee")
            if task.attempt is None or task.attempt < 1:
                errors.append(f"{label}: status '{task.status}' requires attempt >= 1")
            if not scalar(task.fields.get("started_at", "")):
                errors.append(f"{label}: status '{task.status}' requires started_at")

        if task.status == "blocked" and not scalar(task.fields.get("blocked_reason", "")):
            errors.append(f"{label}: blocked task requires blocked_reason")
        if task.status == "rework" and not scalar(task.fields.get("rework_reason", "")):
            errors.append(f"{label}: rework task requires rework_reason")
        if task.status in {"human_review", "accepted"}:
            errors.extend(self._completion_errors(task))
        if task.status == "accepted" and scalar(task.fields.get("accepted_by", "")) != self.owner:
            errors.append(f"{label}: accepted_by must be '{self.owner}'")
        return errors

    def _open_content_errors(self, task: Task) -> list[str]:
        errors: list[str] = []
        label = task.task_id or task.path.name
        if not task.requirement_refs:
            errors.append(f"{label}: requirement_refs must name at least one governing document")
        for section in ("Outcome", "Scope", "Non-goals", "Inputs", "Outputs", "Behavior"):
            if not meaningful(task.sections.get(section, "")):
                errors.append(f"{label}: section '{section}' is not ready")
        for section in ("Acceptance criteria", "Validation"):
            if not checklist(task.sections.get(section, "")):
                errors.append(f"{label}: section '{section}' needs at least one checkbox")
        return errors

    def _completion_errors(self, task: Task) -> list[str]:
        errors: list[str] = []
        label = task.task_id or task.path.name
        for section in ("Acceptance criteria", "Validation"):
            checks = checklist(task.sections.get(section, ""))
            if not checks or not all(checks):
                errors.append(f"{label}: section '{section}' is incomplete")
        if not meaningful(task.sections.get("Evidence", "")):
            errors.append(f"{label}: Evidence is empty")
        return errors

    def _cycle_errors(self, by_id: dict[str, Task]) -> list[str]:
        state: dict[str, int] = {}
        stack: list[str] = []
        cycles: set[str] = set()

        def visit(task_id: str) -> None:
            state[task_id] = 1
            stack.append(task_id)
            for dependency in by_id[task_id].depends_on:
                if dependency not in by_id:
                    continue
                if state.get(dependency, 0) == 0:
                    visit(dependency)
                elif state.get(dependency) == 1:
                    start = stack.index(dependency)
                    cycle = stack[start:] + [dependency]
                    cycles.add(" -> ".join(cycle))
            stack.pop()
            state[task_id] = 2

        for task_id in sorted(by_id):
            if state.get(task_id, 0) == 0:
                visit(task_id)
        return [f"dependency cycle: {cycle}" for cycle in sorted(cycles)]

    def _resource_collision_errors(self, tasks: Sequence[Task]) -> list[str]:
        holders: dict[str, list[str]] = {}
        for task in tasks:
            if task.status not in self.resource_holding_statuses or task.task_id is None:
                continue
            for resource in task.resources:
                holders.setdefault(resource, []).append(task.task_id)
        return [
            f"exclusive resource '{resource}' held by {', '.join(sorted(task_ids))}"
            for resource, task_ids in sorted(holders.items())
            if len(task_ids) > 1
        ]

    def require_valid(self) -> Snapshot:
        snapshot = self.snapshot()
        if snapshot.errors:
            raise TrackerError("tracker integrity errors:\n  - " + "\n  - ".join(snapshot.errors))
        return snapshot

    def dependency_satisfied(self, task: Task, snapshot: Snapshot) -> bool:
        return all(
            dependency in snapshot.by_id
            and snapshot.by_id[dependency].status in self.satisfied_statuses
            for dependency in task.depends_on
        )

    def resource_blockers(self, task: Task, snapshot: Snapshot) -> list[tuple[str, str]]:
        blockers: list[tuple[str, str]] = []
        wanted = set(task.resources)
        if not wanted:
            return blockers
        for other in snapshot.tasks:
            if (
                other.task_id is None
                or other.task_id == task.task_id
                or other.status not in self.resource_holding_statuses
            ):
                continue
            for resource in sorted(wanted & set(other.resources)):
                blockers.append((resource, other.task_id))
        return blockers

    def task(self, task_id: str, snapshot: Snapshot) -> Task:
        try:
            return snapshot.by_id[task_id]
        except KeyError as exc:
            raise TrackerError(f"unknown task: {task_id}") from exc

    def ready_to_open(self, snapshot: Snapshot) -> list[Task]:
        return [
            task
            for task in snapshot.tasks
            if task.status == "backlog"
            and self.dependency_satisfied(task, snapshot)
            and not self._open_content_errors(task)
        ]

    def ready_to_start(self, snapshot: Snapshot) -> list[Task]:
        return [
            task
            for task in snapshot.tasks
            if task.status in {"ready", "rework"}
            and self.dependency_satisfied(task, snapshot)
            and not self.resource_blockers(task, snapshot)
        ]

    def waves(self, snapshot: Snapshot) -> list[list[Task]]:
        remaining = set(snapshot.by_id)
        done: set[str] = set()
        waves: list[list[Task]] = []
        while remaining:
            current_ids = sorted(
                task_id
                for task_id in remaining
                if set(snapshot.by_id[task_id].depends_on) <= done
            )
            if not current_ids:
                raise TrackerError("cannot derive waves because the dependency graph has a cycle")
            wave = [snapshot.by_id[task_id] for task_id in current_ids]
            waves.append(sorted(wave, key=self.sort_key))
            done.update(current_ids)
            remaining.difference_update(current_ids)
        return waves

    def parallel_batches(self, wave: Sequence[Task]) -> list[list[Task]]:
        batches: list[list[Task]] = []
        used_by_batch: list[set[str]] = []
        for task in wave:
            resources = set(task.resources)
            for index, used in enumerate(used_by_batch):
                if resources.isdisjoint(used):
                    batches[index].append(task)
                    used.update(resources)
                    break
            else:
                batches.append([task])
                used_by_batch.append(set(resources))
        return batches

    def sort_key(self, task: Task) -> tuple[int, str]:
        priorities = self.config["priorities"]
        rank = priorities.index(task.priority) if task.priority in priorities else len(priorities)
        return rank, task.task_id or task.path.name

    def new_task(
        self,
        title: str,
        priority: str,
        dependencies: Sequence[str],
        resources: Sequence[str],
        refs: Sequence[str],
    ) -> Task:
        if not title.strip():
            raise TrackerError("title cannot be blank")
        if priority not in self.config["priorities"]:
            raise TrackerError(f"invalid priority: {priority}")
        with self.lock():
            snapshot = self.require_valid()
            unknown = sorted(set(dependencies) - snapshot.by_id.keys())
            if unknown:
                raise TrackerError(f"unknown dependencies: {', '.join(unknown)}")
            document_ids = self._collect_document_ids()
            unknown_refs = sorted(set(refs) - document_ids)
            if unknown_refs:
                raise TrackerError(f"unknown requirement refs: {', '.join(unknown_refs)}")
            numbers = [
                int(task_id.rsplit("-", 1)[1])
                for task_id in snapshot.by_id
                if TASK_ID.fullmatch(task_id)
            ]
            number = max(numbers, default=0) + 1
            task_id = f"{self.config['task_prefix']}-{number:0{self.config['id_digits']}d}"
            filename = f"{task_id}-{slugify(title)}.md"
            path = self.task_root / "backlog" / filename
            content = render_new_task(
                task_id,
                title.strip(),
                priority,
                dependencies,
                resources,
                refs,
            )
            path.write_text(content, encoding="utf-8")
            return self.task(task_id, self.require_valid())

    def open_task(self, task_id: str, actor: str) -> Task:
        self._require_owner(actor)
        with self.lock():
            snapshot = self.require_valid()
            task = self.task(task_id, snapshot)
            if task.status != "backlog":
                raise TrackerError(f"{task_id} is '{task.status}', expected 'backlog'")
            if not self.dependency_satisfied(task, snapshot):
                waiting = [
                    dep
                    for dep in task.depends_on
                    if snapshot.by_id.get(dep) is None
                    or snapshot.by_id[dep].status not in self.satisfied_statuses
                ]
                raise TrackerError(f"{task_id} waits for: {', '.join(waiting)}")
            content_errors = self._open_content_errors(task)
            if content_errors:
                raise TrackerError("task is not ready to open:\n  - " + "\n  - ".join(content_errors))
            now = utc_now()
            return self._move(
                task,
                "ready",
                {"opened_by": format_scalar(actor), "opened_at": now},
                f"{now} opened by {actor}",
            )

    def start(self, task_id: str, actor: str) -> Task:
        if not actor.strip() or actor == "unassigned":
            raise TrackerError("start actor must be a concrete nonblank name")
        with self.lock():
            snapshot = self.require_valid()
            task = self.task(task_id, snapshot)
            if task.status not in {"ready", "rework"}:
                raise TrackerError(f"{task_id} is '{task.status}', expected 'ready' or 'rework'")
            if not self.dependency_satisfied(task, snapshot):
                raise TrackerError(f"{task_id} has unsatisfied dependencies")
            blockers = self.resource_blockers(task, snapshot)
            if blockers:
                detail = ", ".join(f"{resource} held by {holder}" for resource, holder in blockers)
                raise TrackerError(f"{task_id} has resource collisions: {detail}")
            attempt = (task.attempt or 0) + 1
            now = utc_now()
            return self._move(
                task,
                "in_progress",
                {
                    "assignee": format_scalar(actor),
                    "attempt": str(attempt),
                    "started_at": now,
                    "blocked_reason": "",
                },
                f"{now} started by {actor} for attempt {attempt}",
            )

    def verify_assignment(self, task_id: str, actor: str) -> Task:
        snapshot = self.require_valid()
        task = self.task(task_id, snapshot)
        if task.status != "in_progress":
            raise TrackerError(f"{task_id} is '{task.status}', not 'in_progress'")
        if task.assignee != actor:
            raise TrackerError(f"{task_id} is assigned to '{task.assignee}', not '{actor}'")
        return task

    def submit(self, task_id: str, actor: str) -> Task:
        with self.lock():
            snapshot = self.require_valid()
            task = self.task(task_id, snapshot)
            self._require_assignee(task, actor)
            if task.status != "in_progress":
                raise TrackerError(f"{task_id} is '{task.status}', expected 'in_progress'")
            completion_errors = self._completion_errors(task)
            if completion_errors:
                raise TrackerError("task cannot be submitted:\n  - " + "\n  - ".join(completion_errors))
            now = utc_now()
            return self._move(
                task,
                "human_review",
                {"submitted_at": now},
                f"{now} submitted for Human Owner review by {actor}",
            )

    def accept(self, task_id: str, actor: str) -> Task:
        self._require_owner(actor)
        with self.lock():
            snapshot = self.require_valid()
            task = self.task(task_id, snapshot)
            if task.status != "human_review":
                raise TrackerError(f"{task_id} is '{task.status}', expected 'human_review'")
            completion_errors = self._completion_errors(task)
            if completion_errors:
                raise TrackerError("task cannot be accepted:\n  - " + "\n  - ".join(completion_errors))
            now = utc_now()
            return self._move(
                task,
                "accepted",
                {"accepted_by": format_scalar(actor), "accepted_at": now},
                f"{now} accepted by Human Owner {actor}",
            )

    def request_rework(self, task_id: str, actor: str, reason: str) -> Task:
        self._require_owner(actor)
        if not reason.strip():
            raise TrackerError("rework reason cannot be blank")
        with self.lock():
            snapshot = self.require_valid()
            task = self.task(task_id, snapshot)
            if task.status != "human_review":
                raise TrackerError(f"{task_id} is '{task.status}', expected 'human_review'")
            now = utc_now()
            return self._move(
                task,
                "rework",
                {"rework_reason": format_scalar(reason.strip())},
                f"{now} rework requested by {actor}: {reason.strip()}",
            )

    def block(self, task_id: str, actor: str, reason: str) -> Task:
        if not reason.strip():
            raise TrackerError("blocked reason cannot be blank")
        with self.lock():
            snapshot = self.require_valid()
            task = self.task(task_id, snapshot)
            self._require_assignee(task, actor)
            if task.status != "in_progress":
                raise TrackerError(f"{task_id} is '{task.status}', expected 'in_progress'")
            now = utc_now()
            return self._move(
                task,
                "blocked",
                {"blocked_reason": format_scalar(reason.strip())},
                f"{now} blocked by {actor}: {reason.strip()}",
            )

    def resume(self, task_id: str, actor: str) -> Task:
        with self.lock():
            snapshot = self.require_valid()
            task = self.task(task_id, snapshot)
            self._require_assignee(task, actor)
            if task.status != "blocked":
                raise TrackerError(f"{task_id} is '{task.status}', expected 'blocked'")
            now = utc_now()
            return self._move(
                task,
                "in_progress",
                {"blocked_reason": ""},
                f"{now} resumed by {actor}",
            )

    def cancel(self, task_id: str, actor: str, reason: str) -> Task:
        self._require_owner(actor)
        if not reason.strip():
            raise TrackerError("cancellation reason cannot be blank")
        with self.lock():
            snapshot = self.require_valid()
            task = self.task(task_id, snapshot)
            if task.status in {"accepted", "cancelled"}:
                raise TrackerError(f"{task_id} is terminal in '{task.status}'")
            now = utc_now()
            return self._move(
                task,
                "cancelled",
                {
                    "cancelled_by": format_scalar(actor),
                    "cancelled_at": now,
                    "cancellation_reason": format_scalar(reason.strip()),
                },
                f"{now} cancelled by {actor}: {reason.strip()}",
            )

    def _require_owner(self, actor: str) -> None:
        if actor != self.owner:
            raise TrackerError(f"owner transition requires --by {self.owner}")

    @staticmethod
    def _require_assignee(task: Task, actor: str) -> None:
        if task.assignee != actor:
            raise TrackerError(f"{task.task_id} is assigned to '{task.assignee}', not '{actor}'")

    def _move(
        self,
        task: Task,
        destination_status: str,
        updates: dict[str, str],
        log_entry: str,
    ) -> Task:
        destination = self.task_root / destination_status / task.path.name
        if destination.exists() and destination != task.path:
            raise TrackerError(f"destination already exists: {destination}")
        text = update_front_matter(task.text, updates)
        text = append_work_log(text, log_entry)
        temporary = task.path.with_name(f".{task.path.name}.tmp-{os.getpid()}")
        temporary.write_text(text, encoding="utf-8")
        os.replace(temporary, task.path)
        if destination != task.path:
            os.replace(task.path, destination)
        return Task(
            task_id=task.task_id,
            path=destination,
            status=destination_status,
            fields=parse_front_matter(text),
            text=text,
            sections=parse_sections(text),
        )


def render_list(values: Sequence[str]) -> str:
    return "[" + ", ".join(format_scalar(value) for value in values) + "]"


def render_new_task(
    task_id: str,
    title: str,
    priority: str,
    dependencies: Sequence[str],
    resources: Sequence[str],
    refs: Sequence[str],
) -> str:
    return f"""---
task_id: {task_id}
title: {json.dumps(title, ensure_ascii=False)}
priority: {priority}
assignee: unassigned
depends_on: {render_list(dependencies)}
exclusive_resources: {render_list(resources)}
requirement_refs: {render_list(refs)}
attempt: 0
---

# {task_id} - {title}

## Outcome

TODO

## Scope

TODO

## Non-goals

TODO

## Inputs

TODO

## Outputs

TODO

## Behavior

TODO

## Acceptance criteria

- [ ] TODO

## Validation

- [ ] TODO

## Evidence


## Work log


"""


def print_task(task: Task) -> None:
    resources = ",".join(task.resources) or "-"
    dependencies = ",".join(task.depends_on) or "-"
    print(
        f"{task.task_id:<10} {task.priority:<3} {task.status:<14} "
        f"deps={dependencies:<18} resources={resources:<22} {task.title}"
    )


def command_check(tracker: TaskTracker) -> int:
    snapshot = tracker.snapshot()
    print("=== TASK TRACKER CHECK ===")
    print(f"tasks scanned      : {len(snapshot.tasks)}")
    for status in tracker.statuses:
        count = sum(task.status == status for task in snapshot.tasks)
        print(f"{status:<19}: {count}")
    if snapshot.errors:
        for error in snapshot.errors:
            print(f"BROKEN: {error}")
        print("\nTASK TRACKER FAILED")
        return 1
    print(f"\nready to open      : {len(tracker.ready_to_open(snapshot))}")
    print(f"ready to start     : {len(tracker.ready_to_start(snapshot))}")
    print("\nTASK TRACKER OK")
    return 0


def command_board(tracker: TaskTracker) -> int:
    snapshot = tracker.require_valid()
    for status in tracker.statuses:
        print(f"\n## {status} ({sum(task.status == status for task in snapshot.tasks)})")
        selected = sorted(
            (task for task in snapshot.tasks if task.status == status),
            key=tracker.sort_key,
        )
        if not selected:
            print("(empty)")
        for task in selected:
            print_task(task)
    return 0


def command_graph(tracker: TaskTracker) -> int:
    snapshot = tracker.require_valid()
    for wave_number, wave in enumerate(tracker.waves(snapshot), start=1):
        print(f"Wave {wave_number}")
        for batch_number, batch in enumerate(tracker.parallel_batches(wave), start=1):
            members = ", ".join(f"{task.task_id}[{task.status}]" for task in batch)
            print(f"  parallel batch {batch_number}: {members}")
    return 0


def command_selection(tracker: TaskTracker, selection: str) -> int:
    snapshot = tracker.require_valid()
    if selection == "ready-to-open":
        tasks = tracker.ready_to_open(snapshot)
        empty_message = "No tasks ready to open."
    else:
        tasks = tracker.ready_to_start(snapshot)
        empty_message = "No tasks ready to start."
    for task in sorted(tasks, key=tracker.sort_key):
        print_task(task)
    if not tasks:
        print(empty_message)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", action="version", version=f"%(prog)s {VERSION}")
    subparsers = parser.add_subparsers(dest="command", required=True)
    for name in ("check", "board", "graph", "ready-to-open", "ready-to-start"):
        subparsers.add_parser(name)

    new = subparsers.add_parser("new", help="create a draft task in backlog")
    new.add_argument("--title", required=True)
    new.add_argument("--priority", default="P2")
    new.add_argument("--depends-on", nargs="*", default=[])
    new.add_argument("--resources", nargs="*", default=[])
    new.add_argument("--refs", nargs="*", default=[])

    open_task = subparsers.add_parser("open", help="let the Human Owner open a backlog task")
    open_task.add_argument("task_id")
    open_task.add_argument("--by", required=True)

    start = subparsers.add_parser("start", help="assign and start a ready or rework task")
    start.add_argument("task_id")
    start.add_argument("--actor", required=True)

    verify = subparsers.add_parser("verify-assignment", help="verify task ownership before edits")
    verify.add_argument("task_id")
    verify.add_argument("--actor", required=True)

    submit = subparsers.add_parser("submit", help="submit completed work for Human Owner review")
    submit.add_argument("task_id")
    submit.add_argument("--actor", required=True)

    accept = subparsers.add_parser("accept", help="accept reviewed work")
    accept.add_argument("task_id")
    accept.add_argument("--by", required=True)

    rework = subparsers.add_parser("rework", help="return reviewed work for another attempt")
    rework.add_argument("task_id")
    rework.add_argument("--by", required=True)
    rework.add_argument("--reason", required=True)

    block = subparsers.add_parser("block", help="record an external blocker")
    block.add_argument("task_id")
    block.add_argument("--actor", required=True)
    block.add_argument("--reason", required=True)

    resume = subparsers.add_parser("resume", help="resume a blocked task")
    resume.add_argument("task_id")
    resume.add_argument("--actor", required=True)

    cancel = subparsers.add_parser("cancel", help="cancel a non-terminal task")
    cancel.add_argument("task_id")
    cancel.add_argument("--by", required=True)
    cancel.add_argument("--reason", required=True)
    return parser


def main(argv: Sequence[str] | None = None, root: Path = ROOT) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        tracker = TaskTracker(root)
        if args.command == "check":
            return command_check(tracker)
        if args.command == "board":
            return command_board(tracker)
        if args.command == "graph":
            return command_graph(tracker)
        if args.command in {"ready-to-open", "ready-to-start"}:
            return command_selection(tracker, args.command)
        if args.command == "new":
            task = tracker.new_task(
                args.title,
                args.priority,
                args.depends_on,
                args.resources,
                args.refs,
            )
        elif args.command == "open":
            task = tracker.open_task(args.task_id, args.by)
        elif args.command == "start":
            task = tracker.start(args.task_id, args.actor)
        elif args.command == "verify-assignment":
            task = tracker.verify_assignment(args.task_id, args.actor)
        elif args.command == "submit":
            task = tracker.submit(args.task_id, args.actor)
        elif args.command == "accept":
            task = tracker.accept(args.task_id, args.by)
        elif args.command == "rework":
            task = tracker.request_rework(args.task_id, args.by, args.reason)
        elif args.command == "block":
            task = tracker.block(args.task_id, args.actor, args.reason)
        elif args.command == "resume":
            task = tracker.resume(args.task_id, args.actor)
        elif args.command == "cancel":
            task = tracker.cancel(args.task_id, args.by, args.reason)
        else:  # pragma: no cover - argparse owns command choices
            parser.error(f"unsupported command: {args.command}")
        print(f"{task.task_id}: {task.status} ({task.path.relative_to(tracker.root)})")
        return 0
    except (OSError, TrackerError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
