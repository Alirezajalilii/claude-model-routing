from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import policy_text  # noqa: E402
import routing_config  # noqa: E402

# Built by concatenation so that this file never holds the old plugin id as one literal.
OLD = "claude-" + "model-routing"
OLD_SCOPED = re.compile(r"(?<!@)" + re.escape(OLD) + r"(?::|@| policy| dispatch guard)")

LEGACY = "model-" + "routing"
LEGACY_NAME = re.compile(
    r"(?<![\w/.-])" + re.escape(LEGACY)
    + r"(?::|@| policy| dispatch guard|-usage|-audit|-skills|-init"
    + r"| Claude Code plugin| plugin| session context)"
    + "|" + r"plugin " + re.escape(LEGACY) + r"(?![\w-])"
)
LEGACY_TIER = re.compile(
    r"(?<![\w-])(?:(?:planner|verifier)-(?:haiku|sonnet|opus)-(?:low|medium|high|xhigh)"
    r"|(?:scout|exec)-(?:haiku|sonnet|opus)-medium)(?![\w-])"
)


def tracked_and_untracked_files() -> list[Path]:
    result = subprocess.run(
        ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
        cwd=ROOT,
        capture_output=True,
        check=True,
    )
    names = [name for name in result.stdout.decode("utf-8").split("\0") if name]
    return [ROOT / name for name in names if (ROOT / name).is_file()]


def run_script(script: str, stdin: str, part: str | None = None) -> subprocess.CompletedProcess:
    args = [sys.executable, "-B", str(ROOT / "scripts" / script)]
    if part is not None:
        args += ["--part", part]
    env = dict(os.environ, CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH="1")
    return subprocess.run(
        args,
        cwd=ROOT,
        input=stdin,
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )


class NamingTest(unittest.TestCase):
    def test_shipped_plugin_id_is_mr(self):
        self.assertEqual(routing_config.load_config().plugin_name, "mr")

    def test_no_old_form_scoped_names_in_repository(self):
        hits = []
        history = {ROOT / "docs" / "wiki" / "log.md"}  # append-only record of past names and paths
        for path in tracked_and_untracked_files():
            if path in history or "raw" in path.relative_to(ROOT).parts:
                continue
            text = path.read_text(encoding="utf-8", errors="ignore")
            for number, line in enumerate(text.splitlines(), start=1):
                if OLD_SCOPED.search(line):
                    hits.append(f"{path.relative_to(ROOT)}:{number}")
        self.assertEqual(hits, [], "old-form scoped names found:\n" + "\n".join(hits))

    def test_no_legacy_plugin_or_tier_names_in_repository(self):
        hits = []
        skip = {ROOT / "CHANGELOG.md", ROOT / "docs" / "wiki" / "log.md"}
        for path in tracked_and_untracked_files():
            if path in skip or "raw" in path.relative_to(ROOT).parts:
                continue
            text = path.read_text(encoding="utf-8", errors="ignore")
            for number, line in enumerate(text.splitlines(), start=1):
                if LEGACY_NAME.search(line) or LEGACY_TIER.search(line):
                    hits.append(f"{path.relative_to(ROOT)}:{number}")
        self.assertEqual(hits, [], "legacy names found:\n" + "\n".join(hits))

    def test_session_context_uses_new_plugin_id(self):
        result = run_script("session_context.py", "{}", part="1")
        self.assertEqual(result.returncode, 0, result.stderr)
        context = json.loads(result.stdout)["hookSpecificOutput"]["additionalContext"]
        total = policy_text.part_count(routing_config.load_config())
        self.assertTrue(
            context.startswith(f"# mr policy, part 1 of {total}: "),
            context[:120],
        )

    def test_dispatch_guard_blocks_new_scoped_name_without_skills_line(self):
        payload = {
            "tool_name": "Agent",
            "tool_input": {"subagent_type": "mr:exec-haiku-low", "prompt": "Reply with READY."},
        }
        result = run_script("dispatch_guard.py", json.dumps(payload))
        self.assertEqual(result.returncode, 2)
        self.assertTrue(result.stderr.startswith("mr dispatch guard:"), result.stderr[:200])

    def test_routing_policy_skill_names_new_dispatch_form(self):
        text = (ROOT / "skills" / "routing-policy" / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("`mr:<name>`", text)
        self.assertNotIn(OLD, text)

    def test_plans_readme_template_uses_generic_policy_name(self):
        text = (ROOT / "templates" / "plans-README.md").read_text(encoding="utf-8")
        self.assertIn("Model Routing Policy", text)
        self.assertNotIn(OLD, text)

    def test_no_bare_old_plugin_id_in_prose(self):
        # TC10: allowed are the owner/repo shorthand (Alirezajalilii/<old>, which also covers the
        # github.com URL), an install id (@<old>), and the marketplace "name" entry in
        # .claude-plugin/marketplace.json.
        bare = re.compile(r"(?<!@)(?<!Alirezajalilii/)" + re.escape(OLD))
        marketplace = ROOT / ".claude-plugin" / "marketplace.json"
        name_entry = re.compile(r'"name"\s*:')
        hits = []
        history = {ROOT / "docs" / "wiki" / "log.md"}  # append-only record of past names and paths
        for path in tracked_and_untracked_files():
            if path in history or "raw" in path.relative_to(ROOT).parts:
                continue
            text = path.read_text(encoding="utf-8", errors="ignore")
            for number, line in enumerate(text.splitlines(), start=1):
                if not bare.search(line):
                    continue
                if path == marketplace and name_entry.search(line):
                    continue
                hits.append(f"{path.relative_to(ROOT)}:{number}")
        self.assertEqual(hits, [], "bare old plugin id in prose:\n" + "\n".join(hits))


if __name__ == "__main__":
    unittest.main()
