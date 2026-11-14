"""Policy text for run outputs outside worktrees and the mr-clean timing (plan clean-safety-fixes, F4 and F5).

CleanSafetyPolicyTest pins the sentence F4 puts in handoffs.md (outputs name the main
checkout's copy, never a worktree's), the removal of the old worktree-copy sentence,
and part 5's size cap. CleanSafetyPolicyGuardTest pins text that must stay as it is
(the findings= rule, the dated run directory clause, and handoffs.md without cleanup text).
Run with: python3 -B -m unittest discover -s tests -p test_clean_safety_policy.py -v
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
NEW_SENTENCE = "Paths into it always name the main checkout's copy, never a worktree's."
OLD_PHRASE = "writes inside that worktree's copy of the directory"


def render_parts(config):
    count = pt.part_count(config)
    return {i: pt.render_part(config, i) for i in range(1, count + 1)}


class CleanSafetyPolicyTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config = rc.load_config()
        cls.parts = render_parts(cls.config)
        cls.text = "\n".join(cls.parts[i] for i in sorted(cls.parts))

    # TC41
    def test_tc41_part5_names_main_checkout_copy_and_stays_capped(self):
        self.assertIn(
            "kept out of version control. Paths into it always name the main checkout's copy, never a worktree's.",
            self.parts[5],
        )
        self.assertLess(len(self.parts[5]), MAX_PART_CHARS)

    # TC42
    def test_tc42_old_worktree_copy_sentence_is_gone(self):
        self.assertNotIn(OLD_PHRASE, self.text)

    # TC44
    def test_tc44_skill_md_has_new_sentence_and_not_old(self):
        skill = SKILL.read_text(encoding="utf-8")
        self.assertIn(NEW_SENTENCE, skill)
        self.assertNotIn(OLD_PHRASE, skill)


class CleanSafetyPolicyGuardTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config = rc.load_config()
        cls.parts = render_parts(cls.config)
        cls.text = "\n".join(cls.parts[i] for i in sorted(cls.parts))

    # TC45
    def test_tc45_guard_findings_rule_head_and_cleanup_condition_stay(self):
        self.assertIn("Leave out `--handoff` when a status line of the run carried `findings=`.", self.text)
        self.assertIn("(or the run directory the project's rules name), kept out of version control.", self.text)
        handoffs = (SECTIONS / "handoffs.md").read_text(encoding="utf-8")
        self.assertNotIn("{{plugin_name}}-clean", handoffs)
        self.assertNotIn("Cleanup", handoffs)


class CleanTimingPolicyTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config = rc.load_config()
        cls.parts = render_parts(cls.config)

    # TC43
    def test_tc43_cleanup_runs_only_when_no_agent_is_running(self):
        self.assertIn(
            "instead of `--plan`). Run it only when no agent of the run is still running. Leave out `--handoff` when",
            self.parts[1],
        )
        self.assertLess(len(self.parts[1]), MAX_PART_CHARS)
        skill = SKILL.read_text(encoding="utf-8")
        self.assertIn("Run it only when no agent of the run is still running.", skill)


if __name__ == "__main__":
    unittest.main()
