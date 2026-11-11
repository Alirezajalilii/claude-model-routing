"""Derive task dependencies from the Contract items of a plan and layer the tasks into waves."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Set, Tuple

from plan_contract import PlanContract, Task

CYCLE_PREFIX = "requires or after form a cycle: "


@dataclass(frozen=True)
class WavePlan:
    waves: Tuple[Tuple[str, ...], ...]
    dependencies: Dict[str, Tuple[str, ...]]
    cycle: str


def _task_deps(task: Task, ids: Set[str], order: Dict[str, int]) -> Tuple[str, ...]:
    named = [req.provider for req in task.requires] + [target for target, _ in task.after]
    known = {name for name in named if name in ids and name != task.task_id}
    return tuple(sorted(known, key=lambda name: order[name]))


def dependencies(plan: PlanContract) -> Dict[str, Tuple[str, ...]]:
    order = {}  # type: Dict[str, int]
    for index, task in enumerate(plan.tasks):
        order.setdefault(task.task_id, index)
    ids = set(order)
    return {task.task_id: _task_deps(task, ids, order) for task in plan.tasks}


def _ready(remaining: List[str], deps: Dict[str, Tuple[str, ...]], done: Set[str]) -> List[str]:
    return [
        task_id for task_id in remaining
        if all(dep in done for dep in deps[task_id])
    ]


def _cycle_text(remaining: List[str], deps: Dict[str, Tuple[str, ...]]) -> str:
    left = set(remaining)
    path = [remaining[0]]  # type: List[str]
    position = {remaining[0]: 0}  # type: Dict[str, int]
    while True:
        nxt = next(dep for dep in deps[path[-1]] if dep in left)
        if nxt in position:
            return " -> ".join(path[position[nxt]:] + [nxt])
        position[nxt] = len(path)
        path.append(nxt)


def plan_waves(plan: PlanContract) -> WavePlan:
    deps = dependencies(plan)
    remaining = list(deps)
    done = set()  # type: Set[str]
    waves = []  # type: List[Tuple[str, ...]]
    while remaining:
        ready = _ready(remaining, deps, done)
        if not ready:
            return WavePlan((), deps, _cycle_text(remaining, deps))
        waves.append(tuple(ready))
        done.update(ready)
        remaining = [task_id for task_id in remaining if task_id not in done]
    return WavePlan(tuple(waves), deps, "")


def _task_text(task_id: str, deps: Tuple[str, ...]) -> str:
    if not deps:
        return task_id
    return "%s (%s)" % (task_id, ", ".join(deps))


def format_waves(wave_plan: WavePlan) -> str:
    if wave_plan.cycle:
        return CYCLE_PREFIX + wave_plan.cycle
    lines = []  # type: List[str]
    for number, wave in enumerate(wave_plan.waves, 1):
        items = [_task_text(task_id, wave_plan.dependencies[task_id]) for task_id in wave]
        lines.append("wave %d: %s" % (number, ", ".join(items)))
    return "\n".join(lines)
