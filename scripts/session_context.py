"""SessionStart hook: inject one part of the dispatcher policy into the session."""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Mapping, Optional, Sequence, TextIO

from policy_text import SECTIONS_DIR, part_count, render_part
from routing_config import RoutingConfig, load_config, model_family, resolve_tier

MAX_CONTEXT_CHARS = 9900
SPAWN_DEPTH_VAR = "CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH"


def parse_event(text: str) -> dict:
    """Return the hook event as a dict, or an empty dict when it is not one."""
    try:
        event = json.loads(text)
    except ValueError:
        return {}
    return event if isinstance(event, dict) else {}


def _flag_on(value: str) -> bool:
    return value.lower() not in ("0", "false")


def _spawn_depth_warning(env: Mapping[str, str]) -> Optional[str]:
    depth = env.get(SPAWN_DEPTH_VAR, "")
    if depth == "1":
        return None
    state = f"`{depth}`" if depth else "not set"
    return (
        f"`{SPAWN_DEPTH_VAR}` is {state}. Set it to `1` in your settings env "
        "so subagents cannot spawn subagents."
    )


def _model_warning(event: Mapping, config: RoutingConfig) -> Optional[str]:
    model = event.get("model")
    family = model_family(model)
    if not isinstance(model, str) or not model or family is None:
        return None
    if family == config.dispatcher_model_family:
        return None
    family = config.dispatcher_model_family
    return (
        f"This session runs on `{model}`, but the policy expects the main session "
        f"on the `{family}` model family. In your first reply, before anything else, "
        "tell the user: switch with `/model` in the CLI, or pick a "
        f"`{family}` model in the desktop app's model picker for new sessions "
        "(it remembers the choice)."
    )


def collect_warnings(env: Mapping[str, str], event: Mapping, config: RoutingConfig) -> list:
    """Return configuration warnings for this session, in a fixed order."""
    candidates = []
    effort = env.get("CLAUDE_CODE_EFFORT_LEVEL", "")
    if effort:
        candidates.append(
            f"`CLAUDE_CODE_EFFORT_LEVEL` is set to `{effort}`. It overrides the effort "
            "of every tier agent; unset it in your shell profile and settings env."
        )
    subagent_model = env.get("CLAUDE_CODE_SUBAGENT_MODEL", "")
    if subagent_model:
        candidates.append(
            f"`CLAUDE_CODE_SUBAGENT_MODEL` is set to `{subagent_model}`. The policy "
            "requires it unset; with `CLAUDE_CODE_SUBAGENT_MODEL_FORCE` it overrides "
            "every tier agent's model."
        )
    force = env.get("CLAUDE_CODE_SUBAGENT_MODEL_FORCE", "")
    if force and _flag_on(force):
        candidates.append(
            "`CLAUDE_CODE_SUBAGENT_MODEL_FORCE` is set. It makes every tier agent "
            "ignore its frontmatter model; unset it."
        )
    candidates.append(_spawn_depth_warning(env))
    candidates.append(_model_warning(event, config))
    return [text for text in candidates if text]


def _session_block(event: Mapping) -> str:
    sid = event.get("session_id")
    if not isinstance(sid, str) or not sid:
        return ""
    return (
        f"\n\n## Session\n- Session id: `{sid}`. Pass it to `model-routing-usage` "
        "and `model-routing-audit`."
    )


def _warning_block(warnings: Sequence[str]) -> str:
    if not warnings:
        return ""
    return "\n\n## Configuration warnings\n" + "\n".join(f"- {w}" for w in warnings)


def _fallback(config: RoutingConfig, part: int) -> str:
    section_ids = config.dispatcher_parts[part - 1].sections
    return (
        f"# {config.plugin_name} policy, part {part} of {part_count(config)}: "
        f"{config.dispatcher_parts[part - 1].title}\n\n"
        "This part is too long for session-start context. Invoke the skill "
        f"`{config.plugin_name}:routing-policy` and read these sections: "
        f"{', '.join(section_ids)}."
    )


def build_context(
    config: RoutingConfig,
    part: int,
    event: Mapping,
    env: Mapping[str, str],
    sections_dir: Path = SECTIONS_DIR,
) -> str:
    """Return the additional context for one dispatcher part."""
    policy = render_part(config, part, sections_dir)
    extra = ""
    if part == 1:
        extra = _session_block(event) + _warning_block(collect_warnings(env, event, config))
    if len(policy) + len(extra) > MAX_CONTEXT_CHARS:
        policy = _fallback(config, part)
    return policy + extra


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--part", type=int, required=True, help="dispatcher part number")
    return parser


def main(
    argv: Optional[Sequence[str]] = None,
    stdin: Optional[TextIO] = None,
    stdout: Optional[TextIO] = None,
    stderr: Optional[TextIO] = None,
    env: Optional[Mapping[str, str]] = None,
    config: Optional[RoutingConfig] = None,
    sections_dir: Optional[Path] = None,
) -> int:
    args = _parser().parse_args(argv)
    stdin = sys.stdin if stdin is None else stdin
    stdout = sys.stdout if stdout is None else stdout
    stderr = sys.stderr if stderr is None else stderr
    env = os.environ if env is None else env
    try:
        cfg = config if config is not None else load_config()
        event = parse_event(stdin.read())
        if resolve_tier(event.get("agent_type"), cfg) is not None:
            return 0
        text = build_context(cfg, args.part, event, env, sections_dir or SECTIONS_DIR)
    except Exception as exc:  # hook must report, never crash the session
        stderr.write(f"session_context: {exc}\n")
        return 1
    payload = {"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": text}}
    print(json.dumps(payload), file=stdout)
    return 0


if __name__ == "__main__":
    sys.exit(main())
