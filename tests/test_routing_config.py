import copy
import dataclasses
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import routing_config as rc  # noqa: E402


def raw_config():
    return json.loads((ROOT / "config" / "routing.json").read_text(encoding="utf-8"))


def tier_by_name(raw, name):
    return next(t for t in raw["tiers"] if t["name"] == name)


class ShippedConfigTest(unittest.TestCase):
    def test_shipped_config_loads(self):
        config = rc.load_config()
        self.assertEqual(len(config.tiers), 15)
        self.assertEqual(len(config.roles), 4)
        self.assertEqual(config.dispatcher_model_family, "sonnet")
        for tier in config.tiers:
            prefix = config.roles[tier.role].prefix
            self.assertEqual(tier.name, f"{prefix}-{tier.family}-{tier.effort}")

    def test_shipped_config_has_no_validation_errors(self):
        self.assertEqual(rc.validate(raw_config()), [])


class ValidateTest(unittest.TestCase):
    def assert_rejected(self, mutate, needle):
        raw = copy.deepcopy(raw_config())
        mutate(raw)
        messages = rc.validate(raw)
        self.assertTrue(messages, f"expected a message mentioning {needle}")
        self.assertTrue(any(needle in m for m in messages), messages)

    def test_effort_max(self):
        self.assert_rejected(
            lambda r: tier_by_name(r, "exec-haiku-low").update(effort="max"),
            "exec-haiku-low",
        )

    def test_haiku_xhigh(self):
        def mutate(r):
            tier_by_name(r, "exec-haiku-high").update(
                effort="xhigh", name="exec-haiku-xhigh"
            )

        self.assert_rejected(mutate, "exec-haiku-xhigh")

    def test_executor_on_opus(self):
        def mutate(r):
            tier_by_name(r, "exec-sonnet-high").update(
                model="opus", name="exec-opus-high"
            )

        self.assert_rejected(mutate, "exec-opus-high")

    def test_duplicate_tier_name(self):
        def mutate(r):
            r["tiers"].append(copy.deepcopy(tier_by_name(r, "exec-haiku-low")))

        self.assert_rejected(mutate, "exec-haiku-low")

    def test_name_mismatch(self):
        self.assert_rejected(
            lambda r: tier_by_name(r, "exec-haiku-low").update(model="sonnet"),
            "exec-haiku-low",
        )

    def test_unknown_role(self):
        self.assert_rejected(
            lambda r: tier_by_name(r, "exec-haiku-low").update(role="reviewer"),
            "reviewer",
        )

    def test_missing_tunable(self):
        self.assert_rejected(
            lambda r: r["tunables"].pop("skill_cap_haiku"), "skill_cap_haiku"
        )

    def test_sample_rate_zero(self):
        self.assert_rejected(
            lambda r: r["tunables"].update(calibration_sample_rate=0),
            "calibration_sample_rate",
        )

    def test_sample_rate_above_one(self):
        self.assert_rejected(
            lambda r: r["tunables"].update(calibration_sample_rate=1.5),
            "calibration_sample_rate",
        )

    def test_low_defect_rate_not_below_high(self):
        self.assert_rejected(
            lambda r: r["tunables"].update(calibration_low_defect_rate=0.2),
            "calibration_low_defect_rate",
        )

    def test_scout_uses_advisor(self):
        self.assert_rejected(
            lambda r: r["roles"]["scout"].update(uses_advisor=True), "scout"
        )

    def test_role_missing_send_message(self):
        def mutate(r):
            r["roles"]["executor"]["disallowed_tools"].remove("SendMessage")

        self.assert_rejected(mutate, "executor")

    def test_part_with_unknown_section(self):
        def mutate(r):
            r["policy"]["dispatcher_parts"][0]["sections"].append("nope")

        self.assert_rejected(mutate, "nope")

    def test_flag_every_use_unknown_tier(self):
        self.assert_rejected(
            lambda r: r["audit"].update(flag_every_use=["scout-x-y"]), "scout-x-y"
        )

    def test_description_with_newline(self):
        self.assert_rejected(
            lambda r: tier_by_name(r, "exec-haiku-low").update(description="a\nb"),
            "exec-haiku-low",
        )

    def test_two_invalid_tiers_two_messages(self):
        raw = copy.deepcopy(raw_config())
        tier_by_name(raw, "exec-haiku-low").update(effort="max")
        tier_by_name(raw, "scout-haiku-low").update(effort="max")
        messages = rc.validate(raw)
        self.assertTrue(any("exec-haiku-low" in m for m in messages))
        self.assertTrue(any("scout-haiku-low" in m for m in messages))
        self.assertGreaterEqual(len(messages), 2)

    def test_full_model_id_validates_with_family(self):
        raw = copy.deepcopy(raw_config())
        tier_by_name(raw, "exec-sonnet-medium").update(model="claude-sonnet-5-5")
        self.assertEqual(rc.validate(raw), [])
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "routing.json"
            path.write_text(json.dumps(raw), encoding="utf-8")
            config = rc.load_config(path)
        tier = next(t for t in config.tiers if t.name == "exec-sonnet-medium")
        self.assertEqual(tier.family, "sonnet")


