"""Workflow text for verifier self-fix: FIXED handling, verifier round cap, kept-worktree batches."""
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(rel):
    return (ROOT / rel).read_text(encoding="utf-8")


FULL_LANE = "policy/sections/full-lane.md"
HANDOFFS = "policy/sections/handoffs.md"
GATE = "policy/sections/gate.md"
CALIBRATION = "policy/sections/calibration.md"
FORBIDDEN = "policy/sections/forbidden.md"
ROLES = "policy/sections/roles.md"
OVERVIEW = "policy/sections/overview.md"
PLANNER = "policy/agents/planner.md"
SKILL = "skills/routing-policy/SKILL.md"


class FlowRedTest(unittest.TestCase):
    def test_tc1_full_lane_verifier_fixed_is_final(self):
        text = read(FULL_LANE)
        self.assertIn("Verifier FIXED: the verdict is final; no verifier checks the task again.", text)
        self.assertNotIn("Verifier FIX: resume the same executor instance", text)

    def test_tc2_full_lane_verifier_round_cap(self):
        text = read(FULL_LANE)
        for phrase in (
            "FIX rounds per executor tier, and {{max_fix_rounds_per_tier}} verifier rounds per task",
            "resume the same verifier instance with the gate file path (a verifier round)",
            "After the last verifier round, handle the task as a REPLAN with the verdict and gate file paths.",
        ):
            self.assertIn(phrase, text)

    def test_tc3_full_lane_kept_worktree_batches(self):
        text = read(FULL_LANE)
        self.assertIn("it checks and fixes each task in that task's kept worktree (see Gate)", text)
        self.assertIn("each task's worktree path", text)
        self.assertNotIn("detached worktree", text)

    def test_tc4_handoffs_fixed_status(self):
        text = read(HANDOFFS)
        for phrase in (
            "`FIXED <path> commits=<sha>,<sha>`",
            "(verdicts PASS, FIXED, REPLAN-small",
            "or to the gate as its `--report` after FIXED",
        ):
            self.assertIn(phrase, text)
        self.assertNotIn("`FIX <path>`", text)
        self.assertNotIn("to the executor (FIX)", text)

    def test_tc5_gate_fixed_batches(self):
        text = read(GATE)
        self.assertIn("or FIXED and its new gate passes", text)
        self.assertIn("Its verifier's fixes, an escalation or a replan add commits", text)

    def test_tc6_calibration_fixed(self):
        text = read(CALIBRATION)
        self.assertIn("(FIXED or REPLAN)", text)
        self.assertNotIn("(FIX or REPLAN)", text)

    def test_tc7_forbidden_additions(self):
        text = read(FORBIDDEN)
        self.assertIn("An Opus verifier fixes only the defects it finds in the tasks it verifies.", text)
        self.assertIn(
            "- Resuming an executor with a verifier's verdict, or a second verifier pass over a task"
            " whose verifier returned FIXED.",
            text,
        )

    def test_tc8_role_summaries_say_verifiers_fix(self):
        for rel in (ROLES, OVERVIEW, PLANNER):
            self.assertIn("judge, and fix themselves, only the tasks", read(rel), rel)

    def test_tc9_generated_skill_rebuilt(self):
        self.assertIn("Verifier FIXED: the verdict is final", read(SKILL))


class FlowGuardTest(unittest.TestCase):
    def test_tc10_unchanged_guards(self):
        full = read(FULL_LANE)
        self.assertIn(
            "(`checks=green`): resume the same executor instance through SendMessage with the gate file path",
            full,
        )
        self.assertIn("A REPLAN with `fix=small` goes to the fast lane", full)
        self.assertIn("fix=small|design", read(HANDOFFS))


if __name__ == "__main__":
    unittest.main()
