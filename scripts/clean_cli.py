"""mr-clean: remove what one mr run created: its local branches merged into the base branch, their clean worktrees, its handoff directory and the session scratchpad's contents. Dry run unless --apply. Every input is checked before anything changes."""

from __future__ import annotations

import argparse
import os
import shutil
import sys
import tempfile
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import AbstractSet, Dict, List, Optional, Pattern, Sequence, Tuple

import clean_git as cg
import clean_scope as cs
from plan_contract import Task, parse_plan

EXIT_OK, EXIT_FAIL, EXIT_USAGE = 0, 1, 2
DESCRIPTION = ("Remove what one mr run created: its local branches merged into the base "
               "branch, their clean worktrees, its handoff directory and the session "
               "scratchpad's contents. Dry run unless --apply.")
DRY_RUN_HEADER = ("mr-clean: dry run; nothing changed. "
                  "Run again with --apply to remove the items below.")
STATE_TEXT = {"dirty": "has uncommitted changes",
              "hidden": "holds files marked assume-unchanged or skip-worktree",
              "ignored": "holds git-ignored files",
              "unknown": "could not be checked"}


class UsageError(Exception):
    """A command-line input is missing, malformed or refused."""


@dataclass(frozen=True)
class Action:
    """One change; kind is worktree, branch, directory or scratch. needs is the worktree a branch depends on; sha and base are a branch's commit and base branch at the check."""

    kind: str
    target: str
    text: str
    needs: str = ""
    sha: str = ""
    base: str = ""


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
                        help=("run directory to remove: named <YYYY-MM-DD>-<topic-slug>, "
                              "git-ignored, inside the repository, holding no tracked file"))
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


def _overlaps(first: Path, second: Path) -> bool:
    """True when one path is the other or lies inside it, by name or by file identity."""
    return cs.path_within(first, second) or cs.path_within(second, first)


def _held_paths(args: argparse.Namespace, repo: Path, cwd: Path) -> List[Path]:
    """Paths a handoff directory may not hold: linked worktrees, the plan file and the current directory."""
    held = [Path(wt.path) for wt in cg.list_worktrees(repo)[1:]]
    if args.plan:
        held.append(cwd / args.plan)
    held.append(cwd)
    return held


def _handoff_action(args: argparse.Namespace, repo: Path, cwd: Path) -> Action:
    path = cwd / args.handoff
    rel = _relative_to_repo(path, repo)
    ignored = rel is not None and cg.is_ignored(repo, rel)
    unignored = cg.unignored_files(repo, rel) if rel else []
    problem = cs.handoff_problem(path, repo, ignored,
                                 _held_paths(args, repo, cwd), unignored)
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
    if cs.path_within(cwd, Path(wt.path)):
        return f"worktree {wt.path} contains the current directory"
    state = cg.worktree_state(Path(wt.path))
    if state != "clean":
        return f"worktree {wt.path} {STATE_TEXT.get(state, STATE_TEXT['unknown'])}"
    return None


def _nested_worktree(wt: cs.Worktree,
                     registered: Sequence[cs.Worktree]) -> Optional[str]:
    """git worktree remove deletes everything below the worktree, git-ignored
    directories and other worktrees in them included; keep it if it holds one."""
    outer = Path(wt.path)
    for other in registered:
        if cs.path_within(Path(other.path), outer, strict=True):
            return f"worktree {wt.path} holds the worktree {other.path}"
    return None


def _keep_branch(out: Cleanup, text: str) -> None:
    out.kept.append(text)
    out.branches_kept += 1


