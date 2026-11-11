"""mr-gate: run the gate checks for one plan task and write the gate file.

This is the composition root: it reads the plan and the report, gathers data
through the git adapter (gate_git), hands it to the pure checks (gate_checks)
and renders the result. It holds no check logic and runs no subprocess itself.
The only file it writes is --out. main returns the exit code instead of exiting.
"""
from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Sequence, TextIO

import contract_presence
import gate_checks as gc
import gate_git as gg
import plan_contract
import plan_gate

EXIT_OK = 0
EXIT_FAIL = 1
EXIT_USAGE = 2
PROG = "mr-gate"
DEFAULT_TIMEOUT = 1800
SEPARATOR = " | "


class UsageError(Exception):
    """The arguments, the plan or the worktree cannot be used."""


@dataclass(frozen=True)
class Data:
    gate: plan_gate.GateBlock
    plan_text: str
    commits: List[str]
    base: str
    actual: List[str]
    changed: List[str]
    c1_files: List[str]
    later: List[str]
    diff: gc.ParsedDiff
    c1_added: str
    c1: str


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=PROG, description="Run the gate checks for one plan task and write the gate file.")
    parser.add_argument("plan")
    parser.add_argument("task_id")
    parser.add_argument("worktree")
    parser.add_argument("--commits", required=True,
                        help="comma-separated commit shas, oldest first")
    parser.add_argument("--report", required=True, help="the executor's output file")
    parser.add_argument("--out", required=True, help="the gate file to write")
    parser.add_argument("--base", help="the ref the task branched from")
    parser.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT,
                        help="seconds allowed per command (default %(default)s)")
    return parser


def _fence(text: str) -> str:
    longest = max((len(run) for run in re.findall(r"`+", text)), default=0)
    return "`" * max(3, longest + 1)


def _render_detail(detail: str) -> str:
    if SEPARATOR not in detail:
        return detail
    fence = _fence(detail)
    return "%s\n%s\n%s" % (fence, detail.replace(SEPARATOR, "\n", 1).replace(" / ", "\n"), fence)


def render_gate(task_id: str, plan: str, worktree: str, base: str,
                commits: Sequence[str], results: Sequence[gc.CheckResult]) -> str:
    failed = gc.failed_names(results)
    outcome = "FAIL (%s)" % ", ".join(failed) if failed else "PASS"
    lines = ["# Gate: %s" % task_id, "", "- plan: %s" % plan, "- worktree: %s" % worktree,
             "- base: %s" % base, "- commits: %s" % ",".join(commits),
             "- result: %s" % outcome]
    for result in results:
        lines += ["", "## %s: %s" % (result.name, result.status), _render_detail(result.detail)]
    return "\n".join(lines) + "\n"


def _read_text(path: str, what: str) -> str:
    try:
        return Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        raise UsageError("cannot read %s %s: %s" % (what, path, exc))


def _resolve_commits(worktree: Path, commits: Sequence[str]) -> List[str]:
    resolved = []
    for sha in commits:
        try:
            resolved.append(gg.resolve(worktree, sha))
        except gg.GitError:
            raise UsageError("unknown commit %s" % sha)
    return resolved


def _gather(args: argparse.Namespace, worktree: Path) -> Data:
    plan_text = _read_text(args.plan, "plan")
    try:
        gate = plan_gate.parse_gate(plan_text, args.task_id)
    except plan_gate.GateError as exc:
        raise UsageError(str(exc))
    if not worktree.is_dir():
        raise UsageError("worktree is not a directory: %s" % worktree)
    claimed = [sha for sha in args.commits.split(",") if sha]
    if not claimed:
        raise UsageError("--commits lists no commit")
    resolved = _resolve_commits(worktree, claimed)
    if not gg.is_clean(worktree):
        raise UsageError("worktree has uncommitted changes")
    c1 = resolved[0]
    base = (gg.merge_base(worktree, "HEAD", args.base) if args.base
            else gg.resolve(worktree, c1 + "^"))
    test_first = bool(gate.red or gate.guard)
    c1_diff = gc.parse_diff(gg.diff_text(worktree, base, c1))
    return Data(
        gate=gate, plan_text=plan_text, commits=claimed, base=base, c1=c1,
        actual=gg.commits_since(worktree, base),
        changed=gg.changed_files(worktree, base, "HEAD"),
        c1_files=gg.commit_files(worktree, c1),
        later=gg.changed_files(worktree, c1, "HEAD") if test_first else [],
        diff=gc.parse_diff(gg.diff_text(worktree, base, "HEAD")),
        c1_added="\n".join(line for added, _ in c1_diff.values() for line in added))


