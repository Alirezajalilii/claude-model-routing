import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

SKILL_MD = ROOT / "skills" / "routing-policy" / "SKILL.md"
MATCHER_NEW = "matcher `Agent|Task|Skill`"
MATCHER_OLD = "matcher `Agent|Task`)"
SEPARATE_SUBAGENT = "runs as a separate `general-purpose` subagent that none of these layers stops"
SKILL_CHECK = (
    "a Skill call whose SKILL.md sets `context: fork` or that it cannot find "
    "among the user, project and plugin skills"
)
FAILS_INTERNALLY = "if that check fails internally, it denies"
FORBIDDEN_LINE = "- A subagent invoking a skill with `context: fork` through the Skill tool."


class ForkSkillPolicyTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.skill_text = SKILL_MD.read_text(encoding="utf-8")

    def test_matcher_names_skill_and_drops_old_matcher(self):
        self.assertIn(MATCHER_NEW, self.skill_text)
        self.assertNotIn(MATCHER_OLD, self.skill_text)

    def test_policy_states_fork_skill_hole(self):
        self.assertIn(SEPARATE_SUBAGENT, self.skill_text)

    def test_policy_states_skill_checks(self):
        self.assertIn(SKILL_CHECK, self.skill_text)
        self.assertIn(FAILS_INTERNALLY, self.skill_text)

    def test_forbidden_list_names_fork_skill(self):
        self.assertIn(FORBIDDEN_LINE, self.skill_text)


if __name__ == "__main__":
    unittest.main()
