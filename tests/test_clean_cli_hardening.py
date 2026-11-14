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


if __name__ == "__main__":
    unittest.main()
