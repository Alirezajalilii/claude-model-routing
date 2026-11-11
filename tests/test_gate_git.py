"""Tests for the git and command adapter in scripts/gate_git.py.

Each test builds its own throwaway repository in a temporary directory, so no
test touches the project repository. Repository setup uses subprocess directly
so the setup does not depend on the code under test.
"""

import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import gate_checks as gc  # noqa: E402
import gate_git as gg  # noqa: E402


def _git(worktree: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(worktree), *args], check=True,
                   capture_output=True, text=True)


def _sha(worktree: Path, rev: str = "HEAD") -> str:
    out = subprocess.run(["git", "-C", str(worktree), "rev-parse", rev],
                         check=True, capture_output=True, text=True)
    return out.stdout.strip()


def _commit(worktree: Path, files: dict, message: str) -> str:
    for name, text in files.items():
        path = worktree / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    _git(worktree, "add", "--", *files)
    _git(worktree, "commit", "-q", "-m", message)
    return _sha(worktree)


class GateGitTest(unittest.TestCase):
    """Repository: commits A (base.txt), B (tests/t.txt holds TC1), C
    (edits base.txt, adds impl.txt), all on branch `work`."""

    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.wt = Path(tmp.name)
        _git(self.wt, "init", "-q")
        _git(self.wt, "symbolic-ref", "HEAD", "refs/heads/work")
        _git(self.wt, "config", "user.email", "test@example.com")
        _git(self.wt, "config", "user.name", "Test")
        _git(self.wt, "config", "commit.gpgsign", "false")
        self.a = _commit(self.wt, {"base.txt": "base\n"}, "A")
        self.b = _commit(self.wt, {"tests/t.txt": "TC1\n"}, "B")
        self.c = _commit(self.wt, {"base.txt": "base edited\n",
                                   "impl.txt": "impl\n"}, "C")

    def test_tc1_commits_resolve_and_merge_base(self) -> None:
        self.assertEqual(gg.commits_since(self.wt, self.a), [self.b, self.c])
        self.assertEqual(gg.resolve(self.wt, self.b + "^"), self.a)
        with self.assertRaises(gg.GitError):
            gg.resolve(self.wt, "nope")
        _git(self.wt, "branch", "start", self.a)
        self.assertEqual(gg.merge_base(self.wt, "HEAD", "start"), self.a)

    def test_tc2_changed_and_commit_files(self) -> None:
        self.assertEqual(gg.changed_files(self.wt, self.a, "HEAD"),
                         ["base.txt", "impl.txt", "tests/t.txt"])
        self.assertEqual(gg.commit_files(self.wt, self.b), ["tests/t.txt"])
        self.assertEqual(gg.commit_files(self.wt, self.a), ["base.txt"])

    def test_tc3_diff_text(self) -> None:
        text = gg.diff_text(self.wt, self.a, self.b)
        self.assertIn("+TC1", text)
        self.assertIn("diff --git", text)

    def test_tc4_is_clean_ignores_untracked_files(self) -> None:
        self.assertTrue(gg.is_clean(self.wt))
        (self.wt / "base.txt").write_text("edited\n")
        self.assertFalse(gg.is_clean(self.wt))
        _git(self.wt, "checkout", "--", "base.txt")
        (self.wt / "new.txt").write_text("untracked\n")
        self.assertTrue(gg.is_clean(self.wt))

    def test_tc5_checked_out_restores_branch(self) -> None:
        with gg.checked_out(self.wt, self.b):
            self.assertFalse((self.wt / "impl.txt").exists())
            self.assertEqual(gg.current_ref(self.wt), self.b)
        self.assertEqual(gg.current_ref(self.wt), "work")
        self.assertTrue((self.wt / "impl.txt").exists())

    def test_tc6_exception_propagates_and_branch_restored(self) -> None:
        with self.assertRaises(RuntimeError):
            with gg.checked_out(self.wt, self.b):
                raise RuntimeError("boom")
        self.assertEqual(gg.current_ref(self.wt), "work")

    def test_tc7_dirty_tree_is_refused(self) -> None:
        (self.wt / "base.txt").write_text("dirty\n")
        with self.assertRaises(gg.GitError) as ctx:
            with gg.checked_out(self.wt, self.b):
                pass
        self.assertEqual(str(ctx.exception), "worktree has uncommitted changes")
        self.assertEqual(gg.current_ref(self.wt), "work")
        self.assertEqual((self.wt / "base.txt").read_text(), "dirty\n")

    def test_tc8_detached_head_is_restored_detached(self) -> None:
        _git(self.wt, "checkout", "-q", "--detach", self.c)
        with gg.checked_out(self.wt, self.b):
            self.assertEqual(gg.current_ref(self.wt), self.b)
        self.assertEqual(gg.current_ref(self.wt), self.c)
        symbolic = subprocess.run(
            ["git", "-C", str(self.wt), "symbolic-ref", "-q", "HEAD"],
            capture_output=True, text=True)
        self.assertNotEqual(symbolic.returncode, 0)

    def test_tc9_run_command_codes_and_tail(self) -> None:
        ok = gg.run_command("test -f base.txt", self.wt, 30)
        self.assertEqual(ok.code, 0)
        failed = gg.run_command("echo out; echo err 1>&2; exit 3", self.wt, 30)
        self.assertEqual(failed.code, 3)
        self.assertIn("out", failed.tail)
        self.assertIn("err", failed.tail)
        many = gg.run_command(
            "i=1; while [ $i -le 100 ]; do echo line$i; i=$((i+1)); done",
            self.wt, 30)
        lines = many.tail.splitlines()
        self.assertEqual(len(lines), gg.OUTPUT_TAIL_LINES)
        self.assertEqual(lines[-1], "line100")
        self.assertNotIn("line1", lines)

    def test_tc10_timeout_reports_timeout_code(self) -> None:
        result = gg.run_command("sleep 5", self.wt, 1)
        self.assertEqual(result.code, gc.TIMEOUT)
        self.assertIn("timed out after 1 s", result.tail)

    def test_tc11_background_child_does_not_hold_timeout(self) -> None:
        started = time.monotonic()
        result = gg.run_command("sleep 30 & sleep 30", self.wt, 1)
        elapsed = time.monotonic() - started
        self.assertEqual(result.code, gc.TIMEOUT)
        self.assertLess(elapsed, 10)


if __name__ == "__main__":
    unittest.main()
