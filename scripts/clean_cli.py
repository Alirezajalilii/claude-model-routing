"""mr-clean: remove what one mr run created: its local branches merged into the base branch, their clean worktrees, its handoff directory and the session scratchpad's contents. Dry run unless --apply. Every input is checked before anything changes."""

from __future__ import annotations

import argparse
import os
import shutil
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Pattern, Sequence, Set, Tuple

import clean_git as cg
import clean_scope as cs
from plan_contract import Task, parse_plan

EXIT_OK, EXIT_FAIL, EXIT_USAGE = 0, 1, 2
DESCRIPTION = ("Remove what one mr run created: its local branches merged into the base "
               "branch, their clean worktrees, its handoff directory and the session "
               "scratchpad's contents. Dry run unless --apply.")
DRY_RUN_HEADER = ("mr-clean: dry run; nothing changed. "
                  "Run again with --apply to remove the items below.")


class UsageError(Exception):
    """A command-line input is missing, malformed or refused."""


@dataclass(frozen=True)
class Action:
    """One change; kind is worktree, branch, directory or scratch, needs the worktree a branch depends on."""

    kind: str
    target: str
    text: str
    needs: str = ""


@dataclass
class Cleanup:
    """Planned actions, kept items and notes, in print order."""

    actions: List[Action] = field(default_factory=list)
    kept: List[str] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)
    branches_kept: int = 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="mr-clean", description=DESCRIPTION)
    parser.add_argument("--plan", metavar="PATH",
                        help="take the owned branches from this plan file")
    parser.add_argument("--branch", metavar="NAME", action="append", default=[],
                        help="an explicitly owned branch (repeatable)")
    parser.add_argument("--base", metavar="NAME", default="main",
                        help="branch the owned branches must be merged into (default: main)")
    parser.add_argument("--handoff", metavar="DIR",
                        help="handoff directory to remove (git-ignored, inside the repository)")
    parser.add_argument("--scratch", metavar="DIR",
                        help="scratch directory whose contents are emptied (inside a temp directory)")
    parser.add_argument("--repo", metavar="DIR",
                        help="repository (default: the current directory)")
    parser.add_argument("--apply", action="store_true",
                        help="perform the actions (default: dry run)")
    return parser


def _plan_tasks(plan_arg: str, cwd: Path) -> List[Task]:
    try:
        text = (cwd / plan_arg).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as error:
        raise UsageError(f"cannot read plan: {plan_arg}") from error
    tasks = list(parse_plan(text).tasks)
    if not tasks:
        raise UsageError(f"no tasks found in plan: {plan_arg}")
    return tasks


def owned_branches(args: argparse.Namespace, repo: Path,
                   cwd: Path) -> Tuple[List[str], List[str]]:
    pattern: Optional[Pattern[str]] = None
    if args.plan:
        tasks = _plan_tasks(args.plan, cwd)
        pattern = cs.owned_pattern(cs.plan_slug(args.plan),
                                   [task.task_id for task in tasks])
    return cs.select_owned(cg.local_branches(repo), pattern, args.branch)


def _relative_to_repo(path: Path, repo: Path) -> Optional[str]:
    try:
        return path.resolve().relative_to(repo.resolve()).as_posix()
    except ValueError:
        return None


def _held_paths(args: argparse.Namespace, repo: Path, cwd: Path) -> List[Path]:
    """Paths a handoff directory may not hold: linked worktrees and the plan file."""
    held = [Path(wt.path)
            for wt in cs.parse_worktrees(cg.worktree_porcelain(repo))[1:]]
    if args.plan:
        held.append(cwd / args.plan)
    return held


def _handoff_action(args: argparse.Namespace, repo: Path, cwd: Path) -> Action:
    path = cwd / args.handoff
    rel = _relative_to_repo(path, repo)
    ignored = rel is not None and cg.is_ignored(repo, rel)
    problem = cs.handoff_problem(path, repo, ignored, _held_paths(args, repo, cwd))
    if problem is not None:
        raise UsageError(f"refused --handoff: {problem}")
    target = path.resolve()
    return Action("directory", str(target), f"remove directory {target}")


def _scratch_action(args: argparse.Namespace, cwd: Path, tempdir: str) -> Action:
    path = cwd / args.scratch
    problem = cs.scratch_problem(path, cs.temp_roots(tempdir))
    if problem is not None:
        raise UsageError(f"refused --scratch: {problem}")
    target = path.resolve()
    return Action("scratch", str(target), f"empty directory {target}")


def dir_actions(args: argparse.Namespace, repo: Path, cwd: Path,
                tempdir: str) -> List[Action]:
    actions: List[Action] = []
    if args.handoff:
        actions.append(_handoff_action(args, repo, cwd))
    if args.scratch:
        actions.append(_scratch_action(args, cwd, tempdir))
    return actions


def worktree_reason(wt: cs.Worktree, cwd: Path) -> Optional[str]:
    """Why a linked worktree must stay, or None when it may be removed."""
    if wt.prunable:
        return f"worktree {wt.path} is missing"
    if wt.locked:
        return f"worktree {wt.path} is locked"
    path = Path(wt.path).resolve()
    if cwd == path or path in cwd.parents:
        return f"worktree {wt.path} contains the current directory"
    if not cg.is_clean(Path(wt.path)):
        return f"worktree {wt.path} has uncommitted changes"
    return None


def _keep_branch(out: Cleanup, text: str) -> None:
    out.kept.append(text)
    out.branches_kept += 1