def plan_branch(repo: Path, name: str, base: str, current: Optional[str],
                linked: Sequence[cs.Worktree], cwd: Path, out: Cleanup,
                registered: Sequence[cs.Worktree] = ()) -> None:
    if cs.is_protected(name, base, current):
        _keep_branch(out, f"keep branch {name}: protected")
        return
    state = cg.merge_state(repo, name, base)
    if state == "unmerged":
        _keep_branch(out, f"keep branch {name}: not merged into {base}")
        return
    wt = next((item for item in linked if item.branch == name), None)
    if wt is not None:
        reason = worktree_reason(wt, cwd) or _nested_worktree(wt, registered)
        if reason is not None:
            _keep_branch(out, f"keep branch {name}: {reason}")
            return
        out.actions.append(Action("worktree", wt.path,
                                  f"remove worktree {wt.path} (branch {name})"))
    by = "" if state == "ancestor" else " by content"
    out.actions.append(Action("branch", name,
                              f"delete branch {name} (merged into {base}{by})",
                              needs=wt.path if wt is not None else "",
                              sha=cg.branch_tip(repo, name) or "", base=base))


def plan_cleanup(repo: Path, owned: Sequence[str], missing: Sequence[str],
                 base: str, cwd: Path) -> Cleanup:
    registered = cg.list_worktrees(repo)
    linked = registered[1:]
    current = cg.current_branch(repo)
    out = Cleanup()
    branches = cg.local_branches(repo) + [wt.branch for wt in registered if wt.branch]
    for name in owned:
        twin = _case_twin(name, branches)
        if twin is not None:
            _keep_branch(out, f"keep branch {name}: branch {twin} "
                              "differs only in letter case or Unicode form")
            continue
        plan_branch(repo, name, base, current, linked, cwd, out, registered)
    for name in missing:
        out.kept.append(f"keep branch {name}: no such local branch")
    for ref in cg.remote_branches(repo):
        if any(ref.endswith("/" + name) for name in owned):
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


def _blocked(action: Action, failed: Sequence[Action]) -> Optional[str]:
    """Why an earlier failure forbids this action: a branch whose worktree stayed,
    a handoff directory of a run that still has a branch, or a scratch directory
    that holds a worktree that stayed."""
    failed_worktrees = [item.target for item in failed if item.kind == "worktree"]
    if action.kind == "branch" and action.needs in failed_worktrees:
        return "its worktree was not removed"
    if action.kind == "directory" and failed:
        return "a branch of the run was not removed"
    if action.kind == "scratch":
        target = Path(action.target)
        for path in failed_worktrees:
            if _overlaps(target, Path(path).resolve()):
                return f"it holds the worktree {path}, which was not removed"
    return None


def _branch_change(repo: Path, action: Action) -> Optional[str]:
    """Re-check a branch right before deleting it: no case twin, same commit,
    still merged into the base, checked out in no worktree and held by no rebase
    or bisect (git branch -D refused those; update-ref -d does not)."""
    name = action.target
    names = cg.local_branches(repo) + [wt.branch for wt in cg.list_worktrees(repo)
                                       if wt.branch]
    twin = _case_twin(name, names)
    if twin is not None:
        return (f"since the check, branch {twin} differs only in letter case "
                f"or Unicode form from {name}")
    if cg.branch_tip(repo, name) != action.sha:
        return f"since the check, branch {name} moved or was deleted"
    if cg.merge_state(repo, name, action.base) == "unmerged":
        return f"since the check, branch {name} is no longer merged into {action.base}"
    for wt in cg.list_worktrees(repo):
        if wt.branch == name:
            return f"since the check, branch {name} is checked out in {wt.path}"
    if any(_fold(held) == _fold(name) for held in cg.branches_in_use(repo)):
        return f"branch {name} is being rebased or bisected in a worktree"
    return None


def _overlapping_worktree(target: Path, repo: Path,
                          skip: AbstractSet[str] = frozenset()) -> Optional[str]:
    """The first present registered worktree, not in skip, that is target,
    lies inside it or holds it."""
    for wt in cg.list_worktrees(repo):
        if not wt.prunable and wt.path not in skip and _overlaps(target, Path(wt.path)):
            return wt.path
    return None