class LoadConfigTest(unittest.TestCase):
    def test_syntax_error_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "routing.json"
            path.write_text("{not json", encoding="utf-8")
            with self.assertRaises(rc.ConfigError):
                rc.load_config(path)

    def test_missing_file_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(rc.ConfigError):
                rc.load_config(Path(tmp) / "absent.json")

    def test_invalid_structure_lists_every_message(self):
        raw = copy.deepcopy(raw_config())
        tier_by_name(raw, "exec-haiku-low").update(effort="max")
        raw["tunables"].pop("skill_cap_haiku")
        expected = rc.validate(raw)
        self.assertGreaterEqual(len(expected), 2)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "routing.json"
            path.write_text(json.dumps(raw), encoding="utf-8")
            with self.assertRaises(rc.ConfigError) as ctx:
                rc.load_config(path)
        for message in expected:
            self.assertIn(message, str(ctx.exception))


class ResolveTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config = rc.load_config()

    def test_bare_and_scoped_resolve(self):
        for agent_type in (
            "exec-haiku-low",
            "model-routing:exec-haiku-low",
            "model-routing@inline:exec-haiku-low",
            "model-routing@market:exec-haiku-low",
        ):
            tier = rc.resolve_tier(agent_type, self.config)
            self.assertIsNotNone(tier, agent_type)
            self.assertEqual(tier.name, "exec-haiku-low")

    def test_non_tiers_resolve_to_none(self):
        for agent_type in ("other:exec-haiku-low", "general-purpose", "", None, 5):
            self.assertIsNone(rc.resolve_tier(agent_type, self.config), agent_type)

    def test_bare_name(self):
        c = self.config
        self.assertEqual(rc.bare_name("model-routing:x", c), "x")
        self.assertEqual(rc.bare_name("model-routing@m:x", c), "x")
        self.assertEqual(rc.bare_name("other:x", c), "other:x")
        self.assertEqual(rc.bare_name("x", c), "x")

    def test_install_id_prefix_resolves(self):
        tier = rc.resolve_tier("model-routing@claude-model-routing:exec-haiku-low", self.config)
        self.assertIsNotNone(tier)
        self.assertEqual(tier.name, "exec-haiku-low")

    def test_old_plugin_id_prefix_is_not_a_tier(self):
        old_id = "claude-" + "model-routing"
        self.assertIsNone(rc.resolve_tier(old_id + ":exec-haiku-low", self.config))

    def test_bare_name_strips_install_id_prefix(self):
        self.assertEqual(rc.bare_name("model-routing@claude-model-routing:x", self.config), "x")

    def test_tier_names_and_role_of(self):
        names = rc.tier_names(self.config)
        self.assertEqual(len(names), 15)
        tier = rc.resolve_tier("planner-opus-high", self.config)
        self.assertEqual(rc.role_of(tier, self.config).name, "planner")


class ModelFamilyTest(unittest.TestCase):
    def test_known_values(self):
        self.assertEqual(rc.model_family("claude-haiku-5-5"), "haiku")
        self.assertEqual(rc.model_family("sonnet"), "sonnet")
        self.assertEqual(rc.model_family("claude-sonnet-5-5[1m]"), "sonnet")
        self.assertEqual(rc.model_family("CLAUDE-OPUS-5-5"), "opus")

    def test_unknown_values(self):
        for value in ("gpt-x", "", None):
            self.assertIsNone(rc.model_family(value), value)


class ReservedPrefixTest(unittest.TestCase):
    def test_reserved_plugin_prefixes_are_rejected(self):
        for name in ("claude-x", "anthropic-x", "anthropics-x", "cc-plugin-x"):
            raw = raw_config()
            raw["plugin_name"] = name
            messages = rc.validate(raw)
            self.assertTrue(any("reserved prefix" in m for m in messages), name)

    def test_plugin_name_without_reserved_prefix_is_accepted(self):
        raw = raw_config()
        raw["plugin_name"] = "model-routing"
        self.assertFalse(any("reserved prefix" in m for m in rc.validate(raw)))


class ImmutabilityTest(unittest.TestCase):
    def test_frozen(self):
        config = rc.load_config()
        with self.assertRaises(dataclasses.FrozenInstanceError):
            config.plugin_name = "x"
        with self.assertRaises(TypeError):
            config.tunables["x"] = 1


if __name__ == "__main__":
    unittest.main()
