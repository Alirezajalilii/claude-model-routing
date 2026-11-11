"""mr-plan: validate a plan's task contracts, print run waves, and check a task in a worktree.

Read-only: nothing is written to disk. main returns the exit code instead of exiting.
"""
from __future__ import annotations

import argparse
import contextlib
import os
import sys
from pathlib import Path
from typing import List, Optional, TextIO

import contract_presence as cp
import plan_contract as pc
import plan_waves as pw

EXIT_OK = 0
EXIT_FAIL = 1
EXIT_USAGE = 2
NO_CHECK_LINES = "no provides or requires lines"


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validate task contracts in a plan, print run waves, or check a task in a worktree."
    )
    sub = parser.add_subparsers(dest="command", required=True)
    waves = sub.add_parser("waves", help="validate the plan and print its run waves")
    waves.add_argument("plan")
    check = sub.add_parser("check", help="check one task's provides and requires in a worktree")
    check.add_argument("plan")
    check.add_argument("task_id")
    check.add_argument("worktree")
    return parser


def _report(prog: str, messages: List[str], stderr: TextIO) -> int:
    for message in messages:
        stderr.write("%s: %s\n" % (prog, message))
    return EXIT_FAIL


def _read_plan(plan: str, prog: str, stderr: TextIO) -> Optional[pc.PlanContract]:
    try:
        text = Path(plan).read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        stderr.write("%s: cannot read %s: %s\n" % (prog, plan, exc))
        return None
    return pc.parse_plan(text)


def _cmd_waves(plan_path: str, prog: str, stdout: TextIO, stderr: TextIO) -> int:
    plan = _read_plan(plan_path, prog, stderr)
    if plan is None:
        return EXIT_USAGE
    errors = pc.validate(plan)
    if errors:
        return _report(prog, errors, stderr)
    wave_plan = pw.plan_waves(plan)
    if wave_plan.cycle:
        return _report(prog, [pw.format_waves(wave_plan)], stderr)
    stdout.write(pw.format_waves(wave_plan) + "\n")
    return EXIT_OK


def _print_checks(lines: List[cp.CheckLine], stdout: TextIO) -> int:
    if not lines:
        stdout.write(NO_CHECK_LINES + "\n")
        return EXIT_OK
    code = EXIT_OK
    for line in lines:
        if line.ok:
            stdout.write("ok: %s\n" % line.text)
        else:
            stdout.write("missing: %s (%s)\n" % (line.text, line.detail))
            code = EXIT_FAIL
    return code


def _cmd_check(args: argparse.Namespace, prog: str, stdout: TextIO, stderr: TextIO) -> int:
    plan = _read_plan(args.plan, prog, stderr)
    if plan is None:
        return EXIT_USAGE
    errors = pc.validate(plan)
    if errors:
        return _report(prog, errors, stderr)
    if not os.path.isdir(args.worktree):
        stderr.write("%s: %s is not a directory\n" % (prog, args.worktree))
        return EXIT_USAGE
    try:
        lines = cp.check_task(plan, args.task_id, Path(args.worktree))
    except cp.UnknownTask:
        stderr.write("%s: no task %s in %s\n" % (prog, args.task_id, args.plan))
        return EXIT_USAGE
    return _print_checks(lines, stdout)


def _dispatch(args: argparse.Namespace, prog: str, stdout: TextIO, stderr: TextIO) -> int:
    if args.command == "waves":
        return _cmd_waves(args.plan, prog, stdout, stderr)
    return _cmd_check(args, prog, stdout, stderr)


def main(
    argv: Optional[List[str]] = None,
    stdout: Optional[TextIO] = None,
    stderr: Optional[TextIO] = None,
) -> int:
    out = stdout if stdout is not None else sys.stdout
    err = stderr if stderr is not None else sys.stderr
    parser = _build_parser()
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            args = parser.parse_args(argv)
    except SystemExit as exc:
        return exc.code if isinstance(exc.code, int) else EXIT_USAGE
    try:
        return _dispatch(args, parser.prog, out, err)
    except Exception as exc:  # any unexpected failure is an internal error
        err.write("%s: internal error: %s\n" % (parser.prog, exc))
        return EXIT_USAGE