def _directory_change(repo: Path, target: Path) -> Optional[str]:
    """Re-check a handoff directory right before removing it."""
    for wt in cg.list_worktrees(repo)[1:]:
        if not wt.prunable and cs.path_within(Path(wt.path), target):
            return f"since the check, it holds the worktree {wt.path}"
    rel = _relative_to_repo(target, repo)
    files = cg.unignored_files(repo, rel) if rel else []
    if files:
        return ("since the check, it holds files that are tracked or not "
                f"git-ignored: {files[0]}")
    return None


def _run_one(repo: Path, action: Action) -> Optional[str]:
    if action.kind == "worktree":
        state = cg.worktree_state(Path(action.target))
        if state != "clean":
            return (f"since the check, worktree {action.target} "
                    f"{STATE_TEXT.get(state, STATE_TEXT['unknown'])}")
        return cg.remove_worktree(repo, action.target)
    if action.kind == "branch":
        return _branch_change(repo, action) or cg.delete_branch_at(
            repo, action.target, action.sha)
    target = Path(action.target)
    if action.kind == "directory":
        return _directory_change(repo, target) or _remove_tree(target)
    holder = _overlapping_worktree(target, repo)
    if holder is not None:
        return f"since the check, it overlaps the worktree {holder}"
    return _empty_directory(target)


def run_actions(repo: Path, actions: Sequence[Action]) -> Dict[str, str]:
    """Perform the actions in order; return the failure reason keyed by action text."""
    failures: Dict[str, str] = {}
    failed: List[Action] = []
    for action in actions:
        try:
            reason = _blocked(action, failed) or _run_one(repo, action)
        except cg.CleanError as error:
            reason = str(error)
        if reason is None:
            continue
        failures[action.text] = reason
        if action.kind in ("worktree", "branch"):
            failed.append(action)
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


def _guard_scratch(action: Action, repo: Path, cleanup: Cleanup, cwd: Path) -> None:
    """Refuse a scratch directory whose emptying would delete the current directory,
    or a worktree (the main one included) that this run does not remove, or would
    delete files inside such a worktree."""
    target = Path(action.target)
    if cs.path_within(cwd, target, strict=True):
        raise UsageError(f"refused --scratch: {target} holds the current directory {cwd}")
    removed = {item.target for item in cleanup.actions if item.kind == "worktree"}
    holder = _overlapping_worktree(target, repo, removed)
    if holder is not None:
        raise UsageError(f"refused --scratch: {target} overlaps the worktree {holder}")


def _fold(name: str) -> str:
    """A name as a case- and normalization-insensitive file system compares it."""
    return unicodedata.normalize("NFD", unicodedata.normalize("NFD", name).casefold())


def _case_twin(name: str, names: Sequence[str]) -> Optional[str]:
    """Another branch whose loose ref file such a file system opens for name,
    so git may read that branch when asked for this one."""
    key = _fold(name)
    return next((other for other in names if other != name and _fold(other) == key), None)


def build_cleanup(args: argparse.Namespace, cwd: Path,
                  tempdir: str) -> Tuple[Path, Cleanup]:
    """Check every input and plan the actions; nothing is changed here."""
    start = cwd / args.repo if args.repo else cwd
    repo = cg.main_worktree(start).resolve()
    branches = cg.local_branches(repo)
    if args.base not in branches:
        raise UsageError(f"base branch not found: {args.base}")
    twin = _case_twin(args.base, branches)
    if twin is not None:
        raise UsageError(f"base branch {args.base} is ambiguous: branch {twin} "
                         "differs only in letter case or Unicode form")
    owned, missing = owned_branches(args, repo, cwd)
    dirs = dir_actions(args, repo, cwd, tempdir)
    cleanup = plan_cleanup(repo, owned, missing, args.base, cwd)
    for action in dirs:
        if action.kind == "scratch":
            _guard_scratch(action, repo, cleanup, cwd)
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
