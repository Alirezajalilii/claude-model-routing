from __future__ import annotations

import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stdout

import skills_inventory as si


def write_skill(skills_dir: Path, folder: str, body: str) -> None:
    path = skills_dir / folder / "SKILL.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")


def skill_md(name: str, description: str, extra: str = "") -> str:
    return f"---\nname: {name}\ndescription: {description}\n{extra}---\n\nBody.\n"


def write_json(path: Path, data: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


class SkillsInventoryTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        base = Path(self._tmp.name)
        self.claude = base / "claude"
        self.project = base / "project"
        self.claude.mkdir()
        self.project.mkdir()

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def rows(self) -> list:
        return si.build_rows(self.claude, self.project)

    def test_user_skill_row(self) -> None:
        write_skill(self.claude / "skills", "foo", skill_md("foo", "Foo things."))

        rows = self.rows()

        self.assertIn(si.SkillRow("foo", "user", "Foo things."), rows)
        self.assertIn("| foo | user | Foo things. |", si.render_table(self.project, rows))

    def test_disable_model_invocation_skill_is_excluded(self) -> None:
        write_skill(self.claude / "skills", "hidden", skill_md("hidden", "Hidden.", "disable-model-invocation: true\n"))
        write_skill(self.claude / "skills", "visible", skill_md("visible", "Visible."))

        names = [row.name for row in self.rows()]

        self.assertNotIn("hidden", names)
        self.assertIn("visible", names)

    def test_project_skill_has_project_scope(self) -> None:
        write_skill(self.project / ".claude" / "skills", "bar", skill_md("bar", "Bar things."))

        rows = self.rows()

        self.assertIn(si.SkillRow("bar", "project", "Bar things."), rows)

    def test_plugin_dir_from_env_gives_prefixed_skill(self) -> None:
        plugin = Path(self._tmp.name) / "plugin-p"
        write_json(plugin / ".claude-plugin" / "plugin.json", {"name": "p"})
        write_skill(plugin / "skills", "baz", skill_md("baz", "Baz things."))
        write_json(
            self.claude / "settings.json",
            {"env": {"CLAUDE_CODE_PLUGIN_DIRS": os.pathsep.join([str(plugin), str(plugin) + "-unused"])}},
        )

        rows = self.rows()

        self.assertIn(si.SkillRow("p:baz", "plugin p", "Baz things."), rows)

    def test_enabled_user_plugin_is_listed(self) -> None:
        install = Path(self._tmp.name) / "cache" / "q"
        write_json(install / ".claude-plugin" / "plugin.json", {"name": "q"})
        write_skill(install / "skills", "qux", skill_md("qux", "Qux things."))
        write_json(self.claude / "settings.json", {"enabledPlugins": {"q@mk": True}})
        write_json(
            self.claude / "plugins" / "installed_plugins.json",
            {"plugins": {"q@mk": [{"scope": "user", "installPath": str(install)}]}},
        )

        rows = self.rows()

        self.assertIn(si.SkillRow("q:qux", "plugin q", "Qux things."), rows)

    def test_local_scope_plugin_only_for_its_project(self) -> None:
        here = Path(self._tmp.name) / "here-plugin"
        there = Path(self._tmp.name) / "there-plugin"
        for install, folder in ((here, "r"), (there, "s")):
            write_json(install / ".claude-plugin" / "plugin.json", {"name": folder})
            write_skill(install / "skills", "skill-" + folder, skill_md("skill-" + folder, "Local."))
        write_json(
            self.claude / "plugins" / "installed_plugins.json",
            {
                "plugins": {
                    "r@mk": [{"scope": "local", "projectPath": str(self.project), "installPath": str(here)}],
                    "s@mk": [{"scope": "local", "projectPath": str(self.project / "other"), "installPath": str(there)}],
                }
            },
        )

        names = [row.name for row in self.rows()]

        self.assertIn("r:skill-r", names)
        self.assertNotIn("s:skill-s", names)

    def test_directory_marketplace_fallback_reads_source(self) -> None:
        market = Path(self._tmp.name) / "market"
        source = market / "plugins" / "t"
        write_json(source / ".claude-plugin" / "plugin.json", {"name": "t"})
        write_skill(source / "skills", "u", skill_md("u", "U things."))
        write_json(market / ".claude-plugin" / "marketplace.json", {"plugins": [{"name": "t", "source": "./plugins/t"}]})
        empty_cache = Path(self._tmp.name) / "cache-t"
        empty_cache.mkdir()
        write_json(
            self.claude / "settings.json",
            {
                "enabledPlugins": {"t@mk": True},
                "extraKnownMarketplaces": {"mk": {"source": {"source": "directory", "path": str(market)}}},
            },
        )
        write_json(
            self.claude / "plugins" / "installed_plugins.json",
            {"plugins": {"t@mk": [{"scope": "user", "installPath": str(empty_cache)}]}},
        )

        rows = self.rows()

        self.assertIn(si.SkillRow("t:u", "plugin t", "U things."), rows)

    def test_long_description_is_truncated_to_220(self) -> None:
        long_text = "x" * 300
        write_skill(self.claude / "skills", "long", skill_md("long", long_text))

        rows = self.rows()

        self.assertEqual(si.SkillRow("long", "user", "x" * 220), rows[0])

    def test_pipe_in_description_is_replaced_for_table(self) -> None:
        write_skill(self.claude / "skills", "pipes", skill_md("pipes", "a | b"))

        table = si.render_table(self.project, self.rows())

        self.assertIn("| pipes | user | a / b |", table)

    def test_skill_without_frontmatter_is_skipped(self) -> None:
        write_skill(self.claude / "skills", "nofm", "# Just a heading\n")
        write_skill(self.claude / "skills", "ok", skill_md("ok", "Ok."))

        names = [row.name for row in self.rows()]

        self.assertNotIn("nofm", names)
        self.assertIn("ok", names)

    def test_table_header_line_is_exact(self) -> None:
        write_skill(self.claude / "skills", "foo", skill_md("foo", "Foo things."))
        out = io.StringIO()

        with redirect_stdout(out):
            code = si.main(["--claude-dir", str(self.claude), "--project-dir", str(self.project)])

        self.assertEqual(0, code)
        self.assertIn("| Skill | Scope | Description |\n", out.getvalue())
        self.assertIn("| --- | --- | --- |\n", out.getvalue())
        self.assertIn("| foo | user | Foo things. |", out.getvalue())


if __name__ == "__main__":
    unittest.main()
