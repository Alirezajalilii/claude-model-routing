import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import policy_text as pt  # noqa: E402
import routing_config as rc  # noqa: E402


def _agent_text(name):
    return (ROOT / "agents" / f"{name}.md").read_text(encoding="utf-8")


def _tier_names(config, role):
    return [t.name for t in config.tiers if t.role == role]


class FullLanePartTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config = rc.load_config()
        cls.part2 = pt.render_part(cls.config, 2)

    def test_full_lane_dispatches_start_tier_and_falls_back(self):
        for phrase in (
            "Dispatch each task to the start tier the plan assigns",
            "straight to that tier",
            "a task that ran below the plan's executor tier, even if the plan marked it Verify: no",
            "a fresh instance of the plan's fallback verifier tier",
        ):
            self.assertIn(phrase, self.part2)

    def test_full_lane_asks_user_about_wide_task(self):
        self.assertIn("ask the user first about a task with more than 4 skills", self.part2)


class PlannerHaikuFirstTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config = rc.load_config()

    def test_planner_files_carry_start_tier_rules(self):
        names = _tier_names(self.config, "planner")
        self.assertTrue(names)
        for name in names:
            text = _agent_text(name)
            for phrase in (
                "Every task starts on Haiku: on its planned tier if that is a Haiku tier, otherwise on `exec-haiku-high`.",
                "keeps `verify-opus-high` at both tiers",
                "- the task starts below its planned executor tier;",
                "and the start tier (see Executor tier selection)",
                "names its start and fallback verifier tiers",
                "Assign every task a planned executor tier, a start tier and its verifier tiers",
                "split a task that would need more than 4 skills into tasks that each need at most 4",
            ):
                self.assertIn(phrase, text, f"{name}: {phrase}")
            self.assertNotIn("cannot go to a Haiku tier", text, name)


class VerifierFilesTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config = rc.load_config()

    def test_verifier_files_name_lowered_trigger(self):
        names = _tier_names(self.config, "verifier")
        self.assertTrue(names)
        for name in names:
            self.assertIn("the task ran below its planned executor tier", _agent_text(name), name)


class DispatcherHaikuContextTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config = rc.load_config()

    def test_part3_says_executors_start_on_haiku(self):
        part3 = pt.render_part(self.config, 3)
        self.assertIn("Executors start on Haiku, Sonnet-planned tasks included", part3)
        self.assertIn("so planners split work until each task needs at most 4 skills", part3)
        self.assertNotIn("is a Sonnet task", part3)

    def test_part4_cost_and_calibration(self):
        part4 = pt.render_part(self.config, 4)
        for phrase in (
            "a task run below its planned tier, or a failed check",
            "Count tasks run below their planned tier separately.",
            "until the human agrees, verify every one",
        ):
            self.assertIn(phrase, part4)

    def test_part4_states_haiku_price_above_100k(self):
        part4 = pt.render_part(self.config, 4)
        self.assertIn("(0.50 / 2.50 above)", part4)


class ShippedConfigDescriptionsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        raw = json.loads((ROOT / "config" / "routing.json").read_text(encoding="utf-8"))
        cls.tiers = {t["name"]: t for t in raw["tiers"]}

    def test_verifier_descriptions_name_lowered_trigger(self):
        verifiers = [t for t in self.tiers.values() if t["role"] == "verifier"]
        self.assertTrue(verifiers)
        for tier in verifiers:
            self.assertIn("a task run below its planned tier", tier["description"], tier["name"])

    def test_haiku_high_description_names_start_tier_role(self):
        description = self.tiers["exec-haiku-high"]["description"]
        self.assertIn("also the start tier of every Sonnet-planned task", description)

    def test_opus_verifier_description_names_any_executor(self):
        description = self.tiers["verify-opus-high"]["description"]
        self.assertIn("whichever executor tier did the work", description)


class NoUnrenderedPlaceholderTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config = rc.load_config()

    def test_rendered_parts_and_agent_files_have_no_placeholder(self):
        for index in (2, 3, 4):
            self.assertNotIn("{{", pt.render_part(self.config, index), f"part {index}")
        for role in ("planner", "verifier"):
            for name in _tier_names(self.config, role):
                self.assertNotIn("{{", _agent_text(name), name)


if __name__ == "__main__":
    unittest.main()
