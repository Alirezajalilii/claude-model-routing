"""PreToolUse guard: block Agent/Task delegations that break the routing policy.

Every Agent or Task call is checked (exit 2, one reason per line on stderr).
The agent is `subagent_type`, or `general-purpose` when it is missing or empty.
  - A tier agent (bare or plugin-scoped) is blocked when its prompt has no
    `Skills:` line; when that line names anything but `none` or readable
    absolute SKILL.md paths; when it is a non-planner without the line
    "Never consult the advisor."; when it has no `Output:` line with an
    absolute path; or when that path's file name matches
    `dispatch.blocked_output_names`, the names Claude Code's Write tool
    refuses to subagents.
  - An agent type that is neither a tier nor in `dispatch.allow_agents` of the
    routing config is blocked.
  - Any agent is blocked when it passes a non-empty `model` or `effort`.

Malformed input, config errors and internal errors exit 0 (fail open).
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Mapping, Optional, TextIO

import routing_config as rc

GUARDED_TOOLS = frozenset({"Agent", "Task"})
PARAMETERS = ("model", "effort")
SKILLS_LINE = re.compile(r"\bSkills:[ \t]*\S")
SKILLS_VALUE = re.compile(r"\bSkills:[ \t]*([^\n]*)")
OUTPUT_LINE = re.compile(r"\bOutput:[ \t]*(\S+)")
NONE_VALUE = re.compile(r"^\W*none\b", re.IGNORECASE)
DEFAULT_AGENT = "general-purpose"
ADVISOR_LINE = re.compile(r"never consult the advisor", re.IGNORECASE)


def _is_set(value: Any) -> bool:
    return value is not None and str(value).strip() != ""


def _prompt_of(tool_input: Mapping) -> str:
    prompt = tool_input.get("prompt")
    return prompt if isinstance(prompt, str) else ""


def _skill_items(prompt: str) -> list:
    match = SKILLS_VALUE.search(prompt)
    if not match or NONE_VALUE.match(match.group(1)):
        return []
    value = match.group(1).split(". ", 1)[0]
    items = (part.strip().strip("`'\".").strip() for part in value.split(","))
    return [item for item in items if item]


def _is_skill_file(item: str) -> bool:
    path = Path(item).expanduser()
    return path.is_absolute() and path.name == "SKILL.md" and path.is_file()


def _skills_reasons(agent: str, prompt: str, prefix: str) -> list:
    if not SKILLS_LINE.search(prompt):
        return [f"{prefix} delegation to {agent} has no Skills line. "
                "Add a line such as 'Skills: none' and resend."]
    return [
        f"{prefix} Skills line of the delegation to {agent} names '{item}', "
        "which is not a readable absolute SKILL.md path. "
        "Use 'Skills: none' or SKILL.md paths from the skills inventory."
        for item in _skill_items(prompt)
        if not _is_skill_file(item)
    ]


def _output_reasons(agent: str, prompt: str, prefix: str, blocked: str) -> list:
    match = OUTPUT_LINE.search(prompt)
    path = Path(match.group(1).rstrip(".")).expanduser() if match else None
    if path is None or not path.is_absolute():
        return [f"{prefix} delegation to {agent} has no Output line with an "
                "absolute file path. Add 'Output: /absolute/path.md' and resend."]
    if blocked and re.search(blocked, path.name, re.IGNORECASE):
        return [f"{prefix} Output file name '{path.name}' of the delegation to {agent} "
                "is one Claude Code refuses to let a subagent write. Rename it "
                "(for example exec-<task>.md or verdict-<task>.md) and resend."]
    return []


def _tier_reasons(agent: str, uses_advisor: bool, prompt: str, prefix: str,
                  blocked: str) -> list:
    reasons = _skills_reasons(agent, prompt, prefix)
    if not uses_advisor and not ADVISOR_LINE.search(prompt):
        reasons.append(
            f"{prefix} delegation to {agent} lacks the line "
            "'Never consult the advisor.'. Add it and resend.")
    return reasons + _output_reasons(agent, prompt, prefix, blocked)


def _parameter_reasons(tool_input: Mapping, agent: str, prefix: str) -> list:
    return [
        f"{prefix} parameter '{name}' must not be passed for agent {agent}. "
        "Remove it and resend."
        for name in PARAMETERS
        if _is_set(tool_input.get(name))
    ]


def _agent_reasons(tool_input: Mapping, agent: str, config: rc.RoutingConfig,
                   prefix: str) -> list:
    tier = rc.resolve_tier(agent, config)
    if tier is not None:
        uses_advisor = rc.role_of(tier, config).uses_advisor
        return _tier_reasons(agent, uses_advisor, _prompt_of(tool_input), prefix,
                             config.dispatch_blocked_output_names)
    if agent in config.dispatch_allow_agents:
        return []
    return [f"{prefix} subagent type '{agent}' is not a routing tier or an "
            "allowed agent. Dispatch a tier agent, or add the type to "
            "dispatch.allow_agents in the routing config."]


def evaluate(event: Mapping, config: rc.RoutingConfig) -> tuple:
    """Return the policy violations for one hook event; an empty tuple means allowed."""
    if event.get("tool_name") not in GUARDED_TOOLS:
        return ()
    tool_input = event.get("tool_input")
    if not isinstance(tool_input, dict):
        return ()
    subagent = tool_input.get("subagent_type")
    agent = subagent if isinstance(subagent, str) and subagent else DEFAULT_AGENT
    prefix = f"{config.plugin_name} dispatch guard:"
    reasons = _agent_reasons(tool_input, agent, config, prefix)
    return tuple(reasons + _parameter_reasons(tool_input, agent, prefix))


def _parse_args(argv: Optional[list]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="PreToolUse guard for tier-agent delegations.")
    parser.add_argument(
        "--config", type=Path, default=None,
        help="routing config JSON (default: the shipped config/routing.json)")
    return parser.parse_args(argv)


def _read_event(stream: TextIO) -> Optional[dict]:
    try:
        event = json.loads(stream.read())
    except (ValueError, TypeError):
        return None
    return event if isinstance(event, dict) else None


def main(argv: Optional[list] = None, stdin: Optional[TextIO] = None,
         stderr: Optional[TextIO] = None) -> int:
    """Read the hook event from stdin; exit 2 with the reasons on stderr when blocked."""
    args = _parse_args(argv)
    err = stderr if stderr is not None else sys.stderr
    event = _read_event(stdin if stdin is not None else sys.stdin)
    if event is None:
        return 0
    try:
        config = rc.load_config(args.config)
    except Exception as exc:  # fail open, but say why
        err.write(f"dispatch guard: config unavailable ({exc})\n")
        return 0
    try:
        reasons = evaluate(event, config)
    except Exception:  # fail open on any internal error
        return 0
    if not reasons:
        return 0
    err.write("\n".join(reasons) + "\n")
    return 2


if __name__ == "__main__":
    sys.exit(main())
