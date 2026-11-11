"""Parse one task's Gate block, Test Case IDs and executor Skills line from plan text.

Pure functions: no file or process access. Plan grammar helpers come from plan_contract.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Dict, List, Tuple

import plan_contract as pc

GATE_KEYS = ("files", "tests", "red", "guard", "green")
GATE_LINE = "Gate:"
GATE_ITEM_RE = re.compile(r"^\s*- ([a-z]+):\s*(.*)$")
CASE_RE = re.compile(r"^\s*[-*]\s+\**(TC\d+)\b")
SKILLS_PREFIX = "Skills:"
LIST_KEYS = ("files", "tests")


@dataclass(frozen=True)
class GateBlock:
    task_id: str
    line: int                  # 1-based line of the Gate: line
    files: Tuple[str, ...]
    tests: Tuple[str, ...]
    red: Tuple[str, ...]
    guard: Tuple[str, ...]
    green: Tuple[str, ...]
    case_ids: Tuple[str, ...]  # TC IDs in plan order
    skills: Tuple[str, ...]    # executor Skills line paths; () for none or no line


class GateError(Exception):
    """A task's Gate block, Test Case IDs or Skills line is missing or malformed."""


def _plain(line: str) -> str:
    text = " ".join(line.replace("*", "").replace("`", "").split())
    return text[2:] if text.startswith("- ") else text


def _unquote(text: str) -> str:
    text = text.strip()
    if len(text) > 1 and text[0] == "`" and text[-1] == "`":
        text = text[1:-1]
    return text.strip()


def _split_values(value: str) -> Tuple[str, ...]:
    items = (_unquote(part) for part in value.split(","))
    return tuple(item for item in items if item)


def _task_span(lines: List[str], mask: List[bool], task_id: str) -> Tuple[int, int]:
    for start, end, found, _title in pc.task_spans(lines, mask):
        if found == task_id:
            return start, end
    raise GateError("no task %s in the plan" % task_id)


def _gate_items(
    lines: List[str], mask: List[bool], gate_index: int, end: int
) -> List[Tuple[str, str]]:
    items = []  # type: List[Tuple[str, str]]
    for index in range(gate_index + 1, end):
        match = None if mask[index] else GATE_ITEM_RE.match(lines[index])
        if match is None:
            break
        items.append((match.group(1), match.group(2)))
    return items


def _gate_values(task_id: str, items: List[Tuple[str, str]]) -> Dict[str, Tuple[str, ...]]:
    collected = {key: [] for key in GATE_KEYS}  # type: Dict[str, List[str]]
    for key, value in items:
        if key not in collected:
            raise GateError(
                "task %s: unknown gate item '%s' (use files, tests, red, guard or green)"
                % (task_id, key)
            )
        values = _split_values(value) if key in LIST_KEYS else (_unquote(value),)
        values = tuple(item for item in values if item)
        if not values:
            raise GateError("task %s: empty %s line" % (task_id, key))
        collected[key].extend(values)
    return {key: tuple(found) for key, found in collected.items()}


def _check_gate(task_id: str, values: Dict[str, Tuple[str, ...]]) -> None:
    if not values["files"]:
        raise GateError("task %s: Gate block has no files line" % task_id)
    if not values["green"]:
        raise GateError("task %s: Gate block has no green line" % task_id)
    if (values["red"] or values["guard"]) and not values["tests"]:
        raise GateError("task %s: red or guard lines need a tests line" % task_id)


def _case_ids(
    task_id: str, lines: List[str], mask: List[bool], start: int, end: int
) -> Tuple[str, ...]:
    found = []  # type: List[str]
    for index in range(start, end):
        match = None if mask[index] else CASE_RE.match(lines[index])
        if match is None:
            continue
        case_id = match.group(1)
        if case_id in found:
            raise GateError("task %s: duplicate Test Case ID %s" % (task_id, case_id))
        found.append(case_id)
    return tuple(found)


def _skills_value(value: str) -> Tuple[str, ...]:
    text = value.strip()
    if text.lower() in ("", "none"):
        return ()
    return _split_values(text)


def _skills(lines: List[str], mask: List[bool], start: int, end: int) -> Tuple[str, ...]:
    for index in range(start, end):
        if mask[index]:
            continue
        text = lines[index].replace("*", "").strip()
        if text.startswith("- "):
            text = text[2:].strip()
        if text.startswith(SKILLS_PREFIX):
            return _skills_value(text[len(SKILLS_PREFIX):])
    return ()


def parse_gate(text: str, task_id: str) -> GateBlock:
    lines = text.splitlines()
    mask = pc.fence_mask(lines)
    start, end = _task_span(lines, mask, task_id)
    gate_lines = [
        index for index in range(start, end)
        if not mask[index] and _plain(lines[index]) == GATE_LINE
    ]
    if not gate_lines:
        raise GateError("task %s has no Gate block" % task_id)
    if len(gate_lines) > 1:
        raise GateError("task %s: two Gate lines" % task_id)
    gate_index = gate_lines[0]
    values = _gate_values(task_id, _gate_items(lines, mask, gate_index, end))
    _check_gate(task_id, values)
    return GateBlock(
        task_id=task_id,
        line=gate_index + 1,
        files=values["files"],
        tests=values["tests"],
        red=values["red"],
        guard=values["guard"],
        green=values["green"],
        case_ids=_case_ids(task_id, lines, mask, start, end),
        skills=_skills(lines, mask, start, end),
    )
