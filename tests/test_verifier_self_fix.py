import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

FIXED_STATUS = "`FIXED <output path> commits=<sha>,<sha>`"
VERIFY_NAMES = ("verify-sonnet-med", "verify-sonnet-high", "verify-opus-high")
VERIFIER_TOOLS = "tools: Read, Edit, Write, Grep, Glob, Bash, Skill, Monitor, TaskStop"


def _read(rel):
    return (ROOT / rel).read_text(encoding="utf-8")


def _config():
    return json.loads(_read("config/routing.json"))


class VerifierSelfFixRedTest(unittest.TestCase):
    def test_tc1_verifier_tools_equal_executor_tools(self):
        # TC1
        roles = _config()["roles"]
        self.assertEqual(roles["verifier"]["tools"], roles["executor"]["tools"])

    def test_tc2_verifier_descriptions_say_fix_and_commit(self):
        # TC2
        for tier in _config()["tiers"]:
            if not tier["name"].startswith("verify-"):
                continue
            desc = tier["description"]
            name = tier["name"]
            self.assertIn("fixes the defects it finds itself and commits them on the task branch", desc, name)
            self.assertIn("returns PASS, FIXED, REPLAN or BLOCKED", desc, name)
            self.assertNotIn("never edits code", desc, name)

    def test_tc3_verifier_policy_body(self):
        # TC3
        text = _read("policy/agents/verifier.md")
        for phrase in (
            FIXED_STATUS,
            "Change only files that the task's Gate `files:` and `tests:` lines allow",
            "11. Fix every defect you found",
            "12. After your last commit, run the task's `green:` commands again",
        ):
            self.assertIn(phrase, text, phrase)
        for phrase in ("Never change git state", "`FIX <output path>`"):
            self.assertNotIn(phrase, text, phrase)

    def test_tc4_rendered_verifier_files(self):
        # TC4
        for name in VERIFY_NAMES:
            text = _read(f"agents/{name}.md")
            self.assertIn(VERIFIER_TOOLS, text, name)
            self.assertIn(FIXED_STATUS, text, name)


class VerifierSelfFixGuardTest(unittest.TestCase):
    def test_tc5_rendered_verifier_guards(self):
        # TC5 (guard)
        for name in VERIFY_NAMES:
            text = _read(f"agents/{name}.md")
            for phrase in (
                "disallowedTools: Agent, TeamCreate, TeamDelete, SendMessage, advisor",
                "Never consult the advisor.",
                "10. In a batch, do steps 1-9 for each task",
                "- Out-of-scope findings, if any, under their own heading after the verdict.",
            ):
                self.assertIn(phrase, text, f"{name}: {phrase}")

    def test_tc7_size_limits(self):
        # TC7 (guard)
        for tier in _config()["tiers"]:
            name = tier["name"]
            if name.startswith("verify-"):
                limit = 14000
            elif name.startswith("exec-"):
                limit = 12000
            else:
                continue
            size = len(_read(f"agents/{name}.md"))
            self.assertLessEqual(size, limit, f"{name} is {size} characters")


if __name__ == "__main__":
    unittest.main()
