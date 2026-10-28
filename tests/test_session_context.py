import dataclasses
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import routing_config as rc  # noqa: E402
import session_context as sc  # noqa: E402

SESSION_ID = "00000000-0000-4000-8000-000000000001"
SPAWN_OK = {"CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH": "1"}


def fixture_config():
    base = rc.load_config()
    parts = (
        rc.DispatcherPart(title="Alpha", sections=("sec-a",)),
        rc.DispatcherPart(title="Beta", sections=("sec-b", "sec-c")),
    )
    return dataclasses.replace(base, dispatcher_parts=parts)


def event_json(**fields):
    return json.dumps(fields)


class FixtureTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.sections = Path(self._tmp.name)
        (self.sections / "sec-a.md").write_text("Alpha body for {{plugin_name}}.", encoding="utf-8")
        (self.sections / "sec-b.md").write_text("Beta body.", encoding="utf-8")
        (self.sections / "sec-c.md").write_text("Gamma body.", encoding="utf-8")
        self.config = fixture_config()

    def run_main(self, part, stdin_text="{}", env=None):
        out, err = io.StringIO(), io.StringIO()
        code = sc.main(
            ["--part", str(part)],
            stdin=io.StringIO(stdin_text),
            stdout=out,
            stderr=err,
            env=SPAWN_OK if env is None else env,
            config=self.config,
            sections_dir=self.sections,
        )
        return code, out.getvalue(), err.getvalue()


class MainOutputTest(FixtureTestCase):
    def test_part_one_prints_session_context_json(self):
        stdin = event_json(session_id=SESSION_ID, source="startup")
        code, out, _ = self.run_main(1, stdin)
        self.assertEqual(code, 0)
        payload = json.loads(out)
        hook = payload["hookSpecificOutput"]
        self.assertEqual(hook["hookEventName"], "SessionStart")
        self.assertTrue(
            hook["additionalContext"].startswith(
                "# model-routing policy, part 1 of 2:"
            )
        )
        self.assertIn(f"Session id: `{SESSION_ID}`", hook["additionalContext"])
        self.assertNotIn("Configuration warnings", hook["additionalContext"])

    def test_part_two_has_no_session_or_warning_sections(self):
        env = {"CLAUDE_CODE_EFFORT_LEVEL": "max"}
        stdin = event_json(session_id=SESSION_ID)
        code, out, _ = self.run_main(2, stdin, env=env)
        self.assertEqual(code, 0)
        text = json.loads(out)["hookSpecificOutput"]["additionalContext"]
        self.assertTrue(text.startswith("# model-routing policy, part 2 of 2: Beta"))
        self.assertNotIn("## Session", text)
        self.assertNotIn("## Configuration warnings", text)

    def test_part_one_appends_warnings_after_session(self):
        env = {"CLAUDE_CODE_EFFORT_LEVEL": "max"}
        stdin = event_json(session_id=SESSION_ID)
        _, out, _ = self.run_main(1, stdin, env=env)
        text = json.loads(out)["hookSpecificOutput"]["additionalContext"]
        self.assertIn("## Session", text)
        self.assertIn("## Configuration warnings", text)
        self.assertLess(text.index("## Session"), text.index("## Configuration warnings"))

    def test_part_out_of_range_fails_with_stderr(self):
        code, out, err = self.run_main(3)
        self.assertEqual(code, 1)
        self.assertEqual(out, "")
        self.assertTrue(err.startswith("session_context:"))

    def test_tier_agent_type_prints_nothing_scoped(self):
        stdin = event_json(agent_type="model-routing:exec-haiku-low")
        code, out, _ = self.run_main(1, stdin)
        self.assertEqual(code, 0)
        self.assertEqual(out, "")

    def test_tier_agent_type_prints_nothing_bare(self):
        stdin = event_json(agent_type="exec-haiku-low")
        code, out, _ = self.run_main(1, stdin)
        self.assertEqual(code, 0)
        self.assertEqual(out, "")

    def test_non_tier_agent_type_prints_context(self):
        stdin = event_json(agent_type="general-purpose")
        code, out, _ = self.run_main(1, stdin)
        self.assertEqual(code, 0)
        self.assertIn("additionalContext", json.loads(out)["hookSpecificOutput"])

    def test_invalid_stdin_prints_context_without_session_line(self):
        code, out, _ = self.run_main(1, "not json {")
        self.assertEqual(code, 0)
        text = json.loads(out)["hookSpecificOutput"]["additionalContext"]
        self.assertTrue(text.startswith("# model-routing policy, part 1 of 2:"))
        self.assertNotIn("## Session", text)

    def test_oversized_part_is_replaced_by_skill_pointer(self):
        (self.sections / "sec-a.md").write_text("x" * 12000, encoding="utf-8")
        code, out, _ = self.run_main(1, event_json(session_id=SESSION_ID))
        self.assertEqual(code, 0)
        text = json.loads(out)["hookSpecificOutput"]["additionalContext"]
        self.assertLess(len(text), 10000)
        self.assertIn("model-routing:routing-policy", text)
        self.assertIn("sec-a", text)
        self.assertNotIn("x" * 100, text)


