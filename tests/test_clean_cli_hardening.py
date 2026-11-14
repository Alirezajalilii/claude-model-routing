"""mr-clean CLI tests for the hardening plan (hidden edits, case variants, remote names).

Reuses the fixture of CleanCliTest in tests/test_clean_cli.py without
inheriting its tests, so they do not run twice.
"""

import unittest
from pathlib import Path
from unittest import mock

import test_clean_cli as base
from test_clean_cli import _git, _listed_path

cli = base.cli
W = cli.cs.Worktree


class CleanCliHardeningTest(unittest.TestCase):
    """Repository, plan and worktree of CleanCliTest.setUp."""

    setUp = base.CleanCliTest.setUp
    _tempdir = base.CleanCliTest._tempdir
    _run = base.CleanCliTest._run
    _branches = base.CleanCliTest._branches

    # TC56
    def test_tc56_hidden_edit_keeps_worktree_at_planning(self) -> None:
        (self.wt_path / "t1.txt").write_text("edited\n")
        _git(self.wt_path, "update-index", "--assume-unchanged", "t1.txt")
        code, out, _ = self._run("--plan", str(self.plan), "--apply")
        self.assertEqual(code, 0)
        self.assertIn(f"keep branch agent/s-T1: worktree {self.wt_listed} "
                      "holds files marked assume-unchanged or skip-worktree", out)
        self.assertEqual((self.wt_path / "t1.txt").read_text(), "edited\n")
        self.assertIn("agent/s-T1", self._branches())

    # TC57
    def test_tc57_hidden_edit_is_rechecked_before_removal(self) -> None:
        (self.wt_path / "t1.txt").write_text("edited\n")
        _git(self.wt_path, "update-index", "--assume-unchanged", "t1.txt")
        text = f"remove worktree {self.wt_listed} (branch agent/s-T1)"
        failures = cli.run_actions(
            self.repo, [cli.Action("worktree", self.wt_listed, text)])
        self.assertEqual(failures[text],
                         f"since the check, worktree {self.wt_listed} "
                         "holds files marked assume-unchanged or skip-worktree")
        self.assertEqual((self.wt_path / "t1.txt").read_text(), "edited\n")

    # TC65
    def test_tc65_containment_checks_delegate_to_path_within(self) -> None:
        with mock.patch.object(cli.cs, "path_within", return_value=True):
            self.assertTrue(cli._overlaps(Path("/a"), Path("/b")))
            self.assertEqual(
                cli.worktree_reason(W("/w", "b", False, False), Path("/c")),
                "worktree /w contains the current directory")
            self.assertEqual(
                cli._nested_worktree(W("/w", "b", False, False),
                                     [W("/x", None, False, False)]),
                "worktree /w holds the worktree /x")
            with self.assertRaises(cli.UsageError) as caught:
                cli._guard_scratch(cli.Action("scratch", "/s", "empty directory /s"),
                                   self.repo, cli.Cleanup(), Path("/c"))
            self.assertEqual(str(caught.exception),
                             "refused --scratch: /s holds the current directory /c")

    # TC66
    def test_tc66_case_variant_worktree_holds_current_directory(self) -> None:
        _git(self.repo, "worktree", "remove", str(self.wt_path))
        base_dir = self._tempdir()
        (base_dir / "wt").mkdir()
        ci = (base_dir / "WT").is_dir()
        _git(self.repo, "worktree", "add", "-q", str(base_dir / "WT"), "agent/s-T1")
        listed = _listed_path(self.repo, "agent/s-T1")
        code, out, _ = self._run("--plan", str(self.plan), "--repo", str(self.repo),
                                 "--apply", cwd=base_dir / "wt")
        self.assertEqual(code, 0)
        if ci:
            self.assertIn(f"keep branch agent/s-T1: worktree {listed} "
                          "contains the current directory", out)
            self.assertTrue((base_dir / "wt").is_dir())
        else:
            self.assertIn(f"remove worktree {listed} (branch agent/s-T1)", out)

    # TC67
    def test_tc67_case_variant_worktree_inside_scratch_is_kept(self) -> None:
        scratch = self.tempdir / "a" / "b" / "c"
        scratch.mkdir(parents=True)
        ci = (self.tempdir / "A").is_dir()
        wt2 = self.tempdir / "A" / "B" / "C" / "wt2"
        _git(self.repo, "worktree", "add", "-q", str(wt2), "agent/s-T2")
        (wt2 / "u.txt").write_text("u\n")
        code, out, err = self._run("--repo", str(self.repo), "--scratch", str(scratch),
                                   "--apply")
        self.assertTrue((wt2 / "u.txt").exists())
        if ci:
            self.assertEqual(code, 2)
            self.assertEqual(out, "")
            self.assertTrue(err.startswith("mr-clean: refused --scratch:"), err)
            self.assertIn("overlaps the worktree", err)
        else:
            self.assertEqual(code, 0)

    # TC68
    def test_tc68_case_variant_current_directory_inside_scratch_is_kept(self) -> None:
        scratch = self.tempdir / "a" / "b" / "c"
        sub = scratch / "sub"
        sub.mkdir(parents=True)
        ci = (self.tempdir / "A").is_dir()
        code, out, err = self._run("--repo", str(self.repo), "--scratch", str(scratch),
                                   "--apply",
                                   cwd=self.tempdir / "A" / "B" / "C" / "sub")
        if ci:
            self.assertEqual(code, 2)
            self.assertIn("holds the current directory", err)
            self.assertTrue(sub.is_dir())
        else:
            self.assertEqual(code, 0)
            self.assertEqual(list(scratch.iterdir()), [])

    # TC69
    def test_tc69_scratch_equal_to_current_directory_is_emptied(self) -> None:
        scratch = self.tempdir / "a" / "b" / "c"
        scratch.mkdir(parents=True)
        (scratch / "f.txt").write_text("f\n")
        code, _, err = self._run("--repo", str(self.repo), "--scratch", str(scratch),
                                 "--apply", cwd=scratch)
        self.assertEqual(code, 0, err)
        self.assertTrue(scratch.is_dir())
        self.assertEqual(list(scratch.iterdir()), [])

    # TC70
    def test_tc70_base_must_be_an_exact_local_branch_name(self) -> None:
        with mock.patch.object(cli.cg, "branch_exists", return_value=True):
            code, out, err = self._run("--base", "nope", "--branch", "agent/other-T1",
                                       "--apply")
        self.assertEqual(code, 2)
        self.assertEqual(out, "")
        self.assertTrue(err.startswith("mr-clean: base branch not found: nope"), err)
        self.assertIn("agent/other-T1", self._branches())
        _git(self.repo, "branch", "dev", "main")
        code, out, err = self._run("--base", "DEV", "--branch", "dev", "--apply")
        self.assertEqual(code, 2)
        self.assertTrue(err.startswith("mr-clean: base branch not found: DEV"), err)
        self.assertIn("dev", self._branches())


if __name__ == "__main__":
    unittest.main()
