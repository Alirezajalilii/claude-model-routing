"""Tests for the mr-clean command in scripts/clean_cli.py.

Each test builds its own throwaway repository, plan file and worktrees in
temporary directories, so no test touches the project repository. Setup uses
subprocess directly so it does not depend on the code under test. Nothing here
skips: where git lacks `merge-tree --write-tree`, the merge-by-content case
asserts the fallback (the branch is kept as not merged).
"""

import io
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import List, Optional, Tuple
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import clean_cli as cli  # noqa: E402

PLAN_NAME = "2026-01-01-s.md"
PLAN_TEXT = "### Task T1: one\n### Task T2: two\n"
ALL_BRANCHES = ["agent/other-T1", "agent/s-T1", "agent/s-T2",
                "agent/s-integration", "main"]
LS = chr(0x2028)


def _git(repo: Path, *args: str) -> str:
    proc = subprocess.run(["git", "-C", str(repo), *args], check=True,
                          capture_output=True, text=True)
    return proc.stdout.strip()


def _commit(repo: Path, files: dict, message: str) -> None:
    for name, text in files.items():
        path = repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    _git(repo, "add", "--", *files)
    _git(repo, "commit", "-q", "-m", message)


def _worktree_paths(repo: Path) -> List[str]:
    """Worktree paths as git lists them (raw git, not the code under test)."""
    lines = _git(repo, "worktree", "list", "--porcelain").splitlines()
    return [line[len("worktree "):] for line in lines if line.startswith("worktree ")]


def _listed_path(repo: Path, branch: str) -> str:
    """The path git lists for the worktree checked out on `branch`."""
    for block in _git(repo, "worktree", "list", "--porcelain").split("\n\n"):
        lines = block.splitlines()
        if f"branch refs/heads/{branch}" in lines:
            return next(line[len("worktree "):] for line in lines
                        if line.startswith("worktree "))
    raise AssertionError(f"no worktree on {branch}")


def _exclude(repo: Path, *patterns: str) -> None:
    """Add patterns to the repository's local exclude file (not committed)."""
    info = repo / ".git" / "info"
    info.mkdir(parents=True, exist_ok=True)
    with (info / "exclude").open("a") as handle:
        handle.write("".join(pattern + "\n" for pattern in patterns))


