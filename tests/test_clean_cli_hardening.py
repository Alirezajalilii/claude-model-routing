"""mr-clean CLI tests for the hardening plan (hidden edits, case variants, remote names).

Reuses the fixture of CleanCliTest in tests/test_clean_cli.py without
inheriting its tests, so they do not run twice.
"""

import unittest
from pathlib import Path
from unittest import mock

import test_clean_cli as base
from test_clean_cli import _commit, _git, _listed_path

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

    # TC75
    def test_tc75_remote_name_with_slash_gets_note(self) -> None:
        sha = _git(self.repo, "rev-parse", "agent/s-T1")
        _git(self.repo, "update-ref", "refs/remotes/team/origin/agent/s-T1", sha)
        code, out, _ = self._run("--plan", str(self.plan), "--apply")
        self.assertEqual(code, 0)
        self.assertIn("note remote branch team/origin/agent/s-T1 left as is", out)
        self.assertEqual(
            _git(self.repo, "rev-parse", "refs/remotes/team/origin/agent/s-T1"), sha)

    # TC76
    def test_tc76_similar_remote_names_get_no_note(self) -> None:
        sha = _git(self.repo, "rev-parse", "main")
        _git(self.repo, "update-ref", "refs/remotes/origin/agent/s-T1x", sha)
        _git(self.repo, "update-ref", "refs/remotes/origin/xagent/s-T1", sha)
        code, out, _ = self._run("--plan", str(self.plan))
        self.assertEqual(code, 0)
        self.assertNotIn("note remote branch origin/agent/s-T1x", out)
        self.assertNotIn("note remote branch origin/xagent/s-T1", out)

    # TC86
    def test_tc86_branch_with_case_twin_is_kept(self) -> None:
        _git(self.repo, "checkout", "-q", "-b", "dev", "main")
        _commit(self.repo, {"dev.txt": "d\n"}, "unmerged work on dev")
        dev_sha = _git(self.repo, "rev-parse", "HEAD")
        _git(self.repo, "checkout", "-q", "main")
        _git(self.repo, "pack-refs", "--all")
        _git(self.repo, "branch", "Dev", "main")
        code, out, _ = self._run("--branch", "dev", "--apply")
        self.assertEqual(code, 0)
        self.assertIn("keep branch dev: branch Dev differs only in letter case "
                      "or Unicode form", out)
        self.assertEqual(out.splitlines()[-1], "mr-clean: 0 removed, 1 kept, 0 failed")
        refs = _git(self.repo, "for-each-ref", "--format=%(refname) %(objectname)",
                    "refs/heads").splitlines()
        self.assertIn(f"refs/heads/dev {dev_sha}", refs)
        self.assertTrue(any(line.startswith("refs/heads/Dev ") for line in refs))

    # TC87
    def test_tc87_unicode_form_twin_is_kept(self) -> None:
        nfc = "agent/caf" + chr(0xE9)
        nfd = "agent/cafe" + chr(0x301)
        with mock.patch.object(cli.cg, "local_branches",
                               return_value=["main", nfc, nfd]):
            out = cli.plan_cleanup(self.repo, [nfc], [], "main", self.repo.resolve())
        self.assertEqual(out.kept, [f"keep branch {nfc}: branch {nfd} "
                                    "differs only in letter case or Unicode form"])
        self.assertEqual(out.actions, [])
        self.assertEqual(out.branches_kept, 1)

    # TC89
    def test_tc89_registered_worktree_branch_twin_is_kept(self) -> None:
        listed = [W(str(self.repo), "Agent/other-T1", False, False)]
        with mock.patch.object(cli.cg, "list_worktrees", return_value=listed):
            out = cli.plan_cleanup(self.repo, ["agent/other-T1"], [], "main",
                                   self.repo.resolve())
        self.assertEqual(out.kept, ["keep branch agent/other-T1: branch Agent/other-T1 "
                                    "differs only in letter case or Unicode form"])
        self.assertEqual(out.actions, [])


if __name__ == "__main__":
    unittest.main()
