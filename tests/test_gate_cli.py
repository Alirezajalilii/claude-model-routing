"""End-to-end tests for the mr-gate command in scripts/gate_cli.py.

Each test builds a throwaway repository in a temporary directory, writes a plan
and a report in another temporary directory, and runs gate_cli.main() on the
repository. Repository setup uses subprocess directly so the setup does not
depend on the code under test. The launcher bin/mr-gate is covered by
LauncherTest in tests/test_packaging.py.
"""

import io
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import gate_cli  # noqa: E402

SEVEN = ["red", "integrity", "coverage", "scope", "contract", "green", "report"]
BASE_FILES = {"base.txt": "base\n"}
RED = {"tests/t.txt": "TC1 TC2\n"}
GREEN = {"impl.txt": "impl\n"}
GATE = ("- files: impl.txt", "- tests: tests/*.txt", "- red: test -f impl.txt",
        "- guard: test -f base.txt", "- green: test -f impl.txt")
CASES = ("- TC1: the first case", "- TC2 (guard): the second case")
REPORT = "Skills loaded: tdd-workflow\n"
OUTSIDE = REPORT + "\n### Checks failing outside the task\n- test -f missing.txt\n"


def _git(worktree: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(worktree), *args], check=True,
                   capture_output=True, text=True)


def _sha(worktree: Path, rev: str = "HEAD") -> str:
    out = subprocess.run(["git", "-C", str(worktree), "rev-parse", rev],
                         check=True, capture_output=True, text=True)
    return out.stdout.strip()


