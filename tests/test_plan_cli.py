"""Tests for scripts/plan_cli.py and bin/mr-plan: the waves and check subcommands."""
from __future__ import annotations

import io
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import plan_cli  # noqa: E402
import plan_contract  # noqa: E402

DIAMOND = """\
### Task T1: Base

Contract:
- provides: symbol a in a.py -- def a()

### Task T2: Left

Contract:
- requires: T1 a -- def a()
- provides: symbol b in b.py -- def b()

### Task T3: Right

Contract:
- requires: T1 a -- def a()
- provides: symbol c in c.py -- def c()

### Task T4: Join

Contract:
- requires: T2 b -- def b()
- after: T3
"""

UNKNOWN_TASK = """\
### Task T1: Base

Contract:
- provides: symbol a in a.py -- def a()

### Task T2: Left

Contract:
- requires: T9 x -- def x()
"""

CYCLE = """\
### Task T1: One

Contract:
- after: T2

### Task T2: Two

Contract:
- after: T1
"""

NO_CONTRACT = """\
### Task T1: One

Body only.
"""

CONTRACT_NONE = """\
### Task T1: Docs

Contract: none
"""

CHECK = """\
### Task T1: Base

Contract:
- provides: symbol a in a.py -- def a()

### Task T2: Consumer

Contract:
- provides: symbol x in a.py -- def x()
- requires: T1 a -- def a()
"""


class PlanCliTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.prog = os.path.basename(sys.argv[0])

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _write(self, name: str, text: str) -> str:
        path = self.tmp / name
        path.write_text(text, encoding="utf-8")
        return str(path)

    def _worktree(self, a_py: str) -> str:
        root = self.tmp / "wt"
        root.mkdir(exist_ok=True)
        (root / "a.py").write_text(a_py, encoding="utf-8")
        return str(root)

    def _run(self, *argv: str):
        out, err = io.StringIO(), io.StringIO()
        code = plan_cli.main(list(argv), stdout=out, stderr=err)
        return code, out.getvalue(), err.getvalue()

    def test_waves_diamond(self) -> None:
        plan = self._write("plan.md", DIAMOND)
        code, out, err = self._run("waves", plan)
        self.assertEqual(code, 0, err)
        self.assertEqual(out, "wave 1: T1\nwave 2: T2 (T1), T3 (T1)\nwave 3: T4 (T2, T3)\n")
        self.assertEqual(err, "")

    def test_waves_unknown_task(self) -> None:
        plan = self._write("plan.md", UNKNOWN_TASK)
        code, out, err = self._run("waves", plan)
        self.assertEqual(code, 1)
        self.assertEqual(out, "")
        lines = err.splitlines()
        self.assertEqual(len(lines), 1, err)
        self.assertTrue(lines[0].startswith(self.prog + ": "), lines[0])
        self.assertTrue(lines[0].endswith("requires unknown task T9"), lines[0])

    def test_waves_cycle(self) -> None:
        plan = self._write("plan.md", CYCLE)
        code, out, err = self._run("waves", plan)
        self.assertEqual(code, 1)
        self.assertEqual(out, "")
        self.assertIn("requires or after form a cycle: T1 -> T2 -> T1", err)

    def test_waves_no_contract_lines(self) -> None:
        plan = self._write("plan.md", NO_CONTRACT)
        code, _, err = self._run("waves", plan)
        self.assertEqual(code, 1)
        self.assertIn("no task has a Contract line", err)

    def test_waves_missing_file(self) -> None:
        code, out, err = self._run("waves", str(self.tmp / "missing.md"))
        self.assertEqual(code, 2)
        self.assertEqual(out, "")
        self.assertIn("cannot read", err)

    def test_check_all_present(self) -> None:
        plan = self._write("plan.md", CHECK)
        wt = self._worktree("def a():\n    pass\n\ndef x():\n    pass\n")
        code, out, err = self._run("check", plan, "T2", wt)
        self.assertEqual(code, 0, err)
        lines = out.splitlines()
        self.assertTrue(lines, out)
        self.assertTrue(all(line.startswith("ok: ") for line in lines), out)
        self.assertIn("ok: provides symbol x in a.py", lines)

    def test_check_missing_symbol(self) -> None:
        plan = self._write("plan.md", CHECK)
        wt = self._worktree("def a():\n    pass\n")
        code, out, _ = self._run("check", plan, "T2", wt)
        self.assertEqual(code, 1)
        self.assertIn("missing: provides symbol x in a.py (not found in a.py)", out)

    def test_check_unknown_task(self) -> None:
        plan = self._write("plan.md", CHECK)
        wt = self._worktree("def a():\n    pass\n")
        code, out, err = self._run("check", plan, "T9", wt)
        self.assertEqual(code, 2)
        self.assertEqual(out, "")
        self.assertIn("no task T9 in", err)

    def test_check_worktree_is_a_file(self) -> None:
        plan = self._write("plan.md", CHECK)
        not_dir = self._write("not-a-dir", "x")
        code, _, err = self._run("check", plan, "T2", not_dir)
        self.assertEqual(code, 2)
        self.assertIn("is not a directory", err)

    def test_check_invalid_plan(self) -> None:
        plan = self._write("plan.md", UNKNOWN_TASK)
        wt = self._worktree("def a():\n    pass\n")
        code, out, err = self._run("check", plan, "T1", wt)
        self.assertEqual(code, 1)
        self.assertEqual(out, "")
        self.assertIn("requires unknown task T9", err)

    def test_check_contract_none(self) -> None:
        plan = self._write("plan.md", CONTRACT_NONE)
        wt = self._worktree("")
        code, out, err = self._run("check", plan, "T1", wt)
        self.assertEqual(code, 0, err)
        self.assertEqual(out, "no provides or requires lines\n")

    def test_no_subcommand_returns_usage_error(self) -> None:
        err = io.StringIO()
        with redirect_stderr(err):
            code = plan_cli.main([], stdout=io.StringIO(), stderr=err)
        self.assertEqual(code, 2)

    def test_internal_error_is_reported(self) -> None:
        plan = self._write("plan.md", DIAMOND)
        with mock.patch.object(plan_contract, "parse_plan", side_effect=RuntimeError("boom")):
            code, _, err = self._run("waves", plan)
        self.assertEqual(code, 2)
        self.assertIn(self.prog + ": internal error: boom", err)

    def test_launcher_runs_waves(self) -> None:
        plan = self._write("plan.md", DIAMOND)
        env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
        proc = subprocess.run(
            [sys.executable, "-B", str(ROOT / "bin" / "mr-plan"), "waves", plan],
            capture_output=True, text=True, env=env,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("wave 3: T4 (T2, T3)", proc.stdout)


if __name__ == "__main__":
    unittest.main()
