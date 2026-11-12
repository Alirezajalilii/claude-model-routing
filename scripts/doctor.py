"""mr-doctor: check whether the plugin can work in this environment and project.

Every check takes its inputs as parameters (environment mapping, `which`, `run`,
version tuple, paths). Only `main` and the default subprocess adapter read the
real environment.
"""
from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
from collections import namedtuple
from pathlib import Path
from typing import Callable, Mapping, Optional, Sequence, TextIO

from routing_config import load_config
from session_context import SPAWN_DEPTH_VAR, collect_warnings

Check = namedtuple("Check", "status name detail fix")

MIN_PYTHON = (3, 9)
MIN_TESTED_CLAUDE = (2, 1, 306)
API_KEY_VAR = "ANTHROPIC_API_KEY"
PLAN_README = "docs/plans/README.md"
ROUTING_LOG = "docs/model-routing-log.md"
# Warnings from collect_warnings echo these variables' values; the report must not.
VALUE_ECHOING_VARS = (SPAWN_DEPTH_VAR, "CLAUDE_CODE_EFFORT_LEVEL", "CLAUDE_CODE_SUBAGENT_MODEL")
HIDDEN_VALUE = "`<value hidden>`"
VERSION_RE = re.compile(r"(\d+)\.(\d+)\.(\d+)")
COMMAND_TIMEOUT_SECONDS = 10


def _dotted(version: tuple) -> str:
    return ".".join(str(part) for part in version)


def check_python(version_info: tuple) -> Check:
    detail = f"Python {_dotted(version_info[:3])}"
    if tuple(version_info[:2]) >= MIN_PYTHON:
        return Check("OK", "python", detail, "")
    return Check(
        "FAIL",
        "python",
        detail,
        "Install Python 3.9 or later and make it available as python3.",
    )


def parse_claude_version(text: str) -> Optional[tuple]:
    match = VERSION_RE.search(text)
    if match is None:
        return None
    return tuple(int(part) for part in match.groups())


def check_claude(which: Callable, run: Callable) -> Check:
    if which("claude") is None:
        return Check(
            "WARN",
            "claude",
            "claude CLI not found on PATH",
            "Install Claude Code, or ask Claude to run mr-doctor from its Bash tool.",
        )
    try:
        output = run(["claude", "--version"])
    except (OSError, subprocess.TimeoutExpired):
        return Check("WARN", "claude", "could not run claude --version", "")
    version = parse_claude_version(output)
    if version is None:
        return Check("WARN", "claude", "could not read the Claude Code version", "")
    if version < MIN_TESTED_CLAUDE:
        detail = (
            f"Claude Code {_dotted(version)} is older than {_dotted(MIN_TESTED_CLAUDE)}, "
            "the oldest version mr was checked on"
        )
        return Check("WARN", "claude", detail, "Update Claude Code.")
    return Check("OK", "claude", f"Claude Code {_dotted(version)}", "")


def _hide_value(text: str, env: Mapping[str, str]) -> str:
    """Replace the echoed value of a warning's own variable with a placeholder."""
    for name in VALUE_ECHOING_VARS:
        value = env.get(name, "")
        if value and text.startswith(f"`{name}`"):
            return text.replace(f"`{value}`", HIDDEN_VALUE, 1)
    return text


def check_settings(env: Mapping[str, str], config) -> list:
    warnings = collect_warnings(env, {}, config)
    if not warnings:
        return [Check("OK", "settings", f"no overrides; {SPAWN_DEPTH_VAR} is 1", "")]
    return [Check("WARN", "settings", _hide_value(text, env), "") for text in warnings]


def check_api_key(env: Mapping[str, str]) -> Optional[Check]:
    if not env.get(API_KEY_VAR, ""):
        return None
    detail = (
        f"{API_KEY_VAR} is set: Claude Code bills this key at API rates "
        "instead of your subscription"
    )
    return Check("INFO", "billing", detail, "")


def check_project(project_dir: Path) -> Check:
    required = (PLAN_README, ROUTING_LOG)
    missing = [rel for rel in required if not (project_dir / rel).is_file()]
    if not missing:
        return Check("OK", "project", "initialized", "")
    return Check(
        "WARN",
        "project",
        "missing " + ", ".join(missing),
        "Run mr-init --claude-md in the project root, or /mr:init-project in Claude Code.",
    )


def run_checks(
    env: Mapping[str, str],
    project_dir,
    version_info: tuple,
    which: Callable,
    run: Callable,
) -> list:
    python_check = check_python(version_info)
    try:
        config = load_config()
    except Exception as exc:  # any load failure is reported, not raised
        return [
            python_check,
            Check(
                "FAIL",
                "config",
                f"routing config could not be loaded: {exc}",
                "Reinstall the plugin.",
            ),
        ]
    checks = [python_check, check_claude(which, run)]
    checks.extend(check_settings(env, config))
    billing = check_api_key(env)
    if billing is not None:
        checks.append(billing)
    checks.append(check_project(Path(project_dir)))
    return checks


def render(checks: list) -> str:
    lines = []
    for check in checks:
        lines.append(f"{check.status:<4} {check.name}: {check.detail}")
        if check.fix:
            lines.append(f"     fix: {check.fix}")
    failed = sum(1 for check in checks if check.status == "FAIL")
    warned = sum(1 for check in checks if check.status == "WARN")
    lines.append(f"mr-doctor: {failed} failed, {warned} warnings")
    return "\n".join(lines)


def run_command(args: Sequence[str]) -> str:
    proc = subprocess.run(
        list(args),
        capture_output=True,
        text=True,
        timeout=COMMAND_TIMEOUT_SECONDS,
        check=False,
    )
    return proc.stdout


def _parse_args(argv: Optional[Sequence[str]]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="mr-doctor",
        description="Check whether the mr plugin can work in this environment and project.",
    )
    parser.add_argument(
        "--project-dir",
        default=None,
        help="project root (default: CLAUDE_PROJECT_DIR, else the current directory)",
    )
    return parser.parse_args(argv)


def main(
    argv: Optional[Sequence[str]] = None,
    env: Optional[Mapping[str, str]] = None,
    which: Callable = shutil.which,
    run: Callable = run_command,
    version_info: tuple = sys.version_info[:3],
    stdout: Optional[TextIO] = None,
) -> int:
    args = _parse_args(argv)
    environment = os.environ if env is None else env
    project_dir = args.project_dir or environment.get("CLAUDE_PROJECT_DIR") or os.getcwd()
    checks = run_checks(environment, project_dir, version_info, which, run)
    print(render(checks), file=stdout if stdout is not None else sys.stdout)
    return 1 if any(check.status == "FAIL" for check in checks) else 0
