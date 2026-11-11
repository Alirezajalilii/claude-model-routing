"""Git and command adapter for the mr-gate command.

This is the only module that runs git and the plan's shell commands for the
gate. checked_out restores the worktree's branch even when its body raises. It
never stashes, resets or deletes anything, and it refuses a dirty worktree.
"""

import contextlib
import os
import signal
import subprocess
from pathlib import Path
from typing import Iterator, List

from gate_checks import TIMEOUT, CommandResult

OUTPUT_TAIL_LINES = 40


class GitError(Exception):
    """A git command failed, or the worktree is not in a usable state."""


def git(worktree: Path, *args: str) -> str:
    proc = subprocess.run(["git", "-C", str(worktree), *args],
                          capture_output=True, text=True)
    if proc.returncode != 0:
        first = (proc.stderr.strip().splitlines() or [""])[0]
        raise GitError(f"git {' '.join(args)}: {first}")
    return proc.stdout


def resolve(worktree: Path, rev: str) -> str:
    return git(worktree, "rev-parse", "--verify", "--quiet", f"{rev}^{{commit}}").strip()


def merge_base(worktree: Path, a: str, b: str) -> str:
    return git(worktree, "merge-base", a, b).strip()


def commits_since(worktree: Path, base: str) -> List[str]:
    return git(worktree, "rev-list", "--reverse", f"{base}..HEAD").split()


def changed_files(worktree: Path, a: str, b: str) -> List[str]:
    return git(worktree, "diff", "--name-only", "--no-renames", a, b).splitlines()


def commit_files(worktree: Path, sha: str) -> List[str]:
    return git(worktree, "diff-tree", "--no-commit-id", "--name-only", "-r",
               "--root", "--no-renames", sha).splitlines()


def diff_text(worktree: Path, a: str, b: str) -> str:
    return git(worktree, "diff", "--unified=0", "--no-color", "--no-renames", a, b)


def is_clean(worktree: Path) -> bool:
    return git(worktree, "status", "--porcelain", "--untracked-files=no") == ""


def _on_branch(worktree: Path) -> bool:
    try:
        git(worktree, "symbolic-ref", "-q", "HEAD")
    except GitError:
        return False
    return True


def current_ref(worktree: Path) -> str:
    try:
        return git(worktree, "symbolic-ref", "-q", "--short", "HEAD").strip()
    except GitError:
        return git(worktree, "rev-parse", "HEAD").strip()


@contextlib.contextmanager
def checked_out(worktree: Path, rev: str) -> Iterator[None]:
    if not is_clean(worktree):
        raise GitError("worktree has uncommitted changes")
    on_branch = _on_branch(worktree)
    ref = current_ref(worktree)
    git(worktree, "checkout", "--quiet", "--detach", rev)
    try:
        yield
    finally:
        if on_branch:
            git(worktree, "checkout", "--quiet", ref)
        else:
            git(worktree, "checkout", "--quiet", "--detach", ref)


def _tail(output: str) -> str:
    lines = output.splitlines()[-OUTPUT_TAIL_LINES:]
    return "".join(line + "\n" for line in lines)


def _kill_group(proc: "subprocess.Popen[str]") -> None:
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass


def run_command(command: str, cwd: Path, timeout: int) -> CommandResult:
    proc = subprocess.Popen(command, shell=True, cwd=str(cwd), stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, text=True, errors="replace",
                            start_new_session=True)
    try:
        out, _ = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        # Kill the whole group so background children do not hold the pipe open.
        _kill_group(proc)
        out, _ = proc.communicate()
        return CommandResult(command, TIMEOUT,
                             _tail(out) + f"timed out after {timeout} s")
    return CommandResult(command, proc.returncode, _tail(out))
