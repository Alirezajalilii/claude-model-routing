"""Parse and validate the Contract blocks of a plan file (see the Plan Contract)."""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Dict, List, Optional, Tuple

KINDS = ("symbol", "file", "config", "env", "flag", "endpoint", "id")
HEADING_RE = re.compile(r"^### Task ([A-Za-z0-9][A-Za-z0-9._-]*):(.*)$")
BODY_END_RE = re.compile(r"^#{1,3} ")
SEP_RE = re.compile(r"\s+(?:--|—)\s+")
ITEM_RE = re.compile(r"^\s*- ([a-z]+):(.*)$")
FENCE_MARKS = ("```", "~~~")
CONTRACT_FORMS = ("Contract:", "Contract: none", "Contract:none")
NO_TASKS = "no tasks found: task headings must read '### Task <id>: <title>'"
NO_CONTRACT = "no task has a Contract line"
MALFORMED_PROVIDES = "malformed provides (use '<kind> <name> in <path> -- <shape>')"
MALFORMED_REQUIRES = "malformed requires (use '<task-id> <name> -- <shape>')"
MALFORMED_AFTER = "malformed after (use '<task-id>, <task-id>')"


@dataclass(frozen=True)
class Provide:
    task: str
    kind: str
    name: str
    path: str
    shape: str
    line: int


@dataclass(frozen=True)
class Require:
    task: str
    provider: str
    name: str
    shape: str
    line: int


@dataclass(frozen=True)
class Task:
    task_id: str
    title: str
    line: int
    contract_lines: Tuple[int, ...]
    provides: Tuple[Provide, ...]
    requires: Tuple[Require, ...]
    after: Tuple[Tuple[str, int], ...]


@dataclass(frozen=True)
class PlanContract:
    tasks: Tuple[Task, ...]
    errors: Tuple[Tuple[int, str], ...]


def fence_mask(lines: List[str]) -> List[bool]:
    mask = []  # type: List[bool]
    fenced = False
    for line in lines:
        if line.strip().startswith(FENCE_MARKS):
            fenced = not fenced
            mask.append(True)
        else:
            mask.append(fenced)
    return mask


def task_spans(lines: List[str], mask: List[bool]) -> List[Tuple[int, int, str, str]]:
    spans = []  # type: List[Tuple[int, int, str, str]]
    current = None  # type: Optional[Tuple[int, str, str]]
    for index, line in enumerate(lines):
        if mask[index]:
            continue
        heading = HEADING_RE.match(line)
        if heading or BODY_END_RE.match(line):
            if current is not None:
                spans.append((current[0], index, current[1], current[2]))
                current = None
        if heading:
            current = (index, heading.group(1), heading.group(2).strip())
    if current is not None:
        spans.append((current[0], len(lines), current[1], current[2]))
    return spans


def _contract_text(line: str) -> str:
    text = " ".join(line.replace("*", "").replace("`", "").split())
    if text.startswith("- "):
        text = text[2:]
    return text


def _is_contract(line: str) -> bool:
    return _contract_text(line) in CONTRACT_FORMS


def _item_match(line: str) -> Optional[Tuple[str, str]]:
    match = ITEM_RE.match(line.replace("`", ""))
    if match is None:
        return None
    return match.group(1), match.group(2)


def _item_run(lines: List[str], mask: List[bool], start: int, end: int) -> List[int]:
    indices = []  # type: List[int]
    for index in range(start, end):
        if mask[index] or _item_match(lines[index]) is None:
            break
        indices.append(index)
    return indices


def _split_shape(rest: str) -> Tuple[str, str]:
    parts = SEP_RE.split(rest.strip(), maxsplit=1)
    shape = parts[1].strip() if len(parts) > 1 else ""
    return parts[0].strip(), shape


def _safe_path(path: str) -> bool:
    if not path or path.startswith(("/", "~")):
        return False
    return ".." not in PurePosixPath(path).parts


def _parse_provide(
    task_id: str, line_no: int, rest: str
) -> Tuple[Optional[Provide], Optional[str]]:
    head, shape = _split_shape(rest)
    tokens = head.split()
    if len(tokens) == 4 and tokens[2] == "in":
        kind, name, path = tokens[0], tokens[1], tokens[3]  # type: Tuple[str, str, Optional[str]]
    elif len(tokens) == 2:
        kind, name, path = tokens[0], tokens[1], None
    else:
        return None, MALFORMED_PROVIDES
    if kind not in KINDS:
        return None, (
            "unknown kind '%s' (use symbol, file, config, env, flag, endpoint or id)" % kind
        )
    if kind == "file":
        if path is not None:
            return None, "a file provide takes no 'in'"
        checked = name
    else:
        if path is None:
            return None, "%s %s needs 'in <path>'" % (kind, name)
        checked = path
    if not _safe_path(checked):
        return None, "path '%s' must be relative and stay inside the repository" % checked
    return Provide(task_id, kind, name, path or "", shape, line_no), None


def _parse_require(
    task_id: str, line_no: int, rest: str
) -> Tuple[Optional[Require], Optional[str]]:
    head, shape = _split_shape(rest)
    tokens = head.split()
    if len(tokens) != 2:
        return None, MALFORMED_REQUIRES
    return Require(task_id, tokens[0], tokens[1], shape, line_no), None


def _parse_after(line_no: int, rest: str) -> Tuple[List[Tuple[str, int]], Optional[str]]:
    ids = [token for token in re.split(r"[,\s]+", rest.strip()) if token]
    if not ids:
        return [], MALFORMED_AFTER
    return [(task_id, line_no) for task_id in ids], None


