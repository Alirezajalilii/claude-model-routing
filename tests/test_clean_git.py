"""Tests for the git adapter in scripts/clean_git.py.

Each test builds its own throwaway repositories in temporary directories, so no
test touches the project repository. Repository setup uses subprocess directly
so the setup does not depend on the code under test.
"""

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import clean_git as cg  # noqa: E402


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True,
                   capture_output=True, text=True)


def _sha(repo: Path, rev: str = "HEAD") -> str:
    out = subprocess.run(["git", "-C", str(repo), "rev-parse", rev],
                         check=True, capture_output=True, text=True)
    return out.stdout.strip()


def _commit(repo: Path, files: dict, message: str) -> str:
    for name, text in files.items():
        path = repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    _git(repo, "add", "--", *files)
    _git(repo, "commit", "-q", "-m", message)
    return _sha(repo)


def _branch_commit(repo: Path, name: str, start: str, files: dict,
                   message: str) -> str:
    """Commit files on a new branch `name` that starts at `start`, then return to main."""
    _git(repo, "checkout", "-q", "-B", name, start)
    sha = _commit(repo, files, message)
    _git(repo, "checkout", "-q", "main")
    return sha


def _worktree_count(repo: Path) -> int:
    return sum(1 for line in cg.worktree_porcelain(repo).splitlines()
               if line.startswith("worktree "))


