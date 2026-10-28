import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import routing_config as rc  # noqa: E402

STATUS_LINE_PLANNER = (
    "- Status line: `READY <plan path>`, `NEED_EVIDENCE <requests path> scouts=<k>`, "
    "`OUT_OF_TOPIC <one-line reason>`, `NO_PLAN_NEEDED <one-line reason>` or "
    "`BLOCKED <plan path> reason=<one line>` (details in the plan under `## Blocked`)."
)


class AgentBodyWordingTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config = rc.load_config()
        cls.agents = [
            (t, (ROOT / "agents" / f"{t.name}.md").read_text(encoding="utf-8"))
            for t in cls.config.tiers
        ]

    def of(self, *roles):
        return [(t, x) for t, x in self.agents if t.role in roles]

    def test_d1_no_return_to_main_session_in_report(self):
        for t, text in self.agents:
            self.assertNotIn("return that need to the main session in your report", text, t.name)

    def test_d2_non_planner_blocked_wording(self):
        phrase = "record that need in your Output file and reply with the status line `BLOCKED <output path> reason=<one line>`"
        for t, text in self.of("scout", "executor", "verifier"):
            self.assertIn(phrase, text, t.name)

    def test_d3_planner_status_and_need_evidence(self):
        for t, text in self.of("planner"):
            self.assertIn(STATUS_LINE_PLANNER, text.split("\n"), t.name)
            self.assertIn("reply `NEED_EVIDENCE <requests path> scouts=<k>` when the need is evidence", text, t.name)

    def test_d4_skills_first_wording(self):
        for t, text in self.agents:
            self.assertNotIn("Load the listed skills", text, t.name)
        for t, text in self.of("executor", "verifier"):
            self.assertIn("Read the project rules files and the listed SKILL.md files first", text, t.name)

    def test_d5_blocked_status_wording(self):
        for t, text in self.agents:
            self.assertNotIn("stop with status BLOCKED", text, t.name)
            self.assertIn("reply with the BLOCKED status line of your role's Output file section", text, t.name)

    def test_d6_planner_evidence_budget(self):
        for t, text in self.of("planner"):
            self.assertIn("Treat the evidence files named in your delegation as verified", text, t.name)
            self.assertIn("does not count against the evidence budget", text, t.name)
            self.assertIn("at most 5 Read/Grep/Glob calls", text, t.name)
            self.assertNotIn("scout evidence in your delegation message", text, t.name)


if __name__ == "__main__":
    unittest.main()
