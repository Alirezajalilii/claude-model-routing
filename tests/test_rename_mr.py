"""Tests for the rename to plugin `mr` and the short tier names (task R1)."""
from __future__ import annotations

import copy
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))

import routing_config as rc  # noqa: E402
from test_routing_audit import agent, write_session  # noqa: E402

# Legacy names are built by concatenation so that no test file holds them as one literal.
LEGACY = "model-" + "routing"
MARKET = "claude-" + "model-routing"
COMPLIANT = "Skills: none.\nNever consult the advisor.\nOutput: /tmp/handoff/report.md"

NEW_NAMES = {
    "scout-haiku-low", "scout-haiku-med", "scout-sonnet-high",
    "plan-sonnet-high", "plan-opus-high", "plan-opus-xhigh",
    "exec-haiku-low", "exec-haiku-med", "exec-haiku-high",
    "exec-sonnet-med", "exec-sonnet-high", "exec-sonnet-xhigh",
    "verify-sonnet-med", "verify-sonnet-high", "verify-opus-high",
}
OLD_ID = re.compile(
    r"(?<![\w-])(?:(?:planner|verifier)-(?:haiku|sonnet|opus)-(?:low|medium|high|xhigh)"
    r"|(?:scout|exec)-(?:haiku|sonnet|opus)-medium)(?![\w-])"
)


def raw_config() -> dict:
    return json.loads((ROOT / "config" / "routing.json").read_text(encoding="utf-8"))


def run_guard(subagent_type: str, prompt: str = COMPLIANT) -> subprocess.CompletedProcess:
    event = {"tool_name": "Agent", "tool_input": {"subagent_type": subagent_type, "prompt": prompt}}
    return subprocess.run(
        [sys.executable, "-B", str(ROOT / "scripts" / "dispatch_guard.py")],
        input=json.dumps(event), capture_output=True, text=True, timeout=30,
    )


def run_session_context(part: str, event: dict) -> str:
    env = dict(os.environ, CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH="1")
    result = subprocess.run(
        [sys.executable, "-B", str(ROOT / "scripts" / "session_context.py"), "--part", part],
        input=json.dumps(event), capture_output=True, text=True, env=env, timeout=30,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)["hookSpecificOutput"]["additionalContext"]


class ConfigNamesTest(unittest.TestCase):
    def test_plugin_name_is_mr(self):
        self.assertEqual(rc.load_config().plugin_name, "mr")

    def test_tier_names_are_the_fifteen_new_ids(self):
        self.assertEqual(set(rc.tier_names(rc.load_config())), NEW_NAMES)
        self.assertEqual(len(rc.load_config().tiers), 15)

    def test_frontmatter_effort_stays_real_value(self):
        tier = next(t for t in rc.load_config().tiers if t.name == "exec-haiku-med")
        self.assertEqual(tier.effort, "medium")


class EffortLabelsTest(unittest.TestCase):
    def assert_labels_rejected(self, mutate):
        raw = copy.deepcopy(raw_config())
        mutate(raw)
        messages = rc.validate(raw)
        self.assertTrue(any("effort_labels" in m for m in messages), messages)

    def test_missing(self):
        self.assert_labels_rejected(lambda r: r.pop("effort_labels"))

    def test_label_not_a_slug(self):
        self.assert_labels_rejected(lambda r: r["effort_labels"].update(medium="Med"))

    def test_missing_effort_key(self):
        self.assert_labels_rejected(lambda r: r["effort_labels"].pop("xhigh"))

    def test_duplicate_label(self):
        self.assert_labels_rejected(lambda r: r["effort_labels"].update(high="med"))

    def test_shipped_labels_are_valid(self):
        self.assertEqual(rc.validate(raw_config()), [])
        self.assertEqual(
            raw_config()["effort_labels"],
            {"low": "low", "medium": "med", "high": "high", "xhigh": "xhigh"},
        )


class TierNameRuleTest(unittest.TestCase):
    def messages_after_rename(self, old: str, new: str) -> list:
        raw = copy.deepcopy(raw_config())
        next(t for t in raw["tiers"] if t["name"] == old)["name"] = new
        return rc.validate(raw)

    def test_old_effort_token_is_rejected(self):
        messages = self.messages_after_rename("exec-haiku-med", "exec-haiku-" + "medium")
        self.assertTrue(any("name must be exec-haiku-med" in m for m in messages), messages)

    def test_old_role_token_is_rejected(self):
        messages = self.messages_after_rename("plan-opus-high", "planner-" + "opus-high")
        self.assertTrue(any("name must be plan-opus-high" in m for m in messages), messages)


class ResolveTest(unittest.TestCase):
    def test_scoped_names(self):
        config = rc.load_config()
        self.assertEqual(rc.bare_name("mr:x", config), "x")
        tier = rc.resolve_tier("mr@" + MARKET + ":exec-haiku-low", config)
        self.assertEqual(tier.name, "exec-haiku-low")

    def test_legacy_scope_is_not_stripped(self):
        config = rc.load_config()
        self.assertEqual(rc.bare_name(LEGACY + ":x", config), LEGACY + ":x")
        self.assertIsNone(rc.resolve_tier(LEGACY + ":exec-haiku-low", config))


