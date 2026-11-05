import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import routing_config as rc  # noqa: E402

SKILL_MD = ROOT / "skills" / "routing-policy" / "SKILL.md"
LOAD_BY_TOOL = "or call the Skill tool with the skill's name when that name is in your skill listing"
GROUP_FOLDER = "Read is the only way to load them"
NO_OTHER_SKILL = "Load no other skill, by Read or by the Skill tool"
LISTS_LOADED = "listing every skill you loaded"
ROLE_TOOLS = "Every role has Read, Write and the Skill tool"
SKILLS_LINE_NAMES = "A Skills line that names skills instead of their SKILL.md paths."
REMOVED_PHRASES = (
    "without the Skill tool",
    "Giving tier agents the Skill tool",
    "without a skill-loading tool",
)
LISTING_PHRASE = "the skill listing that comes with the Skill tool"
BLOCKED_PHRASE = "reply with the BLOCKED status line of your role's Output file section"


def _agent_text(tier):
    return (ROOT / "agents" / f"{tier.name}.md").read_text(encoding="utf-8")


class SkillToolPolicyTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config = rc.load_config()
        cls.skill_text = SKILL_MD.read_text(encoding="utf-8")

    def each(self):
        for tier in self.config.tiers:
            yield tier, _agent_text(tier)

    def test_every_tier_body_explains_skill_loading(self):
        for tier, text in self.each():
            self.assertIn(LOAD_BY_TOOL, text, tier.name)
            self.assertIn(GROUP_FOLDER, text, tier.name)

    def test_every_tier_body_limits_other_skills(self):
        for tier, text in self.each():
            self.assertIn(NO_OTHER_SKILL, text, tier.name)
            self.assertIn(LISTS_LOADED, text, tier.name)

    def test_routing_policy_describes_skill_tool(self):
        self.assertIn(ROLE_TOOLS, self.skill_text)
        self.assertIn(SKILLS_LINE_NAMES, self.skill_text)

    def test_routing_policy_drops_old_wording(self):
        for phrase in REMOVED_PHRASES:
            self.assertNotIn(phrase, self.skill_text, phrase)

    def test_planner_bodies_describe_listing_cost(self):
        for tier, text in self.each():
            if tier.role == "planner":
                self.assertIn(LISTING_PHRASE, text, tier.name)

    def test_every_tier_body_keeps_blocked_reply(self):
        for tier, text in self.each():
            self.assertIn(BLOCKED_PHRASE, text, tier.name)


if __name__ == "__main__":
    unittest.main()
