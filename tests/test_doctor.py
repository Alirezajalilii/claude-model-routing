from __future__ import annotations

import io
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from doctor import (  # noqa: E402
    Check,
    check_api_key,
    check_claude,
    check_project,
    check_python,
    check_settings,
    main,
    parse_claude_version,
    render,
    run_checks,
)
from routing_config import load_config  # noqa: E402

CONFIG = load_config()
DEPTH = "CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH"
EFFORT = "CLAUDE_CODE_EFFORT_LEVEL"
API_KEY = "ANTHROPIC_API_KEY"
SECRET = "sk-test-secret-value"
NEW_PYTHON = (3, 11, 0)
OLD_PYTHON = (3, 8, 0)
RECENT_CLAUDE = "2.1.318 (Claude Code)"


def found(_name: str) -> str:
    return "/usr/bin/claude"


def never_run(_args: list) -> str:
    raise AssertionError("claude --version must not run")


def clean_env() -> dict:
    return {DEPTH: "1"}


def initialized_project() -> tempfile.TemporaryDirectory:
    tmp = tempfile.TemporaryDirectory()
    plans = Path(tmp.name) / "docs" / "plans"
    plans.mkdir(parents=True)
    (plans / "README.md").write_text("plans\n", encoding="utf-8")
    (Path(tmp.name) / "docs" / "model-routing-log.md").write_text("log\n", encoding="utf-8")
    return tmp


class PythonCheckTest(unittest.TestCase):
    def test_tc1_python_39_is_ok(self) -> None:
        # TC1
        check = check_python((3, 9, 0))
        self.assertEqual(check.status, "OK")
        self.assertEqual(check.name, "python")
        self.assertEqual(check.detail, "Python 3.9.0")

    def test_tc1_python_38_fails_with_fix_naming_39(self) -> None:
        # TC1
        check = check_python((3, 8, 10))
        self.assertEqual(check.status, "FAIL")
        self.assertIn("3.9", check.fix)


class ClaudeVersionTest(unittest.TestCase):
    def test_tc2_parses_first_dotted_version(self) -> None:
        # TC2
        self.assertEqual(parse_claude_version("2.1.318 (Claude Code)"), (2, 1, 318))

    def test_tc2_garbage_has_no_version(self) -> None:
        # TC2
        self.assertIsNone(parse_claude_version("garbage"))


class ClaudeCheckTest(unittest.TestCase):
    def test_tc3_missing_cli_warns_without_running(self) -> None:
        # TC3
        check = check_claude(which=lambda _name: None, run=never_run)
        self.assertEqual(check.status, "WARN")
        self.assertIn("not found on PATH", check.detail)

    def test_tc4_old_claude_warns_with_minimum(self) -> None:
        # TC4
        check = check_claude(which=found, run=lambda _args: "2.1.300 (Claude Code)")
        self.assertEqual(check.status, "WARN")
        self.assertIn("2.1.306", check.detail)

    def test_tc4_recent_claude_is_ok(self) -> None:
        # TC4
        check = check_claude(which=found, run=lambda _args: RECENT_CLAUDE)
        self.assertEqual(check.status, "OK")
        self.assertEqual(check.detail, "Claude Code 2.1.318")

    def test_tc5_timeout_warns_without_exception(self) -> None:
        # TC5
        def timed_out(_args: list) -> str:
            raise subprocess.TimeoutExpired(["claude"], 10)

        check = check_claude(which=found, run=timed_out)
        self.assertEqual(check.status, "WARN")

    def test_tc5_os_error_warns_without_exception(self) -> None:
        # TC5
        def broken(_args: list) -> str:
            raise OSError("exec failed")

        check = check_claude(which=found, run=broken)
        self.assertEqual(check.status, "WARN")

    def test_tc5_unreadable_version_warns(self) -> None:
        # TC5
        check = check_claude(which=found, run=lambda _args: "no version here")
        self.assertEqual(check.status, "WARN")


