from __future__ import annotations

import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import contextlib
import io
import os
import tempfile
import unittest
from unittest import mock

import init_project

POINTER = (
    "Model routing: this project follows the claude-model-routing policy "
    "(plans in docs/plans/, routing log in docs/model-routing-log.md)."
)
TEMPLATES = ROOT / "templates"
PLANS_PATH = "docs/plans/README.md"
LOG_PATH = "docs/model-routing-log.md"
# Built by concatenation so that no literal in this file matches the scanner rules.
HOME_MARKERS = ("~/" + ".claude", "/" + "home/", "subagent-" + "usage.py", "routing-" + "audit.py")


class InitProjectTest(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.project = Path(tmp.name) / "project"
        self.project.mkdir()

    def run_main(self, *args: str) -> tuple[int, str, str]:
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = init_project.main(list(args))
        return code, out.getvalue(), err.getvalue()

    def read(self, relpath: str) -> str:
        return (self.project / relpath).read_text(encoding="utf-8")

    def test_empty_project_creates_both_files_from_templates(self) -> None:
        code, out, _ = self.run_main("--project-dir", str(self.project))
        lines = out.splitlines()

        self.assertEqual(code, 0)
        self.assertEqual(self.read(PLANS_PATH), (TEMPLATES / "plans-README.md").read_text(encoding="utf-8"))
        self.assertEqual(self.read(LOG_PATH), (TEMPLATES / "model-routing-log.md").read_text(encoding="utf-8"))
        self.assertFalse((self.project / "CLAUDE.md").exists())
        self.assertIn("created docs/plans/README.md", lines)
        self.assertIn("created docs/model-routing-log.md", lines)
        self.assertIn(f"pointer: {POINTER}", lines)

    def test_existing_files_are_not_overwritten(self) -> None:
        (self.project / PLANS_PATH).parent.mkdir(parents=True)
        (self.project / PLANS_PATH).write_text("custom plans\n", encoding="utf-8")
        (self.project / LOG_PATH).write_text("custom log\n", encoding="utf-8")

        code, out, _ = self.run_main("--project-dir", str(self.project))
        lines = out.splitlines()

        self.assertEqual(code, 0)
        self.assertEqual(self.read(PLANS_PATH), "custom plans\n")
        self.assertEqual(self.read(LOG_PATH), "custom log\n")
        self.assertIn("exists docs/plans/README.md", lines)
        self.assertIn("exists docs/model-routing-log.md", lines)

    def test_claude_md_is_created_with_pointer_when_missing(self) -> None:
        code, out, _ = self.run_main("--project-dir", str(self.project), "--claude-md")

        self.assertEqual(code, 0)
        self.assertEqual(self.read("CLAUDE.md"), POINTER + "\n")
        self.assertIn("appended CLAUDE.md pointer", out.splitlines())

    def test_claude_md_gets_blank_line_before_pointer(self) -> None:
        (self.project / "CLAUDE.md").write_text("# P\n", encoding="utf-8")

        code, out, _ = self.run_main("--project-dir", str(self.project), "--claude-md")

        self.assertEqual(code, 0)
        self.assertEqual(self.read("CLAUDE.md"), "# P\n\n" + POINTER + "\n")
        self.assertIn("appended CLAUDE.md pointer", out.splitlines())

    def test_claude_md_without_trailing_newline_is_kept_intact(self) -> None:
        (self.project / "CLAUDE.md").write_text("# P", encoding="utf-8")

        code, _, _ = self.run_main("--project-dir", str(self.project), "--claude-md")

        self.assertEqual(code, 0)
        self.assertEqual(self.read("CLAUDE.md"), "# P\n\n" + POINTER + "\n")

    def test_claude_md_already_mentioning_policy_is_unchanged(self) -> None:
        original = "# P\n\nSee claude-model-routing notes.\n"
        (self.project / "CLAUDE.md").write_text(original, encoding="utf-8")

        code, out, _ = self.run_main("--project-dir", str(self.project), "--claude-md")

        self.assertEqual(code, 0)
        self.assertEqual(self.read("CLAUDE.md"), original)
        self.assertIn("exists CLAUDE.md pointer", out.splitlines())

    def test_missing_project_dir_exits_2(self) -> None:
        missing = self.project / "nope"

        code, _, err = self.run_main("--project-dir", str(missing))

        self.assertEqual(code, 2)
        self.assertIn(f"init_project: {missing} does not exist", err)
        self.assertFalse(missing.exists())

    def test_project_dir_defaults_to_claude_project_dir(self) -> None:
        with mock.patch.dict(os.environ, {"CLAUDE_PROJECT_DIR": str(self.project)}):
            code, _, _ = self.run_main()

        self.assertEqual(code, 0)
        self.assertTrue((self.project / PLANS_PATH).is_file())
        self.assertTrue((self.project / LOG_PATH).is_file())

    def test_templates_contain_no_machine_specific_text(self) -> None:
        for name in ("model-routing-log.md", "plans-README.md"):
            text = (TEMPLATES / name).read_text(encoding="utf-8")
            for marker in HOME_MARKERS:
                self.assertNotIn(marker, text, f"{name} contains {marker!r}")


if __name__ == "__main__":
    unittest.main()