def _add_provide(
    provides: List[Provide], task_id: str, line_no: int, rest: str
) -> Optional[str]:
    item, problem = _parse_provide(task_id, line_no, rest)
    if item is None:
        return problem
    if any(existing.name == item.name for existing in provides):
        return "provides '%s' twice" % item.name
    provides.append(item)
    return None


def _add_item(
    found: Tuple[List[Provide], List[Require], List[Tuple[str, int]]],
    verb: str,
    task_id: str,
    line_no: int,
    rest: str,
) -> Optional[str]:
    provides, requires, after = found
    if verb == "provides":
        return _add_provide(provides, task_id, line_no, rest)
    if verb == "requires":
        item, problem = _parse_require(task_id, line_no, rest)
        if item is not None:
            requires.append(item)
        return problem
    if verb == "after":
        ids, problem = _parse_after(line_no, rest)
        after.extend(ids)
        return problem
    return "unknown contract item '%s' (use provides, requires or after)" % verb


def _parse_items(
    task_id: str, lines: List[str], indices: List[int], none: bool,
    errors: List[Tuple[int, str]],
) -> Tuple[List[Provide], List[Require], List[Tuple[str, int]]]:
    found = ([], [], [])  # type: Tuple[List[Provide], List[Require], List[Tuple[str, int]]]
    if none:
        if indices:
            errors.append((indices[0] + 1, "task %s: Contract: none has items" % task_id))
        return found
    for index in indices:
        verb, rest = _item_match(lines[index]) or ("", "")
        problem = _add_item(found, verb, task_id, index + 1, rest)
        if problem:
            errors.append((index + 1, "task %s: %s" % (task_id, problem)))
    return found


def _parse_task(
    lines: List[str], mask: List[bool], start: int, end: int,
    task_id: str, title: str, errors: List[Tuple[int, str]],
) -> Task:
    contract_lines = []  # type: List[int]
    block = None  # type: Optional[int]
    for index in range(start + 1, end):
        if mask[index] or not _is_contract(lines[index]):
            continue
        contract_lines.append(index + 1)
        if block is None:
            block = index
        else:
            errors.append((index + 1, "task %s: two Contract lines" % task_id))
    provides, requires, after = [], [], []  # type: List, List, List
    if block is not None:
        none = _contract_text(lines[block]) != "Contract:"
        indices = _item_run(lines, mask, block + 1, end)
        provides, requires, after = _parse_items(task_id, lines, indices, none, errors)
    return Task(
        task_id, title, start + 1, tuple(contract_lines),
        tuple(provides), tuple(requires), tuple(after),
    )


def parse_plan(text: str) -> PlanContract:
    lines = text.splitlines()
    mask = fence_mask(lines)
    errors = []  # type: List[Tuple[int, str]]
    tasks = [
        _parse_task(lines, mask, start, end, task_id, title, errors)
        for start, end, task_id, title in task_spans(lines, mask)
    ]
    return PlanContract(tuple(tasks), tuple(errors))


def find_provide(plan: PlanContract, task_id: str, name: str) -> Optional[Provide]:
    for task in plan.tasks:
        if task.task_id != task_id:
            continue
        for provide in task.provides:
            if provide.name == name:
                return provide
    return None


def _norm_shape(shape: str) -> str:
    return " ".join(shape.split())


def _provide_problem(plan: PlanContract, req: Require) -> Optional[str]:
    provide = find_provide(plan, req.provider, req.name)
    if provide is None:
        return "%s provides no '%s'" % (req.provider, req.name)
    if req.shape and _norm_shape(req.shape) != _norm_shape(provide.shape):
        return "shape differs from %s's provides at line %d" % (req.provider, provide.line)
    return None


def _requires_errors(
    plan: PlanContract, task: Task, ids: set
) -> List[Tuple[int, str]]:
    found = []  # type: List[Tuple[int, str]]
    for req in task.requires:
        if req.provider == task.task_id:
            problem = "requires itself"
        elif req.provider not in ids:
            problem = "requires unknown task %s" % req.provider
        else:
            problem = _provide_problem(plan, req)
        if problem:
            found.append((req.line, "task %s: %s" % (task.task_id, problem)))
    return found


def _after_errors(task: Task, ids: set) -> List[Tuple[int, str]]:
    found = []  # type: List[Tuple[int, str]]
    for target, line_no in task.after:
        if target == task.task_id:
            problem = "after itself"
        elif target not in ids:
            problem = "after unknown task %s" % target
        else:
            continue
        found.append((line_no, "task %s: %s" % (task.task_id, problem)))
    return found


def _task_errors(plan: PlanContract) -> List[Tuple[int, str]]:
    found = []  # type: List[Tuple[int, str]]
    first_line = {}  # type: Dict[str, int]
    for task in plan.tasks:
        if task.task_id in first_line:
            found.append((
                task.line,
                "duplicate task id %s (first at line %d)"
                % (task.task_id, first_line[task.task_id]),
            ))
        else:
            first_line[task.task_id] = task.line
        if not task.contract_lines:
            found.append((task.line, "task %s: no Contract line" % task.task_id))
    return found


def _cross_errors(plan: PlanContract) -> List[Tuple[int, str]]:
    ids = {task.task_id for task in plan.tasks}
    found = _task_errors(plan)
    for task in plan.tasks:
        found.extend(_requires_errors(plan, task, ids))
        found.extend(_after_errors(task, ids))
    return found


def validate(plan: PlanContract) -> List[str]:
    if not plan.tasks:
        return [NO_TASKS]
    if not any(task.contract_lines for task in plan.tasks):
        return [NO_CONTRACT]
    found = list(plan.errors) + _cross_errors(plan)
    found.sort(key=lambda entry: entry[0])
    return ["line %d: %s" % entry for entry in found]