class ParseEventTest(unittest.TestCase):
    def test_invalid_json_gives_empty_dict(self):
        self.assertEqual(sc.parse_event("{broken"), {})

    def test_non_dict_json_gives_empty_dict(self):
        self.assertEqual(sc.parse_event("[1, 2]"), {})

    def test_dict_json_is_returned(self):
        self.assertEqual(sc.parse_event('{"source": "startup"}'), {"source": "startup"})


class CollectWarningsTest(unittest.TestCase):
    def setUp(self):
        self.config = fixture_config()

    def warnings(self, env, event=None):
        return sc.collect_warnings(env, event or {}, self.config)

    def test_no_warnings_on_clean_environment(self):
        self.assertEqual(self.warnings(SPAWN_OK), [])

    def test_effort_level_warning_names_value(self):
        found = self.warnings({**SPAWN_OK, "CLAUDE_CODE_EFFORT_LEVEL": "max"})
        self.assertEqual(len(found), 1)
        self.assertIn("CLAUDE_CODE_EFFORT_LEVEL", found[0])
        self.assertIn("max", found[0])

    def test_subagent_model_warning(self):
        found = self.warnings({**SPAWN_OK, "CLAUDE_CODE_SUBAGENT_MODEL": "x"})
        self.assertEqual(len(found), 1)
        self.assertIn("CLAUDE_CODE_SUBAGENT_MODEL", found[0])

    def test_force_flag_warns_when_truthy(self):
        found = self.warnings({**SPAWN_OK, "CLAUDE_CODE_SUBAGENT_MODEL_FORCE": "1"})
        self.assertEqual(len(found), 1)
        self.assertIn("CLAUDE_CODE_SUBAGENT_MODEL_FORCE", found[0])

    def test_force_flag_silent_for_zero_and_false(self):
        for value in ("0", "false", "FALSE"):
            with self.subTest(value=value):
                env = {**SPAWN_OK, "CLAUDE_CODE_SUBAGENT_MODEL_FORCE": value}
                self.assertEqual(self.warnings(env), [])

    def test_spawn_depth_unset_warns_not_set(self):
        found = self.warnings({})
        self.assertEqual(len(found), 1)
        self.assertIn("CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH", found[0])
        self.assertIn("not set", found[0])

    def test_spawn_depth_two_warns_with_value(self):
        found = self.warnings({"CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH": "2"})
        self.assertEqual(len(found), 1)
        self.assertIn("`2`", found[0])

    def test_spawn_depth_one_is_silent(self):
        self.assertEqual(self.warnings(SPAWN_OK), [])

    def test_model_mismatch_warns(self):
        found = self.warnings(SPAWN_OK, {"model": "claude-opus-5-5"})
        self.assertEqual(len(found), 1)
        self.assertIn("default main-session model is sonnet", found[0])
        self.assertIn("this session runs on claude-opus-5-5", found[0])
        self.assertIn("Do not ask the user to switch models.", found[0])

    def test_matching_model_with_context_suffix_is_silent(self):
        self.assertEqual(self.warnings(SPAWN_OK, {"model": "claude-sonnet-5-5[1m]"}), [])

    def test_unknown_model_family_is_silent(self):
        self.assertEqual(self.warnings(SPAWN_OK, {"model": "mystery-model"}), [])

    def test_absent_model_is_silent(self):
        self.assertEqual(self.warnings(SPAWN_OK, {}), [])

    def test_warnings_keep_documented_order(self):
        env = {
            "CLAUDE_CODE_EFFORT_LEVEL": "max",
            "CLAUDE_CODE_SUBAGENT_MODEL": "x",
            "CLAUDE_CODE_SUBAGENT_MODEL_FORCE": "1",
            "CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH": "2",
        }
        found = self.warnings(env, {"model": "claude-opus-5-5"})
        keys = [
            "CLAUDE_CODE_EFFORT_LEVEL",
            "CLAUDE_CODE_SUBAGENT_MODEL`",
            "CLAUDE_CODE_SUBAGENT_MODEL_FORCE",
            "CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH",
            "claude-opus-5-5",
        ]
        self.assertEqual(len(found), len(keys))
        for line, key in zip(found, keys):
            self.assertIn(key, line)


