import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _read(relative):
    return (ROOT / relative).read_text(encoding="utf-8")


class ShippedSkillCapsTest(unittest.TestCase):
    def test_shipped_skill_caps(self):
        tunables = json.loads(_read("config/routing.json"))["tunables"]
        self.assertEqual(tunables["skill_cap_haiku"], 4)
        self.assertEqual(tunables["skill_cap_other"], 6)


class RoutingPolicySkillCapsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = _read("skills/routing-policy/SKILL.md")

    def test_caps_are_stated(self):
        for phrase in (
            "at most 4 skills for any Haiku agent",
            "at most 6 skills for any other agent",
        ):
            self.assertIn(phrase, self.text)

    def test_old_caps_are_gone(self):
        for phrase in ("more than 2 skills", "at most 2 skills"):
            self.assertNotIn(phrase, self.text)

    def test_assignment_order_is_stated(self):
        for phrase in (
            "plus the skills for the task's language, framework and specific work",
            "passes the skills the user names as must-follow to the planner",
        ):
            self.assertIn(phrase, self.text)

    def test_grouped_skills_are_stated(self):
        for phrase in (
            "plus skills kept one folder deeper in a group folder",
            "including grouped skills",
        ):
            self.assertIn(phrase, self.text)


class PlannerBodySkillCapsTest(unittest.TestCase):
    def test_planner_bodies_state_caps(self):
        names = sorted(path.name for path in (ROOT / "agents").glob("plan-*.md"))
        self.assertTrue(names)
        for name in names:
            text = _read(f"agents/{name}")
            for phrase in ("at most 4 skills", "would need more than 4 skills"):
                self.assertIn(phrase, text, f"{name}: {phrase}")


class HaikuExecutorDescriptionsTest(unittest.TestCase):
    def test_haiku_executor_descriptions_state_cap(self):
        raw = json.loads(_read("config/routing.json"))
        cap = raw["tunables"]["skill_cap_haiku"]
        tiers = [t for t in raw["tiers"] if t["role"] == "executor" and t["model"] == "haiku"]
        self.assertTrue(tiers)
        for tier in tiers:
            self.assertIn(f"at most {cap} skills", tier["description"], tier["name"])
            self.assertNotIn("at most 2 skills", tier["description"], tier["name"])


if __name__ == "__main__":
    unittest.main()