def plan_branch(repo: Path, name: str, base: str, current: Optional[str],
                linked: Sequence[cs.Worktree], cwd: Path, out: Cleanup) -> None:
    if cs.is_protected(name, base, current):
        _keep_branch(out, f"keep branch {name}: protected")
        return
    state = cg.merge_state(repo, name, base)
    if state == "unmerged":
        _keep_branch(out, f"keep branch {name}: not merged into {base}")
        return
    wt = next((item for item in linked if item.branch == name), None)
    if wt is not None:
        reason = worktree_reason(wt, cwd)
        if reason is not None:
            _keep_branch(out, f"keep branch {name}: {reason}")
            return
        out.actions.append(Action("worktree", wt.path,
                                  f"remove worktree {wt.path} (branch {name})"))
    by = "" if state == "ancestor" else " by content"
    out.actions.append(Action("branch", name,
                              f"delete branch {name} (merged into {base}{by})",
                              needs=wt.path if wt is not None else ""))


def plan_cleanup(repo: Path, owned: Sequence[str], missing: Sequence[str],
                 base: str, cwd: Path) -> Cleanup:
    linked = cs.parse_worktrees(cg.worktree_porcelain(repo))[1:]
    current = cg.current_branch(repo)
    out = Cleanup()
    for name in owned:
        plan_branch(repo, name, base, current, linked, cwd, out)
    for name in missing:
        out.kept.append(f"keep branch {name}: no such local branch")
    owned_set = set(owned)
    for ref in cg.remote_branches(repo):
        if ref.partition("/")[2] in owned_set:
            out.notes.append(f"note remote branch {ref} left as is")
    return out


def add_dir_actions(cleanup: Cleanup, actions: Sequence[Action]) -> None:
    """Append directory actions after the branch actions. A handoff directory is kept while its run still has kept branches, so the gate files stay."""
    for action in actions:
        if action.kind == "directory" and cleanup.branches_kept > 0:
            cleanup.kept.append(f"keep directory {action.target}: "
                                "the run still has kept branches")
        else:
            cleanup.actions.append(action)


def _empty_directory(path: Path) -> Optional[str]:
    """Remove everything inside path and keep path itself."""
    try:
        for child in path.iterdir():
            if child.is_symlink() or not child.is_dir():
                child.unlink()
            else:
                shutil.rmtree(child)
    except OSError as error:
        return str(error)
    return None


def _remove_tree(path: Path) -> Optional[str]:
    try:
        shutil.rmtree(path)
    except OSError as error:
        return str(error)
    return None


def _run_one(repo: Path, action: Action, failed_worktrees: Set[str]) -> Optional[str]:
    if action.kind == "worktree":
        return cg.remove_worktree(repo, action.target)
    if action.kind == "branch":
        if action.needs and action.needs in failed_worktrees:
            return "its worktree was not removed"
        return cg.delete_branch(repo, action.target)
    if action.kind == "directory":
        return _remove_tree(Path(action.target))
    return _empty_directory(Path(action.target))


def run_actions(repo: Path, actions: Sequence[Action]) -> Dict[str, str]:
    """Perform the actions in order; return the failure reason keyed by action text."""
    failures: Dict[str, str] = {}
    failed_worktrees: Set[str] = set()
    for action in actions:
        reason = _run_one(repo, action, failed_worktrees)
        if reason is None:
            continue
        failures[action.text] = reason
        if action.kind == "worktree":
            failed_worktrees.add(action.target)
    return failures


def _apply_lines(cleanup: Cleanup, failures: Dict[str, str]) -> List[str]:
    lines: List[str] = []
    for action in cleanup.actions:
        if action.text in failures:
            lines.append(f"failed: {action.text}: {failures[action.text]}")
        else:
            lines.append(action.text)
    return lines


def _summary(cleanup: Cleanup, applied: bool, failed: int) -> str:
    kept = len(cleanup.kept)
    if not applied:
        return f"mr-clean: dry run: {len(cleanup.actions)} to remove, {kept} kept"
    removed = len(cleanup.actions) - failed
    return f"mr-clean: {removed} removed, {kept} kept, {failed} failed"


def render(cleanup: Cleanup, applied: bool, failures: Dict[str, str]) -> str:
    if applied:
        lines = _apply_lines(cleanup, failures)
    else:
        lines = [DRY_RUN_HEADER] + [action.text for action in cleanup.actions]
    lines += cleanup.kept + cleanup.notes
    lines.append(_summary(cleanup, applied, len(failures)))
    return "\n".join(lines)


def build_cleanup(args: argparse.Namespace, cwd: Path,
                  tempdir: str) -> Tuple[Path, Cleanup]:
    """Check every input and plan the actions; nothing is changed here."""
    start = cwd / args.repo if args.repo else cwd
    repo = cg.main_worktree(start).resolve()
    if not cg.branch_exists(repo, args.base):
        raise UsageError(f"base branch not found: {args.base}")
    owned, missing = owned_branches(args, repo, cwd)
    dirs = dir_actions(args, repo, cwd, tempdir)
    cleanup = plan_cleanup(repo, owned, missing, args.base, cwd)
    add_dir_actions(cleanup, dirs)
    return repo, cleanup


def main(argv: Optional[Sequence[str]] = None, stdout=None, stderr=None,
         cwd: Optional[str] = None, tempdir: Optional[str] = None) -> int:
    out = sys.stdout if stdout is None else stdout
    err = sys.stderr if stderr is None else stderr
    args = build_parser().parse_args(argv)
    here = Path(cwd or os.getcwd()).resolve()
    try:
        repo, cleanup = build_cleanup(args, here, tempdir or tempfile.gettempdir())
    except (UsageError, cg.CleanError) as error:
        print(f"mr-clean: {error}", file=err)
        return EXIT_USAGE
    if not args.apply:
        print(render(cleanup, False, {}), file=out)
        return EXIT_OK
    failures = run_actions(repo, cleanup.actions)
    print(render(cleanup, True, failures), file=out)
    return EXIT_FAIL if failures else EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