class CleanCliTest(unittest.TestCase):
    """Repository R on main with the fixture of T3 step 1 (plan P is PLAN_NAME)."""

    def setUp(self) -> None:
        self.tempdir = self._tempdir()
        self.repo = self.tempdir / "repo"
        self.repo.mkdir()
        _git(self.repo, "init", "-q")
        _git(self.repo, "symbolic-ref", "HEAD", "refs/heads/main")
        _git(self.repo, "config", "user.email", "test@example.com")
        _git(self.repo, "config", "user.name", "Test")
        _git(self.repo, "config", "commit.gpgsign", "false")
        _commit(self.repo, {".gitignore": "docs/handoffs/\n"}, "initial")
        self.plan = self._tempdir() / PLAN_NAME
        self.plan.write_text(PLAN_TEXT)
        _git(self.repo, "checkout", "-q", "-b", "agent/s-integration", "main")
        _commit(self.repo, {"integration.txt": "i\n"}, "integration")
        _git(self.repo, "checkout", "-q", "-b", "agent/s-T1", "agent/s-integration")
        _commit(self.repo, {"t1.txt": "t1\n"}, "T1")
        _git(self.repo, "checkout", "-q", "main")
        _git(self.repo, "branch", "-f", "agent/s-integration", "agent/s-T1")
        _git(self.repo, "merge", "-q", "--ff-only", "agent/s-integration")
        self.wt_path = self._tempdir() / "w1"
        _git(self.repo, "worktree", "add", "-q", str(self.wt_path), "agent/s-T1")
        self.wt_listed = _listed_path(self.repo, "agent/s-T1")
        _git(self.repo, "checkout", "-q", "-b", "agent/s-T2", "main")
        _commit(self.repo, {"t2.txt": "t2\n"}, "T2")
        _git(self.repo, "checkout", "-q", "main")
        _git(self.repo, "branch", "agent/other-T1", "main")

    def _tempdir(self) -> Path:
        holder = tempfile.TemporaryDirectory()
        self.addCleanup(holder.cleanup)
        return Path(holder.name)

    def _run(self, *args: str, cwd: Optional[Path] = None) -> Tuple[int, str, str]:
        out, err = io.StringIO(), io.StringIO()
        code = cli.main(list(args), stdout=out, stderr=err,
                        cwd=str(cwd or self.repo), tempdir=str(self.tempdir))
        return code, out.getvalue(), err.getvalue()

    def _branches(self) -> List[str]:
        return sorted(_git(self.repo, "for-each-ref", "--format=%(refname:lstrip=2)",
                           "refs/heads").splitlines())

    # TC1
    def test_tc1_dry_run_lists_actions_and_changes_nothing(self) -> None:
        code, out, _ = self._run("--plan", str(self.plan))
        self.assertEqual(code, 0)
        self.assertIn(f"remove worktree {self.wt_listed} (branch agent/s-T1)", out)
        self.assertIn("delete branch agent/s-T1 (merged into main)", out)
        self.assertIn("delete branch agent/s-integration (merged into main)", out)
        self.assertIn("keep branch agent/s-T2: not merged into main", out)
        self.assertNotIn("agent/other-T1", out)
        self.assertEqual(out.splitlines()[-1], "mr-clean: dry run: 3 to remove, 1 kept")
        self.assertEqual(self._branches(), ALL_BRANCHES)
        self.assertTrue(self.wt_path.is_dir())

    # TC2
    def test_tc2_apply_removes_merged_worktree_and_branches(self) -> None:
        code, out, _ = self._run("--plan", str(self.plan), "--apply")
        self.assertEqual(code, 0)
        self.assertFalse(self.wt_path.exists())
        self.assertNotIn(self.wt_listed, _worktree_paths(self.repo))
        self.assertEqual(self._branches(),
                         ["agent/other-T1", "agent/s-T2", "main"])
        self.assertEqual(out.splitlines()[-1], "mr-clean: 3 removed, 1 kept, 0 failed")

    # TC3
    def test_tc3_uncommitted_changes_keep_worktree_and_branch(self) -> None:
        (self.wt_path / "untracked.txt").write_text("x\n")
        code, out, _ = self._run("--plan", str(self.plan), "--apply")
        self.assertEqual(code, 0)
        self.assertIn(f"keep branch agent/s-T1: worktree {self.wt_listed} "
                      "has uncommitted changes", out)
        self.assertTrue(self.wt_path.is_dir())
        self.assertIn("agent/s-T1", self._branches())
        self.assertNotIn("agent/s-integration", self._branches())

    # TC4
    def test_tc4_locked_worktree_keeps_worktree_and_branch(self) -> None:
        _git(self.repo, "worktree", "lock", str(self.wt_path))
        code, out, _ = self._run("--plan", str(self.plan), "--apply")
        self.assertEqual(code, 0)
        self.assertIn(f"keep branch agent/s-T1: worktree {self.wt_listed} is locked", out)
        self.assertTrue(self.wt_path.is_dir())
        self.assertIn("agent/s-T1", self._branches())

    # TC5
    def test_tc5_worktree_holding_current_directory_is_kept(self) -> None:
        code, out, _ = self._run("--plan", str(self.plan), "--repo", str(self.repo),
                                 "--apply", cwd=self.wt_path)
        self.assertEqual(code, 0)
        self.assertIn(f"keep branch agent/s-T1: worktree {self.wt_listed} "
                      "contains the current directory", out)
        self.assertTrue(self.wt_path.is_dir())
        self.assertIn("agent/s-T1", self._branches())

    # TC6
    def test_tc6_explicit_branches_without_plan(self) -> None:
        code, out, _ = self._run("--branch", "agent/other-T1", "--branch", "nope",
                                 "--apply")
        self.assertEqual(code, 0)
        self.assertIn("keep branch nope: no such local branch", out)
        self.assertNotIn("agent/other-T1", self._branches())
        self.assertIn("agent/s-T1", self._branches())

    # TC7
    def test_tc7_default_protected_branches_are_kept(self) -> None:
        _git(self.repo, "branch", "master", "main")
        for name in ("main", "master"):
            with self.subTest(branch=name):
                code, out, _ = self._run("--branch", name, "--apply")
                self.assertEqual(code, 0)
                self.assertIn(f"keep branch {name}: protected", out)
                self.assertIn(name, self._branches())

    # TC7
    def test_tc7_base_branch_is_protected(self) -> None:
        _git(self.repo, "branch", "dev", "main")
        code, out, _ = self._run("--base", "dev", "--branch", "dev", "--apply")
        self.assertEqual(code, 0)
        self.assertIn("keep branch dev: protected", out)
        self.assertIn("dev", self._branches())

    # TC8
    def test_tc8_handoff_directory_dry_run_then_apply(self) -> None:
        run1 = self.repo / "docs" / "handoffs" / "2026-01-01-run1"
        run1.mkdir(parents=True)
        (run1 / "out.md").write_text("x\n")
        code, out, _ = self._run("--handoff", str(run1))
        self.assertEqual(code, 0)
        self.assertIn(f"remove directory {run1.resolve()}", out)
        self.assertTrue(run1.is_dir())
        code, _, _ = self._run("--handoff", str(run1), "--apply")
        self.assertEqual(code, 0)
        self.assertFalse(run1.exists())

    # TC8
    def test_tc8_handoff_not_git_ignored_is_refused(self) -> None:
        notes = self.repo / "docs" / "notes"
        notes.mkdir(parents=True)
        (notes / "n.md").write_text("x\n")
        before = self._branches()
        code, out, err = self._run("--plan", str(self.plan), "--handoff", str(notes),
                                   "--apply")
        self.assertEqual(code, 2)
        self.assertTrue(err.startswith("mr-clean: refused --handoff:"), err)
        self.assertEqual(out, "")
        self.assertEqual(self._branches(), before)
        self.assertTrue(self.wt_path.is_dir())
        self.assertTrue(notes.is_dir())

    # TC9
    def test_tc9_scratch_contents_are_emptied_and_directory_kept(self) -> None:
        scratch = self.tempdir / "a" / "b" / "c"
        (scratch / "sub").mkdir(parents=True)
        (scratch / "file.txt").write_text("x\n")
        (scratch / "sub" / "inner.txt").write_text("y\n")
        code, _, err = self._run("--scratch", str(scratch), "--apply")
        self.assertEqual(code, 0, err)
        self.assertTrue(scratch.is_dir())
        self.assertEqual(list(scratch.iterdir()), [])

    # TC9
    def test_tc9_shallow_scratch_directory_is_refused(self) -> None:
        shallow = self.tempdir / "a"
        shallow.mkdir()
        (shallow / "keep.txt").write_text("x\n")
        before = self._branches()
        code, out, err = self._run("--plan", str(self.plan), "--scratch", str(shallow),
                                   "--apply")
        self.assertEqual(code, 2)
        self.assertTrue(err.startswith("mr-clean: refused --scratch:"), err)
        self.assertEqual(out, "")
        self.assertTrue((shallow / "keep.txt").exists())
        self.assertEqual(self._branches(), before)
        self.assertTrue(self.wt_path.is_dir())

    # TC10
    def test_tc10_bad_inputs_exit_2_and_change_nothing(self) -> None:
        plain = self._tempdir()
        no_tasks = self._tempdir() / "empty.md"
        no_tasks.write_text("# no headings here\n")
        cases = [
            (["--plan", str(self.tempdir / "missing.md")],
             "mr-clean: cannot read plan: "),
            (["--plan", str(no_tasks)], "mr-clean: no tasks found in plan: "),
            (["--plan", str(self.plan), "--repo", str(plain)],
             "mr-clean: not a git repository: "),
            (["--plan", str(self.plan), "--base", "nope"],
             "mr-clean: base branch not found: nope"),
        ]
        before = self._branches()
        for args, message in cases:
            with self.subTest(args=args):
                code, out, err = self._run(*args, "--apply")
                self.assertEqual(code, 2)
                self.assertTrue(err.startswith(message), err)
                self.assertEqual(out, "")
                self.assertEqual(self._branches(), before)
                self.assertTrue(self.wt_path.is_dir())

    # TC11
    def test_tc11_remote_branch_is_noted_and_left_as_is(self) -> None:
        sha = _git(self.repo, "rev-parse", "agent/s-T1")
        _git(self.repo, "update-ref", "refs/remotes/origin/agent/s-T1", sha)
        code, out, _ = self._run("--plan", str(self.plan), "--apply")
        self.assertEqual(code, 0)
        self.assertIn("note remote branch origin/agent/s-T1 left as is", out)
        self.assertEqual(_git(self.repo, "rev-parse", "refs/remotes/origin/agent/s-T1"),
                         sha)

    # TC12
    def test_tc12_branch_merged_by_content_is_deleted(self) -> None:
        # Fallback, not a skip: without merge-tree --write-tree the branch is kept.
        probe = subprocess.run(
            ["git", "-C", str(self.repo), "merge-tree", "--write-tree", "main", "main"],
            capture_output=True, text=True)
        supported = not (probe.returncode == 129 or "usage" in probe.stderr.lower())
        _git(self.repo, "checkout", "-q", "-b", "agent/s-T2-2", "main")
        _commit(self.repo, {"c.txt": "x\n"}, "C")
        _git(self.repo, "checkout", "-q", "main")
        _commit(self.repo, {"c.txt": "x\n"}, "C squash-merged")
        code, out, _ = self._run("--plan", str(self.plan))
        self.assertEqual(code, 0)
        if supported:
            expected = "delete branch agent/s-T2-2 (merged into main by content)"
        else:
            expected = "keep branch agent/s-T2-2: not merged into main"
        self.assertIn(expected, out)

    # TC13
    def test_tc13_missing_worktree_directory_is_kept(self) -> None:
        shutil.rmtree(self.wt_path)
        code, out, _ = self._run("--plan", str(self.plan), "--apply")
        self.assertEqual(code, 0)
        self.assertIn(f"keep branch agent/s-T1: worktree {self.wt_listed} is missing", out)
        self.assertIn("agent/s-T1", self._branches())

    # TC14
    def test_tc14_handoff_kept_while_branches_are_kept(self) -> None:
        run1 = self.repo / "docs" / "handoffs" / "2026-01-01-run1"
        run1.mkdir(parents=True)
        (run1 / "gate.md").write_text("x\n")
        code, out, _ = self._run("--plan", str(self.plan), "--handoff", str(run1),
                                 "--apply")
        self.assertEqual(code, 0)
        self.assertIn(f"keep directory {run1.resolve()}: "
                      "the run still has kept branches", out)
        self.assertTrue(run1.is_dir())
        _git(self.repo, "branch", "-D", "agent/s-T2")
        code, _, _ = self._run("--plan", str(self.plan), "--handoff", str(run1),
                               "--apply")
        self.assertEqual(code, 0)
        self.assertFalse(run1.exists())

    # TC15
    def test_tc15_handoff_holding_a_linked_worktree_is_refused(self) -> None:
        handoffs = self.repo / "docs" / "handoffs"
        run2_wt = handoffs / "run2" / "wt"
        _git(self.repo, "worktree", "add", "-q", "--detach", str(run2_wt))
        before = self._branches()
        code, out, err = self._run("--handoff", str(handoffs), "--apply")
        self.assertEqual(code, 2)
        self.assertTrue(err.startswith("mr-clean: refused --handoff:"), err)
        self.assertEqual(out, "")
        self.assertTrue(run2_wt.is_dir())
        self.assertEqual(self._branches(), before)

    # TC15
    def test_tc15_plan_copy_inside_handoff_is_refused(self) -> None:
        run3 = self.repo / "docs" / "handoffs" / "run3"
        run3.mkdir(parents=True)
        plan_copy = run3 / PLAN_NAME
        plan_copy.write_text(PLAN_TEXT)
        code, out, err = self._run("--plan", str(plan_copy), "--handoff", str(run3),
                                   "--apply")
        self.assertEqual(code, 2)
        self.assertTrue(err.startswith("mr-clean: refused --handoff:"), err)
        self.assertEqual(out, "")
        self.assertTrue(plan_copy.exists())
        self.assertIn("agent/s-T1", self._branches())

    # TC29
    def test_tc29_handoff_refuses_plan_and_agent_directories_without_plan(self) -> None:
        _exclude(self.repo, "docs/plans/", ".agent/")
        plans = self.repo / "docs" / "plans"
        agent = self.repo / ".agent"
        plans.mkdir(parents=True)
        (plans / "2026-01-01-s.md").write_text("x\n")
        agent.mkdir()
        (agent / "notes.md").write_text("x\n")
        for directory in (plans, agent):
            with self.subTest(directory=str(directory)):
                code, out, err = self._run("--branch", "agent/s-T1", "--handoff",
                                           str(directory), "--apply")
                self.assertEqual(code, 2)
                self.assertEqual(out, "")
                self.assertTrue(err.startswith("mr-clean: refused --handoff:"), err)
                self.assertIn("is not a run directory named <YYYY-MM-DD>-<topic-slug>",
                              err)
                self.assertTrue((plans / "2026-01-01-s.md").exists())
                self.assertTrue((agent / "notes.md").exists())
                self.assertEqual(self._branches(), ALL_BRANCHES)
                self.assertTrue(self.wt_path.is_dir())

    # TC30
    def test_tc30_tracked_file_in_an_ignored_run_directory_is_refused(self) -> None:
        run = self.repo / "docs" / "handoffs" / "2026-01-01-run1"
        run.mkdir(parents=True)
        (run / "out.md").write_text("x\n")
        (run / "t.md").write_text("x\n")
        _git(self.repo, "add", "-f", "docs/handoffs/2026-01-01-run1/t.md")
        _git(self.repo, "commit", "-q", "-m", "force")
        code, out, err = self._run("--handoff", str(run), "--apply")
        self.assertEqual(code, 2)
        self.assertEqual(out, "")
        self.assertTrue(err.startswith("mr-clean: refused --handoff:"), err)
        self.assertIn("holds files that are tracked or not git-ignored: "
                      "docs/handoffs/2026-01-01-run1/t.md", err)
        self.assertTrue((run / "t.md").exists())
        self.assertTrue((run / "out.md").exists())

    # TC31
    def test_tc31_dated_project_named_run_directory_is_removed(self) -> None:
        _exclude(self.repo, ".agent/")
        run = self.repo / ".agent" / "runs" / "2026-01-01-x"
        run.mkdir(parents=True)
        (run / "a.md").write_text("x\n")
        code, out, _ = self._run("--handoff", str(run))
        self.assertEqual(code, 0)
        self.assertIn(f"remove directory {run.resolve()}", out)
        self.assertTrue(run.is_dir())
        code, _, err = self._run("--handoff", str(run), "--apply")
        self.assertEqual(code, 0, err)
        self.assertFalse(run.exists())
        self.assertTrue((self.repo / ".agent" / "runs").exists())

    # TC47
    def test_tc47_case_variant_of_a_run_directory_with_tracked_file_is_refused(self) -> None:
        run = self.repo / "docs" / "handoffs" / "2026-01-01-run1"
        run.mkdir(parents=True)
        (run / "out.md").write_text("x\n")
        (run / "t.md").write_text("x\n")
        _git(self.repo, "add", "-f", "docs/handoffs/2026-01-01-run1/t.md")
        _git(self.repo, "commit", "-q", "-m", "force")
        variant = self.repo / "docs" / "HANDOFFS" / "2026-01-01-run1"
        code, out, err = self._run("--handoff", str(variant), "--apply")
        self.assertEqual(code, 2)
        self.assertEqual(out, "")
        self.assertTrue(err.startswith("mr-clean: refused --handoff:"), err)
        self.assertTrue((run / "t.md").exists())
        self.assertTrue((run / "out.md").exists())
        if variant.is_dir():
            self.assertIn("holds files that are tracked or not git-ignored:", err)
        else:
            self.assertIn("does not exist", err)

    # TC49
    def test_tc49_handoff_help_names_the_run_directory_rule(self) -> None:
        with mock.patch.dict(os.environ, {"COLUMNS": "200"}):
            help_text = cli.build_parser().format_help()
        text = " ".join(help_text.split())
        self.assertIn("run directory to remove: named <YYYY-MM-DD>-<topic-slug>, "
                      "git-ignored, inside the repository, holding no tracked file", text)

    # TC32
    def test_tc32_ignored_file_in_task_worktree_keeps_it(self) -> None:
        ignored = self.wt_path / "docs" / "handoffs" / "2026-01-01-run1" / "exec-T1.md"
        ignored.parent.mkdir(parents=True)
        ignored.write_text("x\n")
        code, out, _ = self._run("--plan", str(self.plan), "--apply")
        self.assertEqual(code, 0)
        self.assertIn(f"keep branch agent/s-T1: worktree {self.wt_listed} "
                      "holds git-ignored files", out)
        self.assertTrue(ignored.exists())
        self.assertIn("agent/s-T1", self._branches())

    # TC33
    def test_tc33_worktree_with_ignored_file_is_rechecked_before_removal(self) -> None:
        ignored = self.wt_path / "docs" / "handoffs" / "2026-01-01-run1" / "exec-T1.md"
        ignored.parent.mkdir(parents=True)
        ignored.write_text("x\n")
        text = f"remove worktree {self.wt_listed} (branch agent/s-T1)"
        failures = cli.run_actions(self.repo, [cli.Action("worktree", self.wt_listed, text)])
        self.assertEqual(failures[text],
                         f"since the check, worktree {self.wt_listed} holds git-ignored files")
        self.assertTrue(ignored.exists())
        self.assertTrue(self.wt_path.is_dir())

    # TC34
    def test_tc34_worktree_and_repository_paths_with_line_separator_are_removed(self) -> None:
        base = self._tempdir() / ("r" + LS + "x")
        base.mkdir()
        _git(base, "init", "-q")
        _git(base, "symbolic-ref", "HEAD", "refs/heads/main")
        _git(base, "config", "user.email", "test@example.com")
        _git(base, "config", "user.name", "Test")
        _git(base, "config", "commit.gpgsign", "false")
        _commit(base, {"a.txt": "a\n"}, "A")
        _git(base, "branch", "agent/s-T1")
        wt = self._tempdir() / ("w" + LS + "t")
        _git(base, "worktree", "add", "-q", str(wt), "agent/s-T1")
        code, out, _ = self._run("--branch", "agent/s-T1", "--apply", cwd=base)
        self.assertEqual(code, 0)
        self.assertFalse(wt.exists())
        self.assertEqual(_git(base, "branch", "--list", "agent/s-T1"), "")
        self.assertEqual(out.splitlines()[-1], "mr-clean: 2 removed, 0 kept, 0 failed")

    # TC35
    def test_tc35_scratch_holding_a_kept_worktree_is_refused(self) -> None:
        scratch = self.tempdir / "a" / "b" / "c"
        scratch.mkdir(parents=True)
        _git(self.repo, "worktree", "add", "-q", str(scratch / "wt2"), "agent/s-T2")
        (scratch / "wt2" / "u.txt").write_text("x\n")
        before = self._branches()
        code, out, err = self._run("--plan", str(self.plan), "--scratch", str(scratch),
                                   "--apply")
        self.assertEqual(code, 2)
        self.assertEqual(out, "")
        self.assertTrue(err.startswith("mr-clean: refused --scratch:"), err)
        self.assertIn("overlaps the worktree", err)
        self.assertTrue((scratch / "wt2" / "u.txt").exists())
        self.assertEqual(self._branches(), before)

    # TC36
    def test_tc36_scratch_equal_to_a_repository_is_refused(self) -> None:
        r = self.tempdir / "x" / "y" / "r"
        r.mkdir(parents=True)
        _git(r, "init", "-q")
        _git(r, "symbolic-ref", "HEAD", "refs/heads/main")
        _git(r, "config", "user.email", "test@example.com")
        _git(r, "config", "user.name", "Test")
        _git(r, "config", "commit.gpgsign", "false")
        _commit(r, {"a.txt": "a\n"}, "A")
        code, _, err = self._run("--repo", str(r), "--scratch", str(r), "--apply")
        self.assertEqual(code, 2)
        self.assertTrue(err.startswith("mr-clean: refused --scratch:"), err)
        self.assertIn("overlaps the worktree", err)
        self.assertTrue((r / ".git").is_dir())
        self.assertTrue((r / "a.txt").exists())

    # TC37
    def test_tc37_scratch_holding_the_current_directory_is_refused(self) -> None:
        scratch = self.tempdir / "a" / "b" / "c"
        sub = scratch / "sub"
        sub.mkdir(parents=True)
        code, _, err = self._run("--repo", str(self.repo), "--scratch", str(scratch),
                                 "--apply", cwd=sub)
        self.assertEqual(code, 2)
        self.assertIn("holds the current directory", err)
        self.assertTrue(sub.is_dir())

    # TC38
    def test_tc38_handoff_holding_the_current_directory_is_refused(self) -> None:
        run = self.repo / "docs" / "handoffs" / "2026-01-01-run1"
        sub = run / "sub"
        sub.mkdir(parents=True)
        code, _, err = self._run("--repo", str(self.repo), "--handoff", str(run),
                                 "--apply", cwd=sub)
        self.assertEqual(code, 2)
        self.assertTrue(err.startswith("mr-clean: refused --handoff:"), err)
        self.assertIn(" holds ", err)
        self.assertTrue(sub.is_dir())

    # TC39
    def test_tc39_worktree_holding_a_nested_worktree_is_kept(self) -> None:
        _git(self.repo, "worktree", "add", "-q", str(self.wt_path / "nested"), "agent/s-T2")
        (self.wt_path / "nested" / "n.txt").write_text("x\n")
        code, out, _ = self._run("--plan", str(self.plan), "--apply")
        self.assertEqual(code, 0)
        self.assertIn("keep branch agent/s-T1: worktree ", out)
        self.assertTrue((self.wt_path / "nested" / "n.txt").exists())
        self.assertIn("agent/s-T1", self._branches())
        self.assertIn("agent/s-T2", self._branches())

    # TC40
    def test_tc40_later_actions_are_blocked_after_a_failed_worktree_action(self) -> None:
        scratch = self.tempdir / "a" / "b" / "c"
        scratch.mkdir(parents=True)
        (scratch / "f.txt").write_text("x\n")
        ghost = scratch / "wt"
        run = self.repo / "docs" / "handoffs" / "2026-01-01-run1"
        run.mkdir(parents=True)
        (run / "out.md").write_text("x\n")
        actions = [
            cli.Action("worktree", str(ghost),
                       f"remove worktree {ghost} (branch agent/other-T1)"),
            cli.Action("branch", "agent/other-T1",
                       "delete branch agent/other-T1 (merged into main)",
                       needs=str(ghost)),
            cli.Action("directory", str(run.resolve()), f"remove directory {run.resolve()}"),
            cli.Action("scratch", str(scratch.resolve()),
                       f"empty directory {scratch.resolve()}"),
        ]
        failures = cli.run_actions(self.repo, actions)
        self.assertIn(actions[0].text, failures)
        self.assertEqual(failures[actions[1].text], "its worktree was not removed")
        self.assertEqual(failures[actions[2].text], "a branch of the run was not removed")
        self.assertEqual(failures[actions[3].text],
                         f"it holds the worktree {ghost}, which was not removed")
        self.assertTrue((run / "out.md").exists())
        self.assertTrue((scratch / "f.txt").exists())
        self.assertIn("agent/other-T1", self._branches())

    def test_run_actions_skips_branch_whose_worktree_failed(self) -> None:
        missing = str(self.tempdir / "not-a-worktree")
        actions = [
            cli.Action("worktree", missing,
                       f"remove worktree {missing} (branch agent/other-T1)"),
            cli.Action("branch", "agent/other-T1",
                       "delete branch agent/other-T1 (merged into main)",
                       needs=missing),
        ]
        failures = cli.run_actions(self.repo, actions)
        self.assertIn(actions[0].text, failures)
        self.assertEqual(failures[actions[1].text], "its worktree was not removed")
        self.assertIn("agent/other-T1", self._branches())

    def test_render_apply_marks_failed_actions(self) -> None:
        action = cli.Action("branch", "agent/x", "delete branch agent/x (merged into main)")
        cleanup = cli.Cleanup(actions=[action],
                              kept=["keep branch agent/y: not merged into main"],
                              notes=[], branches_kept=1)
        text = cli.render(cleanup, True, {action.text: "boom"})
        self.assertEqual(text.splitlines()[0],
                         "failed: delete branch agent/x (merged into main): boom")
        self.assertEqual(text.splitlines()[-1], "mr-clean: 0 removed, 1 kept, 1 failed")


if __name__ == "__main__":
    unittest.main()
