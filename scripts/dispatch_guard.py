"""PreToolUse guard: block tier-agent delegations that break the routing policy.

A call is checked only when its tool is Agent or Task and its subagent_type names
a configured tier, bare or plugin-scoped. The call is blocked (exit 2, one reason
per line on stderr) when it:
  - passes a non-empty `model` or `effort` (the agent frontmatter sets them);
  - has no `Skills:` line in the prompt;
  - is a non-planner delegation without the line "Never consult the advisor.".

Anything else, including malformed input, exits 0 (fail open).
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
ADVISOR_LINE = re.compile(r"never consult the advisor", re.IGNORECASE)


def _is_set(value: Any) -> bool:
    return value is not None and str(value).strip() != ""


def _prompt_of(tool_input: Mapping) -> str:
    prompt = tool_input.get("prompt")
    return prompt if isinstance(prompt, str) else ""


def _prompt_reasons(agent: str, uses_advisor: bool, prompt: str, prefix: str) -> list:
    reasons = []
    if not SKILLS_LINE.search(prompt):
        reasons.append(
            f"{prefix} delegation to {agent} has no Skills line. "
            "Add a line such as 'Skills: none' and resend.")
    if not uses_advisor and not ADVISOR_LINE.search(prompt):
        reasons.append(
            f"{prefix} delegation to {agent} lacks the line "
            "'Never consult the advisor.'. Add it and resend.")
    return reasons


def _parameter_reasons(tool_input: Mapping, agent: str, prefix: str) -> list:
    return [
        f"{prefix} parameter '{name}' must not be passed for tier agent {agent}; "
        "its frontmatter sets it. Remove it and resend."
        for name in PARAMETERS
        if _is_set(tool_input.get(name))
    ]


def evaluate(event: Mapping, config: rc.RoutingConfig) -> tuple:
    """Return the policy violations for one hook event; an empty tuple means allowed."""
    if event.get("tool_name") not in GUARDED_TOOLS:
        return ()
    tool_input = event.get("tool_input")
    if not isinstance(tool_input, dict):
        return ()
    agent = tool_input.get("subagent_type")
    tier = rc.resolve_tier(agent, config)
    if tier is None:
        return ()
    uses_advisor = rc.role_of(tier, config).uses_advisor
    prefix = f"{config.plugin_name} dispatch guard:"
    reasons = _prompt_reasons(agent, uses_advisor, _prompt_of(tool_input), prefix)
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
