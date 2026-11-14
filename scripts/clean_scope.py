"""mr-clean ownership rules: which branches, worktrees and directories one run may remove. Pure functions: no subprocess, no git, nothing written."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Pattern, Sequence, Tuple

DATE_PREFIX_RE = re.compile(r"^\d{4}-\d{2}-\d{2}-")
PROTECTED = ("main", "master")
MIN_SCRATCH_DEPTH = 3


def plan_slug(plan_path: str) -> str:
    """Return the plan name without directory, date prefix or .md suffix."""
    name = Path(plan_path).name
    if name.endswith(".md"):
        name = name[:-len(".md")]
    return DATE_PREFIX_RE.sub("", name, count=1)


def owned_pattern(slug: str, task_ids: Sequence[str]) -> Pattern[str]:
    """Match the integration branch and the task branches of one plan (fullmatch)."""
    alternatives = ["integration"] + [re.escape(task_id) for task_id in task_ids]
    return re.compile("agent/" + re.escape(slug) + "-(?:"
                      + "|".join(alternatives) + ")(?:-[0-9]+)?")


def select_owned(local: Sequence[str], pattern: Optional[Pattern[str]],
                 explicit: Sequence[str]) -> Tuple[List[str], List[str]]:
    """Split names into owned local branches and explicit names that do not exist."""
    local_set = set(local)
    explicit_set = set(explicit)
    owned = sorted({name for name in local
                    if (pattern is not None and pattern.fullmatch(name))
                    or name in explicit_set})
    missing: List[str] = []
    for name in explicit:
        if name not in local_set and name not in missing:
            missing.append(name)
    return owned, missing


@dataclass(frozen=True)
class Worktree:
    """One entry of `git worktree list --porcelain`."""

    path: str
    branch: Optional[str]
    locked: bool
    prunable: bool


def _worktree_entry(lines: Sequence[str]) -> Optional[Worktree]:
    """Build a Worktree from the lines of one porcelain entry (None without a path)."""
    path: Optional[str] = None
    branch: Optional[str] = None
    locked = False
    prunable = False
    for line in lines:
        if line.startswith("worktree "):
            path = line[len("worktree "):]
        elif line.startswith("branch "):
            branch = line[len("branch "):]
            if branch.startswith("refs/heads/"):
                branch = branch[len("refs/heads/"):]
        elif line == "locked" or line.startswith("locked "):
            locked = True
        elif line == "prunable" or line.startswith("prunable "):
            prunable = True
    if path is None:
        return None
    return Worktree(path, branch, locked, prunable)


def parse_worktrees(porcelain: str) -> List[Worktree]:
    """Parse `git worktree list --porcelain` output; the first entry is the main worktree."""
    entries: List[List[str]] = [[]]
    # git ends porcelain lines with "\n" only; str.splitlines() would also
    # split a worktree path at "\r", "\x1c" or " " and pair a branch
    # with the wrong path.
    for line in porcelain.split("\n"):
        if line.strip():
            entries[-1].append(line)
        else:
            entries.append([])
    parsed = (_worktree_entry(lines) for lines in entries)
    return [worktree for worktree in parsed if worktree is not None]


def temp_roots(tempdir: str) -> List[Path]:
    """Resolved, existing temp directories: the given one, /tmp and /var/tmp."""
    roots: List[Path] = []
    for raw in (tempdir, "/tmp", "/var/tmp"):
        candidate = Path(raw)
        if not candidate.is_dir():
            continue
        resolved = candidate.resolve()
        if resolved not in roots:
            roots.append(resolved)
    return roots


def _missing_or_link_or_file(path: Path) -> Optional[str]:
    """Shared first checks: existence, symbolic link, directory."""
    if not path.exists() and not path.is_symlink():
        return f"{path} does not exist"
    if path.is_symlink():
        return f"{path} is a symbolic link"
    if not path.is_dir():
        return f"{path} is not a directory"
    return None


def scratch_problem(path: Path, roots: Sequence[Path]) -> Optional[str]:
    """Return why a scratch directory may not be emptied, or None when it may."""
    problem = _missing_or_link_or_file(path)
    if problem is not None:
        return problem
    resolved = path.resolve()
    candidates = [root for root in roots if root in resolved.parents]
    if not candidates:
        return f"{path} is not inside a temp directory"
    root = max(candidates, key=lambda candidate: len(candidate.parts))
    if len(resolved.relative_to(root).parts) < MIN_SCRATCH_DEPTH:
        return (f"{path} is less than {MIN_SCRATCH_DEPTH} levels below "
                f"the temp directory {root}")
    return None


def _holds_git_entry(resolved: Path) -> bool:
    """True when a `.git` entry (file or directory) sits anywhere below the directory."""
    for _, dirnames, filenames in os.walk(resolved):
        if ".git" in dirnames or ".git" in filenames:
            return True
    return False


def _git_owned_ancestor(resolved: Path, root: Path) -> Optional[str]:
    """Why a directory strictly inside `root` lies in git metadata or a nested checkout."""
    if any(part.lower() == ".git" for part in resolved.relative_to(root).parts):
        return "is inside a .git directory"
    for ancestor in resolved.parents:
        if ancestor == root:
            break
        if os.path.lexists(ancestor / ".git"):
            return f"is inside the worktree or repository {ancestor}"
    return None


def handoff_problem(path: Path, repo_root: Path, ignored: bool,
                    holds: Sequence[Path]) -> Optional[str]:
    """Return why a handoff directory may not be removed, or None when it may."""
    problem = _missing_or_link_or_file(path)
    if problem is not None:
        return problem
    resolved = path.resolve()
    root = repo_root.resolve()
    if root not in resolved.parents:
        return f"{path} is not inside the repository"
    nested = _git_owned_ancestor(resolved, root)
    if nested is not None:
        return f"{path} {nested}"
    if _holds_git_entry(resolved):
        return f"{path} holds a .git entry"
    for held_path in holds:
        held = held_path.resolve()
        if held == resolved or resolved in held.parents:
            return f"{path} holds {held_path}"
    if not ignored:
        return f"{path} is not git-ignored"
    return None


def is_protected(name: str, base: str, current: Optional[str]) -> bool:
    """True for the base branch, main, master and the main checkout's current branch."""
    return name == base or name in PROTECTED or (current is not None and name == current)
