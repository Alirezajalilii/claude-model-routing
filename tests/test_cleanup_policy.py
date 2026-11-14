"""Policy text for task branch naming and the run cleanup (plan orchestrator-cleanup, T5).

Renders every policy part with the same modules as tests/test_policy_consistency.py
and reads the policy files and the built skill from disk. CleanupPolicyTest pins the
sentences T5 adds (branch naming, the mr-clean cleanup at wrap-up, its placement in
part 1, and the part size cap). CleanupPolicyGuardTest pins text that must stay as
it is (the integration branch sentence, part 5 and handoffs.md without cleanup text).
Run with: python3 -B -m unittest discover -s tests -p test_cleanup_policy.py -v
"""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import policy_text as pt  # noqa: E402
import routing_config as rc  # noqa: E402

SECTIONS = ROOT / "policy" / "sections"
SKILL = ROOT / "skills" / "routing-policy" / "SKILL.md"
MAX_PART_CHARS = 9000
CLEANUP_PARAGRAPH = (
    "**Cleanup.** Every run, also a stalled or abandoned one, ends by removing what it created and nothing else."
)


def render_parts(config):
    count = pt.part_count(config)
    return {i: pt.render_part(config, i) for i in range(1, count + 1)}


class CleanupPolicyTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config = rc.load_config()
        cls.parts = render_parts(cls.config)
        cls.text = "\n".join(cls.parts.values())

    # TC1
    def test_task_branch_naming_rendered(self):
        self.assertIn("Name each task branch `agent/<plan-slug>-<task-id>`", self.text)
        self.assertIn("`mr-clean` finds a run's branches and worktrees only by these names", self.text)

    # TC2
    def test_cleanup_command_rendered(self):
        self.assertIn(
            "run `mr-clean --plan <plan path> --base <base branch> --handoff <handoff dir> --scratch <scratchpad dir>`",
            self.text,
        )

    # TC3
    def test_dry_run_then_apply_rendered(self):
        self.assertIn("then run it again with `--apply`", self.text)

    # TC4
    def test_no_hand_deletion_rendered(self):
        self.assertIn("never delete those by hand or touch another session's branches, worktrees or temp files", self.text)

    # TC5
    def test_full_lane_pointer_in_part_two(self):
        self.assertIn("Before the report, run the **Cleanup** (`mr-clean`).", self.parts[2])
        self.assertLessEqual(len(self.parts[2]), MAX_PART_CHARS)

    # TC6
    def test_fast_lane_pointer_rendered(self):
        self.assertIn("- A run that is fast lane only ends with the Cleanup below (`mr-clean`).", self.text)

    # TC7
    def test_built_skill_names_cleanup_command(self):
        self.assertIn("mr-clean --plan <plan path>", SKILL.read_text(encoding="utf-8"))

    # TC9
    def test_temp_files_confined_to_scratchpad_rendered(self):
        self.assertIn(
            "The main session creates temp files and directories only inside its own session scratchpad.",
            self.text,
        )

    # TC10
    def test_findings_leave_out_handoff_rendered(self):
        self.assertIn("Leave out `--handoff` when a status line of the run carried `findings=`.", self.text)

    # TC11
    def test_cleanup_paragraph_in_part_one(self):
        part1 = self.parts[1]
        self.assertIn(CLEANUP_PARAGRAPH, part1)
        self.assertIn("run `mr-clean --plan <plan path>", part1)
        self.assertLessEqual(len(part1), MAX_PART_CHARS)

    # TC13
    def test_fast_lane_line_precedes_cleanup_paragraph(self):
        lines = (SECTIONS / "lanes.md").read_text(encoding="utf-8").splitlines()
        fast = [i for i, line in enumerate(lines) if line.startswith("- A run that is fast lane only ends with the Cleanup below")]
        cleanup = [i for i, line in enumerate(lines) if line.startswith("**Cleanup.**")]
        self.assertTrue(fast, "fast-lane line missing from lanes.md")
        self.assertTrue(cleanup, "Cleanup paragraph missing from lanes.md")
        self.assertLess(fast[0], cleanup[0])


class CleanupPolicyGuardTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config = rc.load_config()
        cls.parts = render_parts(cls.config)
        cls.text = "\n".join(cls.parts.values())

    # TC8
    def test_integration_branch_sentence_kept(self):
        self.assertIn("create the plan's integration branch `agent/<plan-slug>-integration`", self.text)

    # TC12
    def test_part_five_within_cap_without_cleanup(self):
        part5 = pt.render_part(self.config, 5)
        self.assertLessEqual(len(part5), MAX_PART_CHARS)
        self.assertNotIn("**Cleanup.**", part5)

    # TC12
    def test_handoffs_section_has_no_cleanup_text(self):
        text = (SECTIONS / "handoffs.md").read_text(encoding="utf-8")
        self.assertNotIn("{{plugin_name}}-clean", text)
        self.assertNotIn("Cleanup", text)


if __name__ == "__main__":
    unittest.main()