class SettingsCheckTest(unittest.TestCase):
    def setUp(self) -> None:
        self.config = CONFIG

    def test_tc6_depth_one_is_single_ok(self) -> None:
        # TC6
        checks = check_settings({DEPTH: "1"}, self.config)
        self.assertEqual(len(checks), 1)
        self.assertEqual(checks[0].status, "OK")

    def test_tc6_missing_depth_warns_naming_it(self) -> None:
        # TC6
        checks = check_settings({}, self.config)
        warns = [c for c in checks if c.status == "WARN"]
        self.assertTrue(any(DEPTH in c.detail for c in warns))

    def test_tc6_effort_override_warns_naming_it(self) -> None:
        # TC6
        checks = check_settings({DEPTH: "1", EFFORT: "high"}, self.config)
        self.assertTrue(any(c.status == "WARN" and EFFORT in c.detail for c in checks))

    def test_settings_warnings_hide_env_values(self) -> None:
        # Constraint: no environment variable value is printed (TC7 family).
        checks = check_settings({DEPTH: "depth-value-x", EFFORT: "effort-value-y"}, self.config)
        details = " ".join(c.detail for c in checks)
        self.assertNotIn("depth-value-x", details)
        self.assertNotIn("effort-value-y", details)
        self.assertIn(DEPTH, details)


class ApiKeyCheckTest(unittest.TestCase):
    def test_tc7_set_key_is_info(self) -> None:
        # TC7
        check = check_api_key({API_KEY: SECRET})
        self.assertIsNotNone(check)
        self.assertEqual(check.status, "INFO")
        self.assertEqual(check.name, "billing")

    def test_tc7_empty_or_unset_key_is_none(self) -> None:
        # TC7
        self.assertIsNone(check_api_key({}))
        self.assertIsNone(check_api_key({API_KEY: ""}))

    def test_tc7_report_never_contains_key_value(self) -> None:
        # TC7
        env = {DEPTH: "1", API_KEY: SECRET}
        with tempfile.TemporaryDirectory() as tmp:
            checks = run_checks(env, tmp, NEW_PYTHON, found, lambda _args: RECENT_CLAUDE)
            self.assertNotIn(SECRET, render(checks))


class ProjectCheckTest(unittest.TestCase):
    def test_tc8_initialized_project_is_ok(self) -> None:
        # TC8
        with initialized_project() as tmp:
            check = check_project(Path(tmp))
        self.assertEqual(check.status, "OK")
        self.assertEqual(check.detail, "initialized")

    def test_tc8_empty_project_warns_with_init_fix(self) -> None:
        # TC8
        with tempfile.TemporaryDirectory() as tmp:
            check = check_project(Path(tmp))
        self.assertEqual(check.status, "WARN")
        self.assertIn("docs/plans/README.md", check.detail)
        self.assertIn("docs/model-routing-log.md", check.detail)
        self.assertIn("mr-init --claude-md", check.fix)


class MainTest(unittest.TestCase):
    def run_main(self, python_version: tuple, project: str) -> tuple:
        out = io.StringIO()
        code = main(
            argv=["--project-dir", project],
            env=clean_env(),
            which=found,
            run=lambda _args: RECENT_CLAUDE,
            version_info=python_version,
            stdout=out,
        )
        return code, out.getvalue()

    def test_tc9_healthy_setup_returns_zero(self) -> None:
        # TC9
        with initialized_project() as tmp:
            code, text = self.run_main(NEW_PYTHON, tmp)
        self.assertEqual(code, 0)
        self.assertEqual(text.splitlines()[-1], "mr-doctor: 0 failed, 0 warnings")

    def test_tc9_old_python_returns_one(self) -> None:
        # TC9
        with initialized_project() as tmp:
            code, _text = self.run_main(OLD_PYTHON, tmp)
        self.assertEqual(code, 1)

    def test_tc9_project_dir_defaults_to_env_var(self) -> None:
        # TC9
        out = io.StringIO()
        with initialized_project() as tmp:
            env = {DEPTH: "1", "CLAUDE_PROJECT_DIR": tmp}
            code = main(
                argv=[],
                env=env,
                which=found,
                run=lambda _args: RECENT_CLAUDE,
                version_info=NEW_PYTHON,
                stdout=out,
            )
        self.assertEqual(code, 0)


class RenderTest(unittest.TestCase):
    def test_render_puts_fix_on_its_own_line(self) -> None:
        checks = [Check("FAIL", "python", "Python 3.8.0", "Install Python 3.9.")]
        lines = render(checks).splitlines()
        self.assertEqual(lines[0], "FAIL python: Python 3.8.0")
        self.assertEqual(lines[1], "     fix: Install Python 3.9.")
        self.assertEqual(lines[-1], "mr-doctor: 1 failed, 0 warnings")


class LauncherListTest(unittest.TestCase):
    def test_tc10_launcher_is_listed_in_packaging_tests(self) -> None:
        # TC10: checked by LAUNCHERS in tests/test_packaging.py.
        packaging = (ROOT / "tests" / "test_packaging.py").read_text(encoding="utf-8")
        self.assertIn('"mr-doctor"', packaging)


if __name__ == "__main__":
    unittest.main()
