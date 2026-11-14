"""mr-clean git adapter: the only mr-clean module that runs git. Deletes only through remove_worktree (git worktree remove, never --force) and delete_branch."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import List, Optional

import clean_scope as cs


class CleanError(Exception):
    """A git query failed, or the path is not a git repository."""


def git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    """Run git in repo and return the result; a nonzero exit is not an error here. Output is decoded as UTF-8 with surrogateescape and no newline translation, so any path bytes survive."""
    proc = subprocess.run(["git", "-C", str(repo), *args], capture_output=True)
    return subprocess.CompletedProcess(
        proc.args, proc.returncode,
        proc.stdout.decode("utf-8", "surrogateescape"),
        proc.stderr.decode("utf-8", "surrogateescape"))


def worktree_porcelain(repo: Path) -> str:
    proc = git(repo, "worktree", "list", "--porcelain")
    if proc.returncode != 0:
        raise CleanError(f"not a git repository: {repo}")
    return proc.stdout


def list_worktrees(repo: Path) -> List[cs.Worktree]:
    """Registered worktrees, main first. Uses -z (git 2.36+) so any path survives; falls back to the newline form."""
    proc = git(repo, "worktree", "list", "--porcelain", "-z")
    if proc.returncode == 0:
        return cs.parse_worktrees(proc.stdout, "\0")
    return cs.parse_worktrees(worktree_porcelain(repo))


def main_worktree(start: Path) -> Path:
    worktrees = list_worktrees(start)
    if not worktrees:
        raise CleanError(f"not a git repository: {start}")
    return Path(worktrees[0].path)


def _ref_names(repo: Path, namespace: str, prefix: str) -> List[str]:
    proc = git(repo, "for-each-ref", "--format=%(refname)", namespace)
    if proc.returncode != 0:
        raise CleanError(f"cannot list {namespace} in {repo}")
    return [line.removeprefix(prefix) for line in proc.stdout.split("\n")
            if line.startswith(prefix)]


def local_branches(repo: Path) -> List[str]:
    return _ref_names(repo, "refs/heads", "refs/heads/")


def remote_branches(repo: Path) -> List[str]:
    names = _ref_names(repo, "refs/remotes", "refs/remotes/")
    return [name for name in names if not name.endswith("/HEAD")]


def branch_exists(repo: Path, name: str) -> bool:
    proc = git(repo, "show-ref", "--verify", "--quiet", f"refs/heads/{name}")
    return proc.returncode == 0


def current_branch(repo: Path) -> Optional[str]:
    proc = git(repo, "symbolic-ref", "--quiet", "HEAD")
    if proc.returncode != 0:
        return None
    return proc.stdout.rstrip("\n").removeprefix("refs/heads/")


def _same_tree_after_merge(repo: Path, branch_ref: str, base_ref: str) -> bool:
    """True when merging the branch into the base leaves the base's tree unchanged."""
    merged = git(repo, "merge-tree", "--write-tree", base_ref, branch_ref)
    tree = git(repo, "rev-parse", f"{base_ref}^{{tree}}")
    if merged.returncode != 0 or tree.returncode != 0:
        return False
    first = merged.stdout.splitlines()[:1]
    return bool(first) and first[0].strip() == tree.stdout.strip()


def merge_state(repo: Path, branch: str, base: str) -> str:
    """Return "ancestor", "content" (squash-style merge) or "unmerged"."""
    branch_ref = f"refs/heads/{branch}"
    base_ref = f"refs/heads/{base}"
    ancestor = git(repo, "merge-base", "--is-ancestor", branch_ref, base_ref)
    if ancestor.returncode == 0:
        return "ancestor"
    if ancestor.returncode != 1:
        return "unmerged"
    if _same_tree_after_merge(repo, branch_ref, base_ref):
        return "content"
    return "unmerged"


def worktree_state(worktree: Path) -> str:
    """Return clean, dirty (changes or untracked files), ignored (only git-ignored files) or unknown (git failed). git worktree remove deletes ignored files, so only a clean worktree may be removed."""
    proc = git(worktree, "status", "--porcelain", "-z", "--ignored=matching",
               "--untracked-files=all", "--ignore-submodules=none")
    if proc.returncode != 0:
        return "unknown"
    entries = [entry for entry in proc.stdout.split("\0") if entry]
    if not entries:
        return "clean"
    if all(entry.startswith("!! ") for entry in entries):
        return "ignored"
    return "dirty"


def is_clean(worktree: Path) -> bool:
    return worktree_state(worktree) == "clean"


def is_ignored(repo: Path, rel_path: str) -> bool:
    return git(repo, "check-ignore", "-q", "--", rel_path).returncode == 0


def unignored_files(repo: Path, rel_path: str) -> List[str]:
    """Tracked files and untracked, not-ignored files under rel_path (pathspec taken literally)."""
    proc = git(repo, "--literal-pathspecs", "ls-files", "-z", "--cached",
               "--others", "--exclude-standard", "--", rel_path)
    if proc.returncode != 0:
        raise CleanError(f"cannot list the files in {rel_path}")
    return [name for name in proc.stdout.split("\0") if name]


def _failure(proc: subprocess.CompletedProcess, default: str) -> Optional[str]:
    if proc.returncode == 0:
        return None
    lines = [line.strip() for line in proc.stderr.splitlines() if line.strip()]
    return lines[0] if lines else default


def remove_worktree(repo: Path, path: str) -> Optional[str]:
    return _failure(git(repo, "worktree", "remove", path),
                    "git worktree remove failed")


def delete_branch(repo: Path, name: str) -> Optional[str]:
    return _failure(git(repo, "branch", "-D", name), "git branch -D failed")
