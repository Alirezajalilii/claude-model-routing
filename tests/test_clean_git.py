"""Tests for the git adapter in scripts/clean_git.py.

Each test builds its own throwaway repositories in temporary directories, so no
test touches the project repository. Repository setup uses subprocess directly
so the setup does not depend on the code under test.
"""

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import clean_git as cg  # noqa: E402
import clean_scope as cs  # noqa: E402

LS = chr(0x2028)  # Unicode LINE SEPARATOR


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


def _init_repo(base: Path) -> None:
    """Create a repository on branch main with one commit (base.txt) at base."""
    base.mkdir()
    _git(base, "init", "-q")
    _git(base, "symbolic-ref", "HEAD", "refs/heads/main")
    _git(base, "config", "user.email", "test@example.com")
    _git(base, "config", "user.name", "Test")
    _git(base, "config", "commit.gpgsign", "false")
    _commit(base, {"base.txt": "b\n"}, "A")


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

    # TC18
    def test_tc18_main_worktree_with_separator_in_repository_path(self) -> None:
        base = self.wt_root / ("r" + LS + "x")
        _init_repo(base)
        wt = self.wt_root / ("w" + LS + "t")
        _git(base, "worktree", "add", "-q", str(wt), "-b", "wt2")
        self.assertEqual(cg.main_worktree(wt).resolve(), base.resolve())
        self.assertEqual(cg.main_worktree(base).resolve(), base.resolve())

    # TC19
    def test_tc19_list_worktrees_parses_nul_separated_output(self) -> None:
        text = ("worktree /r/a\nb\0HEAD aaa\0branch refs/heads/main\0\0"
                "worktree /r/w\0HEAD bbb\0branch refs/heads/agent/s-T1\0\0")

        def fake(repo: Path, *args: str) -> subprocess.CompletedProcess:
            if "-z" in args:
                return subprocess.CompletedProcess(list(args), 0, text, "")
            return subprocess.CompletedProcess(list(args), 1, "", "")

        with mock.patch.object(cg, "git", side_effect=fake):
            result = cg.list_worktrees(Path("/r"))
        self.assertEqual(result, [
            cs.Worktree("/r/a\nb", "main", False, False),
            cs.Worktree("/r/w", "agent/s-T1", False, False),
        ])

    # TC20
    def test_tc20_list_worktrees_falls_back_without_z(self) -> None:
        def fake(repo: Path, *args: str) -> subprocess.CompletedProcess:
            if "-z" in args:
                return subprocess.CompletedProcess(list(args), 129, "",
                                                   "error: unknown switch")
            return subprocess.CompletedProcess(
                list(args), 0, "worktree /r\nHEAD aaa\nbranch refs/heads/main\n\n", "")

        with mock.patch.object(cg, "git", side_effect=fake):
            result = cg.list_worktrees(Path("/r"))
        self.assertEqual(result, [cs.Worktree("/r", "main", False, False)])

    # TC20
    def test_tc20_list_worktrees_raises_when_git_fails(self) -> None:
        def fake(repo: Path, *args: str) -> subprocess.CompletedProcess:
            return subprocess.CompletedProcess(list(args), 128, "", "fatal")

        with mock.patch.object(cg, "git", side_effect=fake):
            with self.assertRaises(cg.CleanError):
                cg.list_worktrees(Path("/r"))

    # TC21
    def test_tc21_list_worktrees_on_real_repository(self) -> None:
        wt = self._add_worktree("wt")
        result = cg.list_worktrees(self.repo)
        self.assertEqual(len(result), 2)
        self.assertEqual(Path(result[0].path).resolve(), self.repo.resolve())
        self.assertEqual(result[1].branch, "wt")
        self.assertEqual(Path(result[1].path).resolve(), wt.resolve())

    # TC22
    def test_tc22_local_branches_keep_names_with_separator(self) -> None:
        _git(self.repo, "branch", "agent/s-T1" + LS + "x")
        self.assertEqual(sorted(cg.local_branches(self.repo)),
                         ["agent/s-T1" + LS + "x", "main"])

    # TC23
    def test_tc23_current_branch_keeps_trailing_separator(self) -> None:
        _git(self.repo, "checkout", "-q", "-b", "agent/s-T1" + LS)
        self.assertEqual(cg.current_branch(self.repo), "agent/s-T1" + LS)

    # TC24
    def test_tc24_worktree_state_classifies_changes(self) -> None:
        _commit(self.repo, {".gitignore": "ignored.txt\n"}, "ignore")
        wt = self._add_worktree("wt")
        self.assertEqual(cg.worktree_state(wt), "clean")
        self.assertTrue(cg.is_clean(wt))
        (wt / "ignored.txt").write_text("ignored\n")
        self.assertEqual(cg.worktree_state(wt), "ignored")
        self.assertFalse(cg.is_clean(wt))
        (wt / "ignored.txt").unlink()
        (wt / "new.txt").write_text("untracked\n")
        self.assertEqual(cg.worktree_state(wt), "dirty")
        (wt / "new.txt").unlink()
        (wt / "base.txt").write_text("edited\n")
        self.assertEqual(cg.worktree_state(wt), "dirty")
        _git(wt, "checkout", "--", "base.txt")
        _git(self.repo, "config", "status.showUntrackedFiles", "no")
        (wt / "new.txt").write_text("untracked\n")
        self.assertEqual(cg.worktree_state(wt), "dirty")
        with tempfile.TemporaryDirectory() as plain:
            self.assertEqual(cg.worktree_state(Path(plain)), "unknown")

    # TC25
    def test_tc25_unignored_files_lists_tracked_and_not_ignored(self) -> None:
        _commit(self.repo, {".gitignore": "docs/handoffs/\n"}, "ignore")
        run = self.repo / "docs" / "handoffs" / "2026-01-01-r"
        run.mkdir(parents=True)
        (run / "a.md").write_text("a\n")
        self.assertEqual(cg.unignored_files(self.repo, "docs/handoffs/2026-01-01-r"), [])
        (run / "t.md").write_text("t\n")
        _git(self.repo, "add", "-f", "docs/handoffs/2026-01-01-r/t.md")
        _git(self.repo, "commit", "-q", "-m", "force")
        self.assertEqual(cg.unignored_files(self.repo, "docs/handoffs/2026-01-01-r"),
                         ["docs/handoffs/2026-01-01-r/t.md"])
        self.assertEqual(cg.unignored_files(self.repo, "docs/handoffs/2026-01-01-*"), [])
        with tempfile.TemporaryDirectory() as plain:
            with self.assertRaises(cg.CleanError):
                cg.unignored_files(Path(plain), "docs")

    # TC26
    def test_tc26_git_output_keeps_undecodable_bytes(self) -> None:
        subprocess.run([b"git", b"-C", os.fsencode(str(self.repo)), b"config",
                        b"x.y", bytes([0xFF])], check=True, capture_output=True)
        proc = cg.git(self.repo, "config", "x.y")
        self.assertEqual(proc.returncode, 0)
        self.assertEqual(proc.stdout, chr(0xDCFF) + "\n")

    # TC46
    def test_tc46_main_worktree_keeps_carriage_return_in_path(self) -> None:
        base = self.wt_root / ("r" + chr(13) + "x")
        _init_repo(base)
        self.assertEqual(str(cg.main_worktree(base).resolve()), str(base.resolve()))

    # TC50
    def test_tc50_assume_unchanged_edit_is_hidden(self) -> None:
        wt = self._add_worktree("wt")
        (wt / "base.txt").write_text("edited\n")
        _git(wt, "update-index", "--assume-unchanged", "base.txt")
        self.assertEqual(cg.worktree_state(wt), "hidden")
        self.assertFalse(cg.is_clean(wt))

    # TC51
    def test_tc51_skip_worktree_edit_is_hidden(self) -> None:
        wt = self._add_worktree("wt")
        (wt / "base.txt").write_text("edited\n")
        _git(wt, "update-index", "--skip-worktree", "base.txt")
        self.assertEqual(cg.worktree_state(wt), "hidden")

    # TC52
    def test_tc52_absent_skip_worktree_file_is_clean(self) -> None:
        wt = self._add_worktree("wt")
        _git(wt, "update-index", "--skip-worktree", "base.txt")
        (wt / "base.txt").unlink()
        self.assertEqual(cg.worktree_state(wt), "clean")

    # TC53
    def test_tc53_unedited_flagged_file_present_is_hidden(self) -> None:
        wt = self._add_worktree("wt")
        _git(wt, "update-index", "--assume-unchanged", "base.txt")
        self.assertEqual(cg.worktree_state(wt), "hidden")

    # TC54
    def test_tc54_ls_files_failure_is_unknown(self) -> None:
        def fake(repo: Path, *args: str) -> subprocess.CompletedProcess:
            if "status" in args:
                return subprocess.CompletedProcess(list(args), 0, "", "")
            return subprocess.CompletedProcess(list(args), 128, "", "fatal")

        with mock.patch.object(cg, "git", side_effect=fake):
            self.assertEqual(cg.worktree_state(Path("/w")), "unknown")

    # TC55
    def test_tc55_status_disables_fsmonitor_and_untracked_cache(self) -> None:
        calls: list = []

        def fake(repo: Path, *args: str) -> subprocess.CompletedProcess:
            calls.append(args)
            return subprocess.CompletedProcess(list(args), 0, "", "")

        with mock.patch.object(cg, "git", side_effect=fake):
            cg.worktree_state(Path("/w"))
        self.assertEqual(calls[0], (
            "-c", "core.fsmonitor=false", "-c", "core.untrackedCache=false",
            "status", "--porcelain", "-z", "--ignored=matching",
            "--untracked-files=all", "--ignore-submodules=none"))

    # TC64
    def test_tc64_icase_pathspec_lists_tracked_file_under_a_case_variant(self) -> None:
        _commit(self.repo, {".gitignore": "docs/handoffs/\n"}, "ignore")
        run = self.repo / "docs" / "handoffs" / "2026-01-01-r"
        run.mkdir(parents=True)
        (run / "t.md").write_text("t\n")
        _git(self.repo, "add", "-f", "docs/handoffs/2026-01-01-r/t.md")
        _git(self.repo, "commit", "-q", "-m", "force")
        self.assertEqual(cg.unignored_files(self.repo, "docs/HANDOFFS/2026-01-01-r"),
                         ["docs/handoffs/2026-01-01-r/t.md"])
        ci = (self.repo / "DOCS" / "HANDOFFS").is_dir()
        free = self.repo / "free" / "2026-01-01-q"
        free.mkdir(parents=True)
        (free / "u.txt").write_text("u\n")
        if ci:
            self.assertEqual(
                [name.lower() for name in cg.unignored_files(self.repo, "FREE/2026-01-01-Q")],
                ["free/2026-01-01-q/u.txt"])
        else:
            self.assertEqual(cg.unignored_files(self.repo, "free/2026-01-01-q"),
                             ["free/2026-01-01-q/u.txt"])


if __name__ == "__main__":
    unittest.main()
