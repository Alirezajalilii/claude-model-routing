from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from policy_text import part_count  # noqa: E402
from routing_config import load_config  # noqa: E402

CMD_PREFIX = 'python3 -B "${CLAUDE_PLUGIN_ROOT}/scripts/'
LAUNCHERS = (
    "mr-usage",
    "mr-audit",
    "mr-skills",
    "mr-init",
    "mr-plan",
    "mr-gate",
    "mr-cost",
)


def load_json(rel: str) -> dict:
    return json.loads((ROOT / rel).read_text(encoding="utf-8"))


def all_commands(hooks: dict) -> list:
    return [
        h["command"]
        for groups in hooks["hooks"].values()
        for group in groups
        for h in group["hooks"]
    ]


def find_key(node, key: str) -> bool:
    if isinstance(node, dict):
        return key in node or any(find_key(v, key) for v in node.values())
    if isinstance(node, list):
        return any(find_key(v, key) for v in node)
    return False


def frontmatter(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    block = text.split("---", 2)[1]
    out = {}
    for line in block.strip().splitlines():
        key, _, value = line.partition(":")
        out[key.strip()] = value.strip().strip('"')
    return out


class PluginManifestTest(unittest.TestCase):
    def test_plugin_json_fields(self) -> None:
        data = load_json(".claude-plugin/plugin.json")
        self.assertEqual(data["name"], load_config().plugin_name)
        self.assertRegex(data["version"], r"^\d+\.\d+\.\d+$")
        self.assertEqual(data["license"], "MIT")
        for key in ("description", "homepage", "repository"):
            self.assertTrue(data.get(key), key)
        self.assertTrue(data["author"]["name"])
        self.assertFalse(find_key(data, "email"))

    def test_version_matches_changelog(self) -> None:
        data = load_json(".claude-plugin/plugin.json")
        changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
        match = re.search(r"^## \[(\d+\.\d+\.\d+)\]", changelog, re.MULTILINE)
        self.assertIsNotNone(match)
        self.assertEqual(data["version"], match.group(1))
        self.assertEqual(data["version"], "0.6.0")

    def test_marketplace_json_fields(self) -> None:
        data = load_json(".claude-plugin/marketplace.json")
        self.assertTrue(data["name"])
        self.assertTrue(data["owner"]["name"])
        self.assertEqual(data["plugins"][0]["name"], load_config().plugin_name)
        self.assertIn(data["plugins"][0]["source"], {".", "./"})


class HooksTest(unittest.TestCase):
    def setUp(self) -> None:
        self.hooks = load_json("hooks/hooks.json")

    def test_session_start_parts(self) -> None:
        cmds = [h["command"] for g in self.hooks["hooks"]["SessionStart"] for h in g["hooks"]]
        n = part_count(load_config())
        self.assertEqual(len(cmds), n)
        parts = sorted(int(re.search(r"--part (\d+)$", c).group(1)) for c in cmds)
        self.assertEqual(parts, list(range(1, n + 1)))

    def test_commands_prefix_and_scripts_exist(self) -> None:
        for cmd in all_commands(self.hooks):
            self.assertTrue(cmd.startswith(CMD_PREFIX), cmd)
            script = cmd[len(CMD_PREFIX):].split('"', 1)[0]
            self.assertTrue((ROOT / "scripts" / script).is_file(), script)

    def test_pre_tool_use_and_session_end(self) -> None:
        pre = self.hooks["hooks"]["PreToolUse"][0]
        self.assertEqual(pre["matcher"], "Agent|Task|Skill")
        self.assertIn("dispatch_guard.py", pre["hooks"][0]["command"])
        end = self.hooks["hooks"]["SessionEnd"][0]["hooks"][0]
        self.assertIn("routing_audit.py", end["command"])
        self.assertTrue(end["command"].endswith("--hook"))
        self.assertGreaterEqual(end["timeout"], 10)


class LauncherTest(unittest.TestCase):
    def test_launchers(self) -> None:
        for name in LAUNCHERS:
            path = ROOT / "bin" / name
            with self.subTest(name=name):
                self.assertTrue(path.is_file())
                self.assertTrue(os.access(path, os.X_OK))
                first = path.read_text(encoding="utf-8").splitlines()[0]
                self.assertEqual(first, "#!/usr/bin/env python3")
                proc = subprocess.run([str(path), "--help"], capture_output=True, text=True)
                self.assertEqual(proc.returncode, 0, proc.stderr)
                self.assertIn("usage:", proc.stdout)


class SkillsTest(unittest.TestCase):
    def test_skill_frontmatter(self) -> None:
        skills = sorted((ROOT / "skills").glob("*/SKILL.md"))
        self.assertGreaterEqual(len(skills), 3)
        for path in skills:
            with self.subTest(skill=path.parent.name):
                fm = frontmatter(path)
                self.assertEqual(fm["name"], path.parent.name)
                self.assertTrue(fm["description"])
                self.assertLess(len(fm["description"]), 1536)
                self.assertNotIn("disable-model-invocation", fm)


class AbsentFilesTest(unittest.TestCase):
    def test_forbidden_paths_absent(self) -> None:
        # The plugin is installed from git, so only tracked paths ship. A local, git-ignored
        # CLAUDE.md (the ~/Work workspace pointer "@AGENTS.md") is allowed on disk.
        tracked = subprocess.run(
            ["git", "ls-files", "-z"], cwd=ROOT, capture_output=True, check=True
        ).stdout.decode("utf-8").split("\0")
        for rel in ("CLAUDE.md", ".github/workflows", "settings.json", "commands"):
            self.assertFalse(any(t == rel or t.startswith(rel + "/") for t in tracked), rel)


class HookEndToEndTest(unittest.TestCase):
    def run_script(self, args: list, extra_env: dict | None = None) -> subprocess.CompletedProcess:
        env = {**os.environ, **(extra_env or {})}
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        return subprocess.run(
            [sys.executable, "-B", *args], input="{}", capture_output=True, text=True, env=env
        )

    def test_dispatch_guard(self) -> None:
        proc = self.run_script([str(ROOT / "scripts" / "dispatch_guard.py")])
        self.assertEqual(proc.returncode, 0, proc.stderr)

    def test_session_context_part_one(self) -> None:
        proc = self.run_script([str(ROOT / "scripts" / "session_context.py"), "--part", "1"])
        self.assertEqual(proc.returncode, 0, proc.stderr)
        data = json.loads(proc.stdout)
        self.assertEqual(data["hookSpecificOutput"]["hookEventName"], "SessionStart")

    def test_routing_audit_hook(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            proc = self.run_script(
                [str(ROOT / "scripts" / "routing_audit.py"), "--hook"],
                {"CLAUDE_PLUGIN_DATA": tmp},
            )
        self.assertEqual(proc.returncode, 0, proc.stderr)


RESERVED_PREFIXES = ("claude-", "anthropic-", "anthropics-", "cc-plugin-")


class RevisionTwoTest(unittest.TestCase):
    def test_plugin_display_name_and_unreserved_id(self) -> None:
        data = load_json(".claude-plugin/plugin.json")
        self.assertEqual(data["displayName"], "Model Routing (mr)")
        self.assertFalse(data["name"].startswith(RESERVED_PREFIXES), data["name"])

    def test_marketplace_description_and_names(self) -> None:
        data = load_json(".claude-plugin/marketplace.json")
        self.assertIsInstance(data.get("description"), str)
        self.assertTrue(data["description"].strip())
        repository = load_json(".claude-plugin/plugin.json")["repository"]
        self.assertEqual(data["name"], repository.rstrip("/").rsplit("/", 1)[-1])
        self.assertEqual(data["plugins"][0]["name"], load_config().plugin_name)

    def test_icon_svg(self) -> None:
        path = ROOT / ".claude-plugin" / "icon.svg"
        self.assertTrue(path.is_file())
        self.assertLess(path.stat().st_size, 4096)
        root = ET.parse(path).getroot()
        self.assertEqual(root.tag, "{http://www.w3.org/2000/svg}svg")
        self.assertEqual(root.get("viewBox"), "0 0 64 64")


if __name__ == "__main__":
    unittest.main()
