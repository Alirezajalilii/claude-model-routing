import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
POLICY_SKILL = ROOT / "skills" / "routing-policy" / "SKILL.md"


class VerifyModesPolicyTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.planners = {
            path.name: path.read_text(encoding="utf-8")
            for path in sorted((ROOT / "agents").glob("plan-*.md"))
        }
        cls.policy = POLICY_SKILL.read_text(encoding="utf-8")

    def assert_planners_contain(self, phrases):
        for name, text in self.planners.items():
            for phrase in phrases:
                self.assertIn(phrase, text, f"{name}: missing {phrase!r}")

    def assert_planners_lack(self, phrases):
        for name, text in self.planners.items():
            for phrase in phrases:
                self.assertNotIn(phrase, text, f"{name}: still has {phrase!r}")

    def test_planner_files_are_found(self):
        self.assertTrue(self.planners, "no agents/plan-*.md files found")

    def test_tc1_planners_teach_gate_block_and_test_case_ids(self):
        self.assert_planners_contain(
            (
                "### Gate block format",
                "`- guard: <command>`",
                "`- green: <command>`",
                "(`- TC4 (guard): ...`)",
                "starting `Skills:`",
            )
        )

    def test_tc2_planners_name_task_and_batch_verify_marks(self):
        self.assert_planners_contain(
            (
                "`Verify: task` (its own verifier, before the task merges)",
                "`Verify: batch` (one verifier for several tasks",
            )
        )
        self.assert_planners_lack(("Verification triggers (marked by the planner as Verify: yes)",))

    def test_tc3_planners_limit_xhigh_to_three_yes_answers(self):
        self.assert_planners_contain(
            (
                "never above `exec-sonnet-high`",
                "only for a task with three yes answers or as the escalation after a failure at `exec-sonnet-high`",
            )
        )
        self.assert_planners_lack(("Large refactors, concurrency, performance, security-sensitive code",))

    def test_tc4_planners_start_below_tier_tasks_at_least_batch(self):
        self.assert_planners_contain(("is at least `Verify: batch`",))
        self.assert_planners_lack(("A task that starts below its planned tier is Verify: yes",))

    def test_tc5_planners_mark_every_task_task_batch_or_no(self):
        self.assert_planners_contain(("Mark every task `Verify: task`, `Verify: batch` or `Verify: no`",))

    def test_tc6_routing_policy_skill_has_gate_block_format(self):
        self.assertIn("### Gate block format", self.policy)
        self.assertIn("from which `mr-gate` runs the gate", self.policy)

    def test_tc7_guard_planners_keep_start_tier_and_verifier_pins(self):
        self.assert_planners_contain(
            (
                "- the task starts below its planned executor tier;",
                "keeps `verify-opus-high` at both tiers",
            )
        )


if __name__ == "__main__":
    unittest.main()