def _branch(worktree: Path) -> str:
    out = subprocess.run(["git", "-C", str(worktree), "symbolic-ref", "--short", "HEAD"],
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


def _plan(gate=GATE, cases=CASES, note=None) -> str:
    lines = ["# Plan", "", "### Task T1: x", "", "Contract: none", ""]
    if note:
        lines += [note, ""]
    if cases:
        lines += ["Test Cases:", *cases, ""]
    lines += ["Skills: /s/tdd-workflow/SKILL.md", ""]
    if gate is not None:
        lines += ["Gate:", *gate]
    return "\n".join(lines) + "\n"


def _gate_with(*lines: str) -> tuple:
    """GATE with each item replaced by the given line that has the same key."""
    keys = {line.split(":", 1)[0]: line for line in lines}
    return tuple(keys.get(line.split(":", 1)[0], line) for line in GATE)


def _sections(text: str) -> list:
    pairs = []
    for line in text.splitlines():
        if line.startswith("## ") and ": " in line:
            name, status = line[3:].split(": ", 1)
            pairs.append((name, status))
    return pairs


def _status(text: str, name: str) -> str:
    return dict(_sections(text))[name]


def _field(text: str, key: str) -> str:
    prefix = "- %s: " % key
    for line in text.splitlines():
        if line.startswith(prefix):
            return line[len(prefix):]
    raise AssertionError("gate file has no %s line" % key)


def _checks(stdout: str) -> list:
    return stdout.strip().split("checks=", 1)[1].split(",")


class GateCliTest(unittest.TestCase):
    """Repository: base commit A (base.txt) on branch `work`. A task adds
    commit B (red: tests/t.txt holds TC1 TC2) and commit C (green: impl.txt),
    through _build."""

    def setUp(self) -> None:
        repo = tempfile.TemporaryDirectory()
        self.addCleanup(repo.cleanup)
        self.wt = Path(repo.name)
        _git(self.wt, "init", "-q")
        _git(self.wt, "symbolic-ref", "HEAD", "refs/heads/work")
        _git(self.wt, "config", "user.email", "test@example.com")
        _git(self.wt, "config", "user.name", "Test")
        _git(self.wt, "config", "commit.gpgsign", "false")
        self.base = _commit(self.wt, BASE_FILES, "A")
        files = tempfile.TemporaryDirectory()
        self.addCleanup(files.cleanup)
        self.dir = Path(files.name)
        self.plan = self.dir / "plan.md"
        self.report = self.dir / "report.md"
        self.out = self.dir / "gates" / "T1.md"
        self.task = []  # type: list
        self._write_plan(_plan())

    def _build(self, red=RED, green=GREEN, report=REPORT) -> None:
        self.task = []
        if red is not None:
            self.task.append(_commit(self.wt, red, "B"))
        self.task.append(_commit(self.wt, green, "C"))
        if report is not None:
            self._write_report(report)

    def _write_plan(self, text: str) -> None:
        self.plan.write_text(text, encoding="utf-8")

    def _write_report(self, text: str) -> None:
        self.report.write_text(text, encoding="utf-8")

    def _run(self, commits=None, extra=()):
        out, err = io.StringIO(), io.StringIO()
        shas = commits if commits is not None else ",".join(self.task)
        argv = [str(self.plan), "T1", str(self.wt), "--commits", shas,
                "--report", str(self.report), "--out", str(self.out), *extra]
        rc = gate_cli.main(argv, stdout=out, stderr=err)
        return rc, out.getvalue(), err.getvalue()

    def _gate(self) -> str:
        return self.out.read_text(encoding="utf-8")

    def test_tc1_happy_path_writes_seven_passing_sections(self) -> None:
        self._build()
        rc, out, err = self._run()
        self.assertEqual(rc, 0, err)
        self.assertEqual(out, "PASS %s\n" % self.out)
        gate = self._gate()
        self.assertIn("- result: PASS", gate)
        self.assertEqual([name for name, _ in _sections(gate)], SEVEN)

    def test_tc2_red_command_passing_on_commit_one_fails_red(self) -> None:
        self._build()
        self._write_plan(_plan(gate=_gate_with("- red: test -f base.txt")))
        rc, out, _ = self._run()
        self.assertEqual(rc, 1)
        self.assertEqual(out, "FAIL %s checks=red\n" % self.out)

    def test_tc3_green_commit_outside_file_list_fails_scope(self) -> None:
        self._build(green={"impl.txt": "impl\n", "extra.txt": "x\n"})
        rc, out, _ = self._run()
        self.assertEqual(rc, 1)
        self.assertEqual(out, "FAIL %s checks=scope\n" % self.out)

    def test_tc4_green_commit_editing_commit_one_fails_integrity(self) -> None:
        self._build(green={"impl.txt": "impl\n", "tests/t.txt": "TC1 TC2 edited\n"})
        rc, out, _ = self._run()
        self.assertEqual(rc, 1)
        self.assertEqual(out, "FAIL %s checks=integrity\n" % self.out)

    def test_tc5_case_without_test_name_fails_coverage(self) -> None:
        self._build()
        self._write_plan(_plan(cases=("- TC3: the only case",)))
        rc, out, _ = self._run()
        self.assertEqual(rc, 1)
        self.assertEqual(out, "FAIL %s checks=coverage\n" % self.out)

    def test_tc6_unlisted_green_failure_fails_and_listed_one_passes(self) -> None:
        self._build()
        self._write_plan(_plan(gate=_gate_with("- green: test -f missing.txt")))
        rc, out, _ = self._run()
        self.assertEqual(rc, 1)
        self.assertEqual(out, "FAIL %s checks=green\n" % self.out)
        self._write_report(OUTSIDE)
        rc, out, err = self._run()
        self.assertEqual(rc, 0, err)
        self.assertEqual(out, "PASS %s\n" % self.out)

    def test_tc7_report_commits_follow_the_base_ref(self) -> None:
        self._build()
        green = self.task[-1]
        _git(self.wt, "branch", "start", self.base)
        rc, out, _ = self._run(commits=green, extra=("--base", "start"))
        self.assertEqual(rc, 1)
        self.assertIn("report", _checks(out))
        self.assertEqual(_status(self._gate(), "report"), "fail")
        rc, out, _ = self._run(commits=green)
        self.assertEqual(_status(self._gate(), "report"), "pass")

    def test_tc8_missing_report_fails_report(self) -> None:
        self._build(report=None)
        rc, out, _ = self._run()
        self.assertEqual(rc, 1)
        self.assertEqual(out, "FAIL %s checks=report\n" % self.out)

    def test_tc9_plan_without_gate_block_is_a_usage_error(self) -> None:
        self._build()
        self._write_plan(_plan(gate=None))
        rc, out, err = self._run()
        self.assertEqual(rc, 2)
        self.assertEqual(err.strip(), "mr-gate: task T1 has no Gate block")
        self.assertFalse(self.out.exists())

    def test_tc10_untracked_change_is_allowed_modified_file_is_not(self) -> None:
        self._build()
        (self.wt / "scratch.txt").write_text("untracked\n")
        rc, _, err = self._run()
        self.assertEqual(rc, 0, err)
        (self.wt / "base.txt").write_text("edited\n")
        rc, _, err = self._run()
        self.assertEqual(rc, 2)
        self.assertEqual(err.strip(), "mr-gate: worktree has uncommitted changes")

    def test_tc11_worktree_is_back_on_its_branch_after_every_run(self) -> None:
        self._build()
        self._run()
        self.assertEqual(_branch(self.wt), "work")
        self.assertTrue((self.wt / "impl.txt").exists())
        self._write_plan(_plan(gate=_gate_with("- red: test -f base.txt")))
        self._run()
        self.assertEqual(_branch(self.wt), "work")
        self.assertTrue((self.wt / "impl.txt").exists())

    def test_tc12_existing_suite_only_task_skips_red_and_coverage(self) -> None:
        self._build(red=None)
        self._write_plan(_plan(gate=("- files: impl.txt", "- green: test -f impl.txt"),
                               cases=(), note="Tests: existing suite only"))
        rc, _, err = self._run()
        self.assertEqual(rc, 0, err)
        gate = self._gate()
        self.assertEqual(_status(gate, "red"), "n/a")
        self.assertEqual(_status(gate, "integrity"), "pass")
        self.assertEqual(_status(gate, "coverage"), "n/a")
        self.assertIn("- result: PASS", gate)

    def test_tc13_command_over_timeout_fails_green(self) -> None:
        self._build()
        self._write_plan(_plan(gate=_gate_with("- green: sleep 3")))
        rc, out, _ = self._run(extra=("--timeout", "1"))
        self.assertEqual(rc, 1)
        self.assertEqual(_checks(out), ["green"])
        self.assertIn("timed out after 1 s", self._gate())

    def test_tc15_base_moved_by_merge_then_fix_commit_regates(self) -> None:
        self._build()
        rc, _, err = self._run()
        self.assertEqual(rc, 0, err)
        base = _field(self._gate(), "base")
        green = self.task[-1]
        _git(self.wt, "branch", "start", green)  # the task was fast-forwarded into start
        fix = _commit(self.wt, {"impl.txt": "impl fixed\n"}, "D")
        rc, out, _ = self._run(commits=",".join(self.task), extra=("--base", "start"))
        self.assertEqual(rc, 1)
        self.assertIn("report", _checks(out))
        rc, out, err = self._run(commits=",".join([*self.task, fix]),
                                 extra=("--base", base))
        self.assertEqual(rc, 0, err)
        self.assertEqual(out, "PASS %s\n" % self.out)


if __name__ == "__main__":
    unittest.main()
