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


def messages(mutate):
    raw = copy.deepcopy(raw_config())
    mutate(raw)
    return "\n".join(rc.validate(raw))


def set_key(key, value):
    def mutate(raw):
        raw["stall_watch"][key] = value
    return mutate


class StallWatchShippedTest(unittest.TestCase):
    def setUp(self):
        self.config = rc.load_config()

    def test_v1_shipped_values(self):
        sw = self.config.stall_watch
        self.assertIsInstance(sw, rc.StallWatch)
        self.assertIs(sw.enabled, True)
        self.assertEqual(sw.roles, ("executor",))
        self.assertEqual(sw.ignored_tools, ("Monitor", "TaskStop"))
        self.assertEqual(sw.change_tools, ("Edit", "Write"))
        self.assertEqual(sw.handback_tools, ("Write",))
        self.assertEqual(sw.read_only_tools, ("Read", "Grep", "Glob"))
        self.assertEqual(len(sw.read_only_bash_prefixes), 13)
        self.assertIn("sed -n", sw.read_only_bash_prefixes)
        self.assertIn("git status", sw.read_only_bash_prefixes)
        self.assertEqual(sw.repeat_window, 40)
        self.assertEqual(sw.repeat_limit, 4)
        self.assertEqual(sw.read_only_streak_limit, 60)
        self.assertEqual(sw.max_nudges, 1)
        self.assertEqual(sw.state_max_age_hours, 24)
        self.assertEqual(
            sw.call_key_fields,
            (("Bash", ("command", "timeout", "run_in_background")),),
        )

    def test_v2_stall_watch_is_frozen(self):
        with self.assertRaises(dataclasses.FrozenInstanceError):
            self.config.stall_watch.repeat_limit = 5

    def test_v3_shipped_config_has_no_stall_watch_errors(self):
        self.assertEqual(rc.validate(raw_config()), [])


class StallWatchSectionTest(unittest.TestCase):
    def test_v4_missing_section(self):
        self.assertIn("stall_watch: missing", messages(lambda r: r.pop("stall_watch")))

    def test_v4_section_not_an_object(self):
        def mutate(raw):
            raw["stall_watch"] = []
        self.assertIn("stall_watch: must be an object", messages(mutate))

    def test_v5_unknown_key(self):
        def mutate(raw):
            raw["stall_watch"]["repeat_limt"] = 4
        self.assertIn("stall_watch.repeat_limt: unknown key", messages(mutate))

    def test_v6_missing_key(self):
        def mutate(raw):
            del raw["stall_watch"]["max_nudges"]
        self.assertIn("stall_watch.max_nudges: missing", messages(mutate))

    def test_v7_enabled_not_bool(self):
        self.assertIn(
            "stall_watch.enabled: must be true or false",
            messages(set_key("enabled", "yes")),
        )


class StallWatchRolesTest(unittest.TestCase):
    ROLES_MSG = "stall_watch.roles: must be a non-empty list of unique non-empty strings"

    def test_v8_empty_roles(self):
        self.assertIn(self.ROLES_MSG, messages(set_key("roles", [])))

    def test_v8_duplicate_roles(self):
        self.assertIn(self.ROLES_MSG, messages(set_key("roles", ["executor", "executor"])))

    def test_v8_unknown_role(self):
        self.assertIn(
            "stall_watch.roles: unknown role executer",
            messages(set_key("roles", ["executer"])),
        )


class StallWatchIntegersTest(unittest.TestCase):
    def assert_int_message(self, key, value, minimum):
        needle = f"stall_watch.{key}: must be an integer >= {minimum}"
        self.assertIn(needle, messages(set_key(key, value)))

    def test_v9_repeat_limit_below_minimum(self):
        self.assert_int_message("repeat_limit", 1, 2)

    def test_v9_repeat_limit_string(self):
        self.assert_int_message("repeat_limit", "4", 2)

    def test_v9_repeat_window_bool(self):
        self.assert_int_message("repeat_window", True, 2)

    def test_v9_read_only_streak_limit_zero(self):
        self.assert_int_message("read_only_streak_limit", 0, 1)

    def test_v9_max_nudges_negative(self):
        self.assert_int_message("max_nudges", -1, 0)

    def test_v9_state_max_age_hours_zero(self):
        self.assert_int_message("state_max_age_hours", 0, 1)

    def test_v10_repeat_limit_exceeds_window(self):
        self.assertIn(
            "stall_watch.repeat_limit: must not exceed repeat_window",
            messages(set_key("repeat_limit", 41)),
        )


class StallWatchListsTest(unittest.TestCase):
    def list_msg(self, key):
        return (
            f"stall_watch.{key}: must be a non-empty list of unique non-empty strings"
        )

    def test_v11_empty_handback_tools(self):
        self.assertIn(
            self.list_msg("handback_tools"), messages(set_key("handback_tools", []))
        )

    def test_v11_empty_string_in_bash_prefixes(self):
        self.assertIn(
            self.list_msg("read_only_bash_prefixes"),
            messages(set_key("read_only_bash_prefixes", ["cat", ""])),
        )

    def test_v11_change_tools_not_a_list(self):
        self.assertIn(
            self.list_msg("change_tools"), messages(set_key("change_tools", "Edit"))
        )

    def test_v11_empty_ignored_tools_is_allowed(self):
        self.assertNotIn("stall_watch", messages(set_key("ignored_tools", [])))