class GuardTest(unittest.TestCase):
    def test_new_names_are_allowed(self):
        for name in ("mr:exec-haiku-med", "mr@inline:plan-opus-high", "verify-sonnet-high"):
            result = run_guard(name)
            self.assertEqual(result.returncode, 0, (name, result.stderr))

    def test_legacy_names_are_denied(self):
        for name in (LEGACY + ":exec-haiku-low", "exec-haiku-" + "medium", "planner-" + "opus-high"):
            result = run_guard(name)
            self.assertEqual(result.returncode, 2, name)
            self.assertTrue(result.stderr.startswith("mr dispatch guard:"), result.stderr[:120])


class SessionContextTest(unittest.TestCase):
    def test_part_one_names_the_plugin(self):
        text = run_session_context("1", {"session_id": "00000000-0000-4000-8000-000000000001"})
        self.assertTrue(text.startswith("# mr policy, part 1 of "), text[:80])
        self.assertIn("`mr:<name>`", text)
        self.assertIn("mr:exec-haiku-low", text)
        self.assertIn("mr-audit", text)
        self.assertIn("mr-usage", text)
        self.assertNotIn(LEGACY + "-audit", text)
        self.assertNotIn(LEGACY + "-usage", text)


class GeneratedFilesTest(unittest.TestCase):
    def test_agent_files_match_tier_names(self):
        stems = {p.stem for p in (ROOT / "agents").glob("*.md")}
        self.assertEqual(stems, NEW_NAMES)

    def test_exec_haiku_med_frontmatter(self):
        lines = (ROOT / "agents" / "exec-haiku-med.md").read_text(encoding="utf-8").split("\n")
        self.assertEqual(lines[1], "name: exec-haiku-med")
        front = lines[: lines.index("---", 1)]
        self.assertIn("effort: medium", front)
        self.assertIn("model: haiku", front)
        self.assertTrue((ROOT / "agents" / "verify-opus-high.md").is_file())

    def test_reference_skill_roster(self):
        text = (ROOT / "skills" / "routing-policy" / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("`scout-haiku-med` (haiku, medium)", text)
        self.assertIn("`plan-opus-xhigh` (opus, xhigh)", text)

    def test_generated_text_has_no_old_names(self):
        paths = list((ROOT / "agents").glob("*.md")) + [ROOT / "skills" / "routing-policy" / "SKILL.md"]
        for path in paths:
            text = path.read_text(encoding="utf-8")
            self.assertIsNone(OLD_ID.search(text), path.name)
            self.assertNotIn(LEGACY + ":", text, path.name)

    def test_rendered_dispatcher_parts_have_no_old_names(self):
        for part in ("1", "2", "3", "4", "5"):
            text = run_session_context(part, {})
            self.assertIsNone(OLD_ID.search(text), part)
            self.assertNotIn(LEGACY + ":", text, part)


class LauncherTest(unittest.TestCase):
    def test_launchers_exist_and_are_executable(self):
        for name in ("mr-usage", "mr-audit", "mr-skills", "mr-init"):
            path = ROOT / "bin" / name
            self.assertTrue(path.is_file(), name)
            self.assertTrue(os.access(path, os.X_OK), name)

    def test_no_legacy_launcher_names(self):
        for path in (ROOT / "bin").iterdir():
            self.assertFalse(path.name.startswith(LEGACY), path.name)


class AuditNamesTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.claude = os.path.join(tmp.name, "claude")
        self.root = os.path.join(self.claude, "projects")
        os.makedirs(self.root)

    def report(self, agents, n):
        import contextlib
        import io

        import routing_audit as ra

        base = write_session(self.root, f"00000000-0000-4000-8000-0000000000{n:02d}", agents)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            ra.main([base, "--claude-dir", self.claude])
        return out.getvalue()

    def test_scoped_and_bare_share_a_row(self):
        prompt = "Skills: none\nNever consult the advisor.\nPlan docs/plans/2026-10-28-x.md task R1"
        out = self.report([
            agent("pppppppppppppp1", "mr:exec-haiku-low", prompt),
            agent("qqqqqqqqqqqqqq2", "exec-haiku-low", prompt),
        ], 31)
        self.assertIn("- exec-haiku-low: 2", out)

    def test_every_use_flag_and_advisor_flags(self):
        out = self.report([
            agent("rrrrrrrrrrrrrrr3", "mr:scout-sonnet-high",
                  "Skills: none\nNever consult the advisor.\nFind it."),
            agent("ppppppppppppppp4", "mr:plan-opus-high", "Skills: none\nPlan the change."),
            agent("vvvvvvvvvvvvvvv5", "mr:verify-opus-high", "Skills: none\nCheck it."),
        ], 32)
        lines = out.splitlines()
        self.assertTrue(any("every-use tier" in ln and "scout-sonnet-high" in ln for ln in lines), out)
        advisor = "no 'Never consult the advisor' line"
        planner = [ln for ln in lines if "pppppppppp" in ln]
        verifier = [ln for ln in lines if "vvvvvvvvvv" in ln]
        self.assertFalse(any(advisor in ln for ln in planner), out)
        self.assertTrue(any(advisor in ln for ln in verifier), out)


if __name__ == "__main__":
    unittest.main()