class BuildContextTest(FixtureTestCase):
    def test_part_one_without_session_or_warnings_has_only_policy(self):
        text = sc.build_context(self.config, 1, {}, SPAWN_OK, sections_dir=self.sections)
        self.assertNotIn("## Session", text)
        self.assertNotIn("## Configuration warnings", text)
        self.assertIn("Alpha body for model-routing.", text)

    def test_session_line_names_routing_tools(self):
        text = sc.build_context(
            self.config, 1, {"session_id": SESSION_ID}, SPAWN_OK, sections_dir=self.sections
        )
        self.assertIn(f"- Session id: `{SESSION_ID}`", text)
        self.assertIn("model-routing-usage", text)
        self.assertIn("model-routing-audit", text)

    def test_warnings_are_bulleted(self):
        text = sc.build_context(
            self.config, 1, {}, {"CLAUDE_CODE_EFFORT_LEVEL": "max"}, sections_dir=self.sections
        )
        self.assertIn("## Configuration warnings\n- `CLAUDE_CODE_EFFORT_LEVEL`", text)

    def test_part_two_renders_its_own_sections(self):
        text = sc.build_context(self.config, 2, {}, SPAWN_OK, sections_dir=self.sections)
        self.assertIn("Beta body.", text)
        self.assertIn("Gamma body.", text)
        self.assertNotIn("Alpha body", text)

    def test_oversized_part_one_keeps_session_and_warning_blocks(self):
        (self.sections / "sec-a.md").write_text("x" * 12000, encoding="utf-8")
        text = sc.build_context(
            self.config,
            1,
            {"session_id": SESSION_ID, "model": "claude-opus-5-5"},
            SPAWN_OK,
            sections_dir=self.sections,
        )
        self.assertIn("model-routing:routing-policy", text)
        self.assertIn("## Session", text)
        self.assertIn("## Configuration warnings", text)
        self.assertIn("this session runs on claude-opus-5-5", text)
        self.assertNotIn("x" * 100, text)
        self.assertLess(len(text), 9900)

    def test_oversized_part_two_is_pointer_only(self):
        (self.sections / "sec-b.md").write_text("y" * 12000, encoding="utf-8")
        text = sc.build_context(
            self.config,
            2,
            {"session_id": SESSION_ID, "model": "claude-opus-5-5"},
            SPAWN_OK,
            sections_dir=self.sections,
        )
        self.assertIn("model-routing:routing-policy", text)
        self.assertNotIn("## Session", text)
        self.assertNotIn("## Configuration warnings", text)

    def test_mismatch_keeps_policy_then_session_then_warnings(self):
        text = sc.build_context(
            self.config,
            1,
            {"session_id": SESSION_ID, "model": "claude-opus-5-5"},
            SPAWN_OK,
            sections_dir=self.sections,
        )
        self.assertIn("Alpha body for model-routing.", text)
        self.assertLess(text.index("Alpha body"), text.index("## Session"))
        self.assertLess(text.index("## Session"), text.index("## Configuration warnings"))
        self.assertIn("this session runs on claude-opus-5-5", text)


if __name__ == "__main__":
    unittest.main()
