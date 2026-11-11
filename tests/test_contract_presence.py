"""Tests for scripts/contract_presence.py: provides and requires checks in a worktree."""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import contract_presence as cp  # noqa: E402
import plan_contract as pc  # noqa: E402

CHECK_PLAN = """\
### Task T1: Parser

Contract:
- provides: symbol parse_plan in a.py -- def parse_plan(text)
- provides: file b.py -- module

### Task T2: Consumer

Contract:
- requires: T1 parse_plan -- def parse_plan(text)
"""

GHOST_PLAN = """\
### Task T1: Parser

Contract:
- provides: file b.py -- module

### Task T2: Consumer

Contract:
- requires: T1 ghost -- a ghost
"""

NONE_PLAN = """\
### Task T1: Nothing

Contract: none
"""


def _provide(kind: str, name: str, path: str = "") -> pc.Provide:
    return pc.Provide(task="T1", kind=kind, name=name, path=path, shape="", line=1)


class _WorktreeTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def write(self, rel: str, text: str) -> None:
        target = self.root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")


class FileProvideTests(_WorktreeTestCase):
    def test_present_when_file_exists(self) -> None:
        self.write("scripts/a.py", "print('hi')\n")
        result = cp.provide_present(_provide("file", "scripts/a.py"), self.root)
        self.assertEqual(result, (True, ""))

    def test_missing_when_file_absent(self) -> None:
        result = cp.provide_present(_provide("file", "scripts/a.py"), self.root)
        self.assertEqual(result, (False, "file missing"))

    def test_missing_when_directory_sits_at_path(self) -> None:
        (self.root / "scripts" / "a.py").mkdir(parents=True)
        result = cp.provide_present(_provide("file", "scripts/a.py"), self.root)
        self.assertEqual(result, (False, "file missing"))


class TextProvideTests(_WorktreeTestCase):
    def test_symbol_present_as_whole_word(self) -> None:
        self.write("a.py", "def parse_plan(text):\n    return text\n")
        result = cp.provide_present(_provide("symbol", "parse_plan", "a.py"), self.root)
        self.assertEqual(result, (True, ""))

    def test_symbol_absent_when_only_prefix_matches(self) -> None:
        self.write("a.py", "def parse_plan_extra():\n    return 1\n")
        result = cp.provide_present(_provide("symbol", "parse_plan", "a.py"), self.root)
        self.assertEqual(result, (False, "not found in a.py"))

    def test_dotted_symbol_checks_last_part(self) -> None:
        self.write("a.py", "    errors: tuple\n")
        result = cp.provide_present(
            _provide("symbol", "PlanContract.errors", "a.py"), self.root
        )
        self.assertEqual(result, (True, ""))

    def test_symbol_in_missing_file_names_the_path(self) -> None:
        result = cp.provide_present(_provide("symbol", "x", "missing.py"), self.root)
        self.assertEqual(result, (False, "file missing: missing.py"))


class ConfigProvideTests(_WorktreeTestCase):
    def test_json_key_path_present(self) -> None:
        self.write("routing.json", '{"tunables": {"x": 1}}')
        result = cp.provide_present(
            _provide("config", "tunables.x", "routing.json"), self.root
        )
        self.assertEqual(result, (True, ""))

    def test_json_missing_key_path(self) -> None:
        self.write("routing.json", '{"tunables": {"x": 1}}')
        result = cp.provide_present(
            _provide("config", "tunables.y", "routing.json"), self.root
        )
        self.assertEqual(result, (False, "key path not found in routing.json"))

    def test_json_key_path_through_scalar_is_missing(self) -> None:
        self.write("routing.json", '{"tunables": {"x": 1}}')
        result = cp.provide_present(
            _provide("config", "tunables.x.z", "routing.json"), self.root
        )
        self.assertEqual(result, (False, "key path not found in routing.json"))

    def test_invalid_json_is_reported(self) -> None:
        self.write("routing.json", "{bad")
        result = cp.provide_present(
            _provide("config", "tunables.x", "routing.json"), self.root
        )
        self.assertEqual(result, (False, "invalid JSON: routing.json"))

    def test_toml_uses_whole_word_rule(self) -> None:
        self.write("settings.toml", "max_rounds = 2\n")
        result = cp.provide_present(
            _provide("config", "limits.max_rounds", "settings.toml"), self.root
        )
        self.assertEqual(result, (True, ""))


class SubstringProvideTests(_WorktreeTestCase):
    def test_flag_present(self) -> None:
        self.write("cli.py", 'parser.add_argument("--waves")\n')
        result = cp.provide_present(_provide("flag", "--waves", "cli.py"), self.root)
        self.assertEqual(result, (True, ""))

    def test_env_present(self) -> None:
        self.write(".env.example", "MR_X=\n")
        result = cp.provide_present(
            _provide("env", "MR_X", ".env.example"), self.root
        )
        self.assertEqual(result, (True, ""))

    def test_endpoint_absent_is_not_found(self) -> None:
        self.write("app.py", "routes = []\n")
        result = cp.provide_present(_provide("endpoint", "/api/x", "app.py"), self.root)
        self.assertEqual(result, (False, "not found in app.py"))


class PathSafetyTests(_WorktreeTestCase):
    def test_path_leaving_worktree_is_rejected(self) -> None:
        result = cp.provide_present(
            _provide("symbol", "x", "../outside.py"), self.root
        )
        self.assertEqual(result, (False, "path leaves the worktree"))


class CheckTaskTests(_WorktreeTestCase):
    def test_provides_and_requires_lines(self) -> None:
        self.write("a.py", "def parse_plan(text):\n    return text\n")
        plan = pc.parse_plan(CHECK_PLAN)
        self.assertEqual(
            cp.check_task(plan, "T1", self.root),
            [
                cp.CheckLine(True, "provides symbol parse_plan in a.py", ""),
                cp.CheckLine(False, "provides file b.py", "file missing"),
            ],
        )
        self.assertEqual(
            cp.check_task(plan, "T2", self.root),
            [cp.CheckLine(True, "requires parse_plan from T1", "")],
        )

    def test_require_of_unprovided_name_fails(self) -> None:
        plan = pc.parse_plan(GHOST_PLAN)
        self.assertEqual(
            cp.check_task(plan, "T2", self.root),
            [cp.CheckLine(False, "requires ghost from T1", "T1 provides no 'ghost'")],
        )

    def test_contract_none_returns_empty_list(self) -> None:
        plan = pc.parse_plan(NONE_PLAN)
        self.assertEqual(cp.check_task(plan, "T1", self.root), [])

    def test_unknown_task_raises(self) -> None:
        plan = pc.parse_plan(NONE_PLAN)
        with self.assertRaises(cp.UnknownTask):
            cp.check_task(plan, "T9", self.root)


if __name__ == "__main__":
    unittest.main()
