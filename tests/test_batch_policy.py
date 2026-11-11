"""Policy text for batch statuses, usage limits, calibration, logging, forbidden and cost."""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import policy_text as pt  # noqa: E402
import routing_config as rc  # noqa: E402


class BatchPolicyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        config = rc.load_config()
        cls.part4 = pt.render_part(config, 4)
        cls.part5 = pt.render_part(config, 5)

    def test_tc1_part_five_batch_status_and_usage_limit(self):
        for text in (
            "tasks=<id>:<verdict>",
            "REPLAN-small, REPLAN-design",
            "pass the gate file path; it holds the failing output",
            "- Usage limit:",
            "stopped by the usage limit",
            "dispatch nothing until the reset time it names",
        ):
            self.assertIn(text, self.part5)
        self.assertNotIn("redirect the failing command's output", self.part5)

    def test_tc2_part_four_calibration_feeds_batch(self):
        for text in (
            "adds a random 20% of Verify: no tasks to the plan's batch verification",
            "where claude.md is generated or not committed",
            "becomes `Verify: batch`",
        ):
            self.assertIn(text, self.part4)
        self.assertNotIn("propose in the project's CLAUDE.md", self.part4)

    def test_tc3_part_four_logging_and_forbidden(self):
        for text in (
            "- `exec-sonnet-xhigh` for a task without three yes answers,"
            " except as the escalation after a failure at `exec-sonnet-high`.",
            "agents stopped by the usage limit (dispatch their tasks again after the reset)",
            "`exec-sonnet-xhigh` runs with no earlier `exec-haiku-high` or `exec-sonnet-high`"
            " run of the task",
            "whether a verifier ran, per task or in a batch",
        ):
            self.assertIn(text, self.part4)

    def test_tc4_part_four_cost_batch_verifier(self):
        self.assertIn("share one batch verifier per group at the end of the plan", self.part4)

    def test_tc5_guard_pinned_phrases(self):
        for text in (
            "a task run below its planned tier, or a failed check",
            "Count tasks run below their planned tier separately.",
            "until the human agrees, verify every one",
        ):
            self.assertIn(text, self.part4)

    def test_tc7_part_sizes(self):
        self.assertLessEqual(len(self.part4), 9000)
        self.assertLessEqual(len(self.part5), 9000)


if __name__ == "__main__":
    unittest.main()
