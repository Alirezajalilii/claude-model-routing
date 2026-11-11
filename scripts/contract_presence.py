"""Check that a plan task's provides and requires are present in a worktree.

Read-only: nothing is written and no file is changed. provide_present never
raises; check_task raises only UnknownTask.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import List, Tuple

import plan_contract as pc

WHOLE_WORD_KINDS = ("symbol", "config")


class UnknownTask(Exception):
    """Raised by check_task when the plan has no task with the given ID."""


@dataclass(frozen=True)
class CheckLine:
    ok: bool
    text: str
    detail: str


def _inside(target: Path, root: Path) -> bool:
    try:
        target.resolve().relative_to(root.resolve())
    except (OSError, RuntimeError, ValueError):
        return False
    return True


def _is_file(path: Path) -> bool:
    try:
        return path.is_file()
    except OSError:
        return False


def _whole_word(name: str, text: str) -> bool:
    part = name.rsplit(".", 1)[-1]
    pattern = r"(?<![A-Za-z0-9_])" + re.escape(part) + r"(?![A-Za-z0-9_])"
    return re.search(pattern, text) is not None


def _json_key_present(provide: pc.Provide, text: str) -> Tuple[bool, str]:
    try:
        data = json.loads(text)
    except (ValueError, RecursionError):
        return False, "invalid JSON: %s" % provide.path
    node = data
    for key in provide.name.split("."):
        if not isinstance(node, dict) or key not in node:
            return False, "key path not found in %s" % provide.path
        node = node[key]
    return True, ""


def _text_present(provide: pc.Provide, text: str) -> Tuple[bool, str]:
    if provide.kind == "config" and provide.path.endswith(".json"):
        return _json_key_present(provide, text)
    if provide.kind in WHOLE_WORD_KINDS:
        found = _whole_word(provide.name, text)
    else:
        found = provide.name in text
    if found:
        return True, ""
    return False, "not found in %s" % provide.path


def provide_present(provide: pc.Provide, root: Path) -> Tuple[bool, str]:
    """Return (present, detail); detail is "" when the provide is present."""
    if provide.kind == "file":
        target = root / provide.name
    else:
        target = root / provide.path
    if not _inside(target, root):
        return False, "path leaves the worktree"
    if provide.kind == "file":
        return (True, "") if _is_file(target) else (False, "file missing")
    if not _is_file(target):
        return False, "file missing: %s" % provide.path
    try:
        text = target.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False, "unreadable: %s" % provide.path
    return _text_present(provide, text)


def _find_task(plan: pc.PlanContract, task_id: str) -> pc.Task:
    for task in plan.tasks:
        if task.task_id == task_id:
            return task
    raise UnknownTask(task_id)


def _provide_line(provide: pc.Provide, root: Path) -> CheckLine:
    ok, detail = provide_present(provide, root)
    text = "provides %s %s" % (provide.kind, provide.name)
    if provide.path:
        text += " in %s" % provide.path
    return CheckLine(ok, text, detail)


def _require_line(plan: pc.PlanContract, require: pc.Require, root: Path) -> CheckLine:
    text = "requires %s from %s" % (require.name, require.provider)
    provide = pc.find_provide(plan, require.provider, require.name)
    if provide is None:
        detail = "%s provides no '%s'" % (require.provider, require.name)
        return CheckLine(False, text, detail)
    ok, detail = provide_present(provide, root)
    return CheckLine(ok, text, detail)


def check_task(plan: pc.PlanContract, task_id: str, root: Path) -> List[CheckLine]:
    """Return one CheckLine per provide, then one per require, of the task."""
    task = _find_task(plan, task_id)
    lines = [_provide_line(provide, root) for provide in task.provides]
    lines.extend(_require_line(plan, require, root) for require in task.requires)
    return lines