class CleanGitTest(unittest.TestCase):
    """Repository on branch main with one initial commit (base.txt)."""

    def setUp(self) -> None:
        repo_dir = tempfile.TemporaryDirectory()
        self.addCleanup(repo_dir.cleanup)
        self.repo = Path(repo_dir.name)
        _git(self.repo, "init", "-q")
        _git(self.repo, "symbolic-ref", "HEAD", "refs/heads/main")
        _git(self.repo, "config", "user.email", "test@example.com")
        _git(self.repo, "config", "user.name", "Test")
        _git(self.repo, "config", "commit.gpgsign", "false")
        self.first = _commit(self.repo, {"base.txt": "base\n"}, "A")
        wt_dir = tempfile.TemporaryDirectory()
        self.addCleanup(wt_dir.cleanup)
        self.wt_root = Path(wt_dir.name)

    def _add_worktree(self, branch: str) -> Path:
        """Add a linked worktree on a new branch `branch` outside the repository."""
        path = self.wt_root / branch
        _git(self.repo, "worktree", "add", "-q", str(path), "-b", branch)
        return path

    # TC1
    def test_local_branches_lists_only_branch_refs(self) -> None:
        _git(self.repo, "branch", "agent/s-T1")
        _git(self.repo, "tag", "v1")
        _git(self.repo, "update-ref", "refs/remotes/origin/x", "HEAD")
        self.assertEqual(sorted(cg.local_branches(self.repo)),
                         ["agent/s-T1", "main"])

    # TC2
    def test_remote_branches_leave_out_origin_head(self) -> None:
        _git(self.repo, "update-ref", "refs/remotes/origin/x", "HEAD")
        _git(self.repo, "symbolic-ref", "refs/remotes/origin/HEAD",
             "refs/remotes/origin/x")
        self.assertEqual(cg.remote_branches(self.repo), ["origin/x"])

    # TC3
    def test_merge_state_ancestor_unmerged_and_missing(self) -> None:
        _commit(self.repo, {"main.txt": "m\n"}, "B")
        _git(self.repo, "branch", "a", self.first)
        _branch_commit(self.repo, "b", "main", {"b.txt": "b\n"}, "X")
        self.assertEqual(cg.merge_state(self.repo, "a", "main"), "ancestor")
        self.assertEqual(cg.merge_state(self.repo, "b", "main"), "unmerged")
        self.assertEqual(cg.merge_state(self.repo, "nope", "main"), "unmerged")

    # TC3
    def test_merge_state_squash_merged_is_content(self) -> None:
        probe = subprocess.run(
            ["git", "-C", str(self.repo), "merge-tree", "--write-tree", "HEAD", "HEAD"],
            capture_output=True, text=True)
        supported = not (probe.returncode == 129 or "usage" in probe.stderr.lower())
        _branch_commit(self.repo, "c", "main", {"c.txt": "x\n"}, "C")
        _commit(self.repo, {"c.txt": "x\n"}, "C squash-merged")
        expected = "content" if supported else "unmerged"
        self.assertEqual(cg.merge_state(self.repo, "c", "main"), expected)

    # TC4
    def test_is_clean_counts_untracked_and_modified_but_not_ignored(self) -> None:
        _commit(self.repo, {".gitignore": "ignored.txt\n"}, "ignore")
        wt = self._add_worktree("wt")
        self.assertTrue(cg.is_clean(wt))
        (wt / "new.txt").write_text("untracked\n")
        self.assertFalse(cg.is_clean(wt))
        (wt / "new.txt").unlink()
        (wt / "base.txt").write_text("edited\n")
        self.assertFalse(cg.is_clean(wt))
        _git(wt, "checkout", "--", "base.txt")
        (wt / "ignored.txt").write_text("ignored\n")
        self.assertTrue(cg.is_clean(wt))

    # TC5
    def test_main_worktree_from_linked_worktree(self) -> None:
        wt = self._add_worktree("wt")
        self.assertEqual(cg.main_worktree(wt).resolve(), self.repo.resolve())
        self.assertEqual(cg.main_worktree(self.repo).resolve(), self.repo.resolve())

    # TC5
    def test_main_worktree_outside_repository_raises(self) -> None:
        with tempfile.TemporaryDirectory() as plain:
            with self.assertRaises(cg.CleanError):
                cg.main_worktree(Path(plain))

    # TC6
    def test_current_branch_on_branch_and_detached(self) -> None:
        self.assertEqual(cg.current_branch(self.repo), "main")
        _git(self.repo, "checkout", "-q", "--detach")
        self.assertIsNone(cg.current_branch(self.repo))

    # TC7
    def test_remove_worktree_clean_returns_none(self) -> None:
        clean = self._add_worktree("clean")
        self.assertIsNone(cg.remove_worktree(self.repo, str(clean)))
        self.assertFalse(clean.exists())
        self.assertEqual(_worktree_count(self.repo), 1)

    # TC7
    def test_remove_worktree_with_untracked_file_is_refused(self) -> None:
        dirty = self._add_worktree("dirty")
        (dirty / "untracked.txt").write_text("x\n")
        reason = cg.remove_worktree(self.repo, str(dirty))
        self.assertTrue(reason)
        self.assertTrue(dirty.exists())
        self.assertEqual(_worktree_count(self.repo), 2)

    # TC8
    def test_delete_branch_not_checked_out(self) -> None:
        _git(self.repo, "branch", "free")
        self.assertIsNone(cg.delete_branch(self.repo, "free"))
        self.assertFalse(cg.branch_exists(self.repo, "free"))

    # TC8
    def test_delete_branch_checked_out_in_worktree_is_refused(self) -> None:
        self._add_worktree("busy")
        reason = cg.delete_branch(self.repo, "busy")
        self.assertTrue(reason)
        self.assertTrue(cg.branch_exists(self.repo, "busy"))

    # TC9
    def test_is_ignored_for_handoff_directory(self) -> None:
        _commit(self.repo, {".gitignore": "docs/handoffs/\n"}, "ignore")
        (self.repo / "docs" / "handoffs" / "run1").mkdir(parents=True)
        (self.repo / "docs" / "handoffs" / "run1" / "out.md").write_text("x\n")
        (self.repo / "docs" / "other").mkdir(parents=True)
        self.assertTrue(cg.is_ignored(self.repo, "docs/handoffs/run1"))
        self.assertFalse(cg.is_ignored(self.repo, "docs/other"))

    # TC10
    def test_branch_exists(self) -> None:
        self.assertTrue(cg.branch_exists(self.repo, "main"))
        self.assertFalse(cg.branch_exists(self.repo, "nope"))


if __name__ == "__main__":
    unittest.main()