def _run_all(worktree: Path, commands: Sequence[str], timeout: int) -> List[gc.CommandResult]:
    return [gg.run_command(cmd, worktree, timeout) for cmd in commands]


def _run_red(data: Data, worktree: Path, timeout: int):
    if not (data.gate.red or data.gate.guard):
        return [], []
    with gg.checked_out(worktree, data.c1):
        return (_run_all(worktree, data.gate.red, timeout),
                _run_all(worktree, data.gate.guard, timeout))


def _run_green(data: Data, worktree: Path, timeout: int, report: Optional[str]):
    green = _run_all(worktree, data.gate.green, timeout)
    retry = [r.command for r in green
             if r.code != 0 and gc.listed_outside(r.command, report)]
    base: Dict[str, gc.CommandResult] = {}
    if retry:
        with gg.checked_out(worktree, data.base):
            base = {cmd: gg.run_command(cmd, worktree, timeout) for cmd in retry}
    return green, base


def _contract(data: Data, worktree: Path) -> gc.CheckResult:
    plan = plan_contract.parse_plan(data.plan_text)
    errors = plan_contract.validate(plan)
    lines = None if errors else contract_presence.check_task(plan, data.gate.task_id, worktree)
    return gc.contract_check(errors, lines)


def _checks(data: Data, worktree: Path, timeout: int,
            report: Optional[str]) -> List[gc.CheckResult]:
    gate = data.gate
    test_first = bool(gate.red or gate.guard)
    red, guard = _run_red(data, worktree, timeout)
    green, base_results = _run_green(data, worktree, timeout, report)
    return [
        gc.red_check(test_first, red, guard),
        gc.integrity_check(test_first, data.c1_files, data.later, gate.tests, data.diff),
        gc.coverage_check(test_first, gate.case_ids, data.c1_added),
        gc.scope_check(data.changed, gate.files, gate.tests),
        _contract(data, worktree),
        gc.green_check(green, base_results, report),
        gc.report_check(report, data.commits, data.actual, gate.skills),
    ]


def _read_report(path: str) -> Optional[str]:
    try:
        return Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


def _write_gate(out: str, text: str) -> None:
    path = Path(out)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _run(args: argparse.Namespace, stdout: TextIO) -> int:
    worktree = Path(args.worktree)
    data = _gather(args, worktree)
    results = _checks(data, worktree, args.timeout, _read_report(args.report))
    _write_gate(args.out, render_gate(args.task_id, args.plan, args.worktree,
                                      data.base, data.commits, results))
    failed = gc.failed_names(results)
    if failed:
        stdout.write("FAIL %s checks=%s\n" % (args.out, ",".join(failed)))
        return EXIT_FAIL
    stdout.write("PASS %s\n" % args.out)
    return EXIT_OK


def main(argv: Optional[Sequence[str]] = None, stdout: Optional[TextIO] = None,
         stderr: Optional[TextIO] = None) -> int:
    stdout = stdout or sys.stdout
    stderr = stderr or sys.stderr
    args = build_parser().parse_args(argv)
    try:
        return _run(args, stdout)
    except UsageError as exc:
        message = str(exc)
    except (gg.GitError, OSError) as exc:
        message = str(exc)
    except Exception as exc:  # the gate must report, not crash
        message = "internal error: %s" % exc
    stderr.write("%s: %s\n" % (PROG, message))
    return EXIT_USAGE


if __name__ == "__main__":
    sys.exit(main())
