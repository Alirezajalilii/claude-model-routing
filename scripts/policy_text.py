"""Strict placeholder renderer for policy text fragments."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Mapping

from routing_config import REPO_ROOT, ROLES, RoutingConfig

SECTIONS_DIR = REPO_ROOT / "policy" / "sections"
PLACEHOLDER = re.compile(r"\{\{\s*([a-z_]+)(?::([a-z0-9-]+))?\s*\}\}")
MAX_DEPTH = 3
ROLE_LABELS = {
    "scout": "Scouts",
    "planner": "Planners",
    "executor": "Executors",
    "verifier": "Verifiers",
}
PERCENT_KEYS = {
    "calibration_sample_percent": "calibration_sample_rate",
    "calibration_low_defect_percent": "calibration_low_defect_rate",
    "calibration_reduced_sample_percent": "calibration_reduced_sample_rate",
    "calibration_high_defect_percent": "calibration_high_defect_rate",
}
INT_KEYS = (
    "planner_evidence_budget",
    "max_evidence_rounds",
    "max_fix_rounds_per_tier",
    "max_executor_escalations",
    "skill_cap_haiku",
    "skill_cap_other",
    "calibration_first_tasks",
)


def render_roster(config: RoutingConfig) -> str:
    lines = []
    for role in ROLES:
        entries = ", ".join(
            f"`{t.name}` ({t.model}, {t.effort})" for t in config.tiers if t.role == role
        )
        lines.append(f"- {ROLE_LABELS[role]}: {entries}")
    return "\n".join(lines)


def base_values(config: RoutingConfig) -> dict:
    tunables = config.tunables
    values = {
        "plugin_name": config.plugin_name,
        "dispatcher_model_family": config.dispatcher_model_family,
        "dispatcher_effort": config.dispatcher_effort,
        "tier_roster": render_roster(config),
    }
    for key in INT_KEYS:
        values[key] = str(tunables[key])
    for key, rate_key in PERCENT_KEYS.items():
        values[key] = f"{tunables[rate_key] * 100:g}"
    rate = tunables["calibration_sample_rate"]
    values["calibration_draw_command"] = (
        f'python3 -c "import random; print(random.random() < {rate:g})"'
    )
    return values


def _replace(match: "re.Match[str]", values: Mapping, sections_dir: Path, depth: int) -> str:
    name, arg = match.group(1), match.group(2)
    if arg is not None:
        if name != "section":
            raise ValueError(f"unknown placeholder form: {match.group(0)}")
        if depth + 1 > MAX_DEPTH:
            raise ValueError("section include depth exceeded")
        path = sections_dir / f"{arg}.md"
        if not path.is_file():
            raise ValueError(f"unknown section: {arg}")
        text = path.read_text(encoding="utf-8").rstrip()
        return render(text, values, sections_dir, depth + 1)
    if name not in values:
        raise ValueError(f"unknown placeholder: {name}")
    return values[name]


def render(text: str, values: Mapping, sections_dir: Path = SECTIONS_DIR, depth: int = 0) -> str:
    if depth > MAX_DEPTH:
        raise ValueError("section include depth exceeded")
    return PLACEHOLDER.sub(lambda m: _replace(m, values, sections_dir, depth), text)


def part_count(config: RoutingConfig) -> int:
    return len(config.dispatcher_parts)


def render_part(config: RoutingConfig, index: int, sections_dir: Path = SECTIONS_DIR) -> str:
    total = part_count(config)
    if not 1 <= index <= total:
        raise ValueError(f"part index {index} out of range 1..{total}")
    part = config.dispatcher_parts[index - 1]
    values = base_values(config)
    header = f"# {config.plugin_name} policy, part {index} of {total}: {part.title}"
    bodies = [render(f"{{{{section:{s}}}}}", values, sections_dir).rstrip() for s in part.sections]
    return "\n\n".join([header] + bodies)
