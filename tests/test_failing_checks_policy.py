import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import routing_config as rc  # noqa: E402


class FailingChecksPolicyTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config = rc.load_config()
        cls.agents = [
            (t, (ROOT / "agents" / f"{t.name}.md").read_text(encoding="utf-8"))
            for t in cls.config.tiers
        ]
        cls.skill = (ROOT / "skills" / "routing-policy" / "SKILL.md").read_text(encoding="utf-8")
        cls.handoffs = (ROOT / "policy" / "sections" / "handoffs.md").read_text(encoding="utf-8")

    def of(self, *roles):
        return [(t, x) for t, x in self.agents if t.role in roles]

    def test_executor_commits_past_failures_its_change_did_not_cause(self):
        for t, text in self.of("executor"):
            self.assertIn("while a check fails because of your change", text, t.name)
            self.assertIn("A failure your change did not cause does not stop the task", text, t.name)
            self.assertIn("Checks failing outside the task", text, t.name)

    def test_executor_replies_blocked_only_when_its_own_tests_cannot_run(self):
        for t, text in self.of("executor"):
            self.assertIn(
                "Reply BLOCKED only when such a failure keeps you from running your task's own tests or verification commands",
                text,
                t.name,
            )

    def test_executor_red_fold_and_report_wording(self):
        for t, text in self.of("executor"):
            self.assertIn(
                "checks that fail only because a commit holds tests without their implementation",
                text,
                t.name,
            )
            self.assertIn(
                '9. Out-of-scope findings, if any; list every check failing outside the task under the sub-heading "Checks failing outside the task"',
                text,
                t.name,
            )

    def test_executor_drops_the_old_blocked_rule(self):
        for t, text in self.of("executor"):
            self.assertNotIn(
                "reply BLOCKED only when the cause lies outside your task's files or in the environment",
                text,
                t.name,
            )

    def test_verifier_does_not_count_gate_confirmed_failures(self):
        for t, text in self.of("verifier"):
            self.assertIn(
                "that the gate confirmed on the base commit is not a defect of this task",
                text,
                t.name,
            )
            self.assertIn(
                "- Out-of-scope findings, if any, under their own heading after the verdict.",
                text,
                t.name,
            )

    def test_routing_policy_skill_green_and_report_checks(self):
        self.assertIn("also fails on the task's base commit", self.skill)
        self.assertIn("An unlisted failure, or a listed one that passes on the base commit, fails Green.", self.skill)
        self.assertIn(
            'its "Skills loaded" line names every skill on the task\'s Skills line',
            self.skill,
        )

    def test_handoffs_routes_checks_section_and_skills_line(self):
        self.assertIn(
            'reads its "Checks failing outside the task" sub-heading itself',
            self.handoffs,
        )
        self.assertNotIn(
            'For the Report check, also read the report\'s "Skills loaded" line.',
            self.handoffs,
        )


if __name__ == "__main__":
    unittest.main()