class StallWatchToolMembershipTest(unittest.TestCase):
    def test_v12_tool_not_of_watched_role(self):
        self.assertIn(
            "stall_watch.read_only_tools: Grepp is not a tool of any watched role",
            messages(set_key("read_only_tools", ["Read", "Grepp"])),
        )


class StallWatchOverlapTest(unittest.TestCase):
    def test_v13_ignored_tool_also_read_only(self):
        self.assertIn(
            "stall_watch.ignored_tools: Read is also in read_only_tools",
            messages(set_key("ignored_tools", ["Monitor", "Read"])),
        )

    def test_v13_change_tool_also_read_only(self):
        self.assertIn(
            "stall_watch.change_tools: Read is also in read_only_tools",
            messages(set_key("change_tools", ["Edit", "Read"])),
        )


class StallWatchZeroNudgesTest(unittest.TestCase):
    def test_v14_zero_nudges_is_valid(self):
        self.assertNotIn("stall_watch", messages(set_key("max_nudges", 0)))


class StallWatchLoadErrorTest(unittest.TestCase):
    def test_v15_load_config_reports_stall_watch_error(self):
        raw = raw_config()
        raw["stall_watch"]["repeat_limit"] = 1
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "routing.json"
            path.write_text(json.dumps(raw), encoding="utf-8")
            with self.assertRaises(rc.ConfigError) as ctx:
                rc.load_config(path)
        self.assertIn("stall_watch.repeat_limit", str(ctx.exception))


def load_with(mutate):
    raw = copy.deepcopy(raw_config())
    mutate(raw)
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "routing.json"
        path.write_text(json.dumps(raw), encoding="utf-8")
        return rc.load_config(path)


class StallWatchCallKeyFieldsTest(unittest.TestCase):
    KEY_MSG = "stall_watch.call_key_fields: "

    def test_c1_shipped_value_loads(self):
        cfg = rc.load_config()
        self.assertEqual(
            cfg.stall_watch.call_key_fields,
            (("Bash", ("command", "timeout", "run_in_background")),),
        )

    def test_c2_frozen_and_plain_data(self):
        sw = rc.load_config().stall_watch
        with self.assertRaises(dataclasses.FrozenInstanceError):
            sw.call_key_fields = ()
        dataclasses.asdict(sw)

    def test_c2_empty_object_loads_as_empty_tuple(self):
        cfg = load_with(set_key("call_key_fields", {}))
        self.assertEqual(cfg.stall_watch.call_key_fields, ())

    def test_c2_pairs_sorted_by_tool_name(self):
        cfg = load_with(
            set_key("call_key_fields", {"Read": ["file_path"], "Bash": ["command"]})
        )
        self.assertEqual(
            cfg.stall_watch.call_key_fields,
            (("Bash", ("command",)), ("Read", ("file_path",))),
        )

    def test_c3_missing_key(self):
        def mutate(raw):
            del raw["stall_watch"]["call_key_fields"]
        self.assertIn(self.KEY_MSG + "missing", messages(mutate))

    def test_c4_not_an_object(self):
        for value in ([], "Bash", None):
            with self.subTest(value=value):
                self.assertIn(
                    self.KEY_MSG + "must be an object",
                    messages(set_key("call_key_fields", value)),
                )

    def test_c5_empty_object_is_accepted(self):
        self.assertNotIn("stall_watch", messages(set_key("call_key_fields", {})))

    def test_c6_tool_not_of_watched_role(self):
        self.assertIn(
            self.KEY_MSG + "Agent is not a tool of any watched role",
            messages(set_key("call_key_fields", {"Agent": ["prompt"]})),
        )

    def test_c7_ignored_tool(self):
        self.assertIn(
            self.KEY_MSG + "Monitor is also in ignored_tools",
            messages(set_key("call_key_fields", {"Monitor": ["command"]})),
        )

    def test_c8_bad_field_lists_for_bash(self):
        bad_values = ([], ["command", "command"], [""], "command", [1])
        for value in bad_values:
            with self.subTest(value=value):
                self.assertIn(
                    "stall_watch.call_key_fields.Bash: must be a non-empty list of unique non-empty strings",
                    messages(set_key("call_key_fields", {"Bash": value})),
                )

    def test_c9_all_errors_collected(self):
        text = messages(set_key("call_key_fields", {"Agent": ["x"], "Bash": []}))
        self.assertIn(self.KEY_MSG + "Agent is not a tool of any watched role", text)
        self.assertIn(
            "stall_watch.call_key_fields.Bash: must be a non-empty list of unique non-empty strings",
            text,
        )

    def test_c10_load_config_reports_call_key_error(self):
        raw = raw_config()
        raw["stall_watch"]["call_key_fields"] = {"Bash": []}
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "routing.json"
            path.write_text(json.dumps(raw), encoding="utf-8")
            with self.assertRaises(rc.ConfigError) as ctx:
                rc.load_config(path)
        self.assertIn("stall_watch.call_key_fields.Bash", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
