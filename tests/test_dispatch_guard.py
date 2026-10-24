import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import io  # noqa: E402
import json  # noqa: E402
import subprocess  # noqa: E402
import tempfile  # noqa: E402
import unittest  # noqa: E402
from unittest import mock  # noqa: E402

import dispatch_guard as dg  # noqa: E402
import routing_config as rc  # noqa: E402

SCRIPT = ROOT / "scripts" / "dispatch_guard.py"
CONFIG = rc.load_config()
PLUGIN = CONFIG.plugin_name

NO_SKILLS_MSG = "has no Skills line"
ADVISOR_MSG = "Never consult the advisor"
MODEL_MSG = "parameter 'model'"
EFFORT_MSG = "parameter 'effort'"

BOTH_LINES = "Task T1. Skills: none.\nNever consult the advisor."
SKILLS_ONLY = "Task T1.\nSkills: none."


def make_event(tool_name="Agent", subagent_type="exec-haiku-low",
               prompt=BOTH_LINES, **extra):
    tool_input = {"subagent_type": subagent_type, "prompt": prompt}
    tool_input.update(extra)
    return {"tool_name": tool_name, "tool_input": tool_input}


def evaluate(event):
    return dg.evaluate(event, CONFIG)


def run_script(stdin_text, *args):
    return subprocess.run(
        [sys.executable, "-B", str(SCRIPT), *args],
        input=stdin_text,
        capture_output=True,
        text=True,
        timeout=30,
    )


class TestEvaluate(unittest.TestCase):
    def test_tc1_non_agent_tool_is_ignored(self):
        event = make_event(tool_name="Bash", subagent_type="exec-haiku-low",
                           prompt="no lines at all")
        self.assertEqual(evaluate(event), ())

    def test_tc2_non_tier_agent_is_ignored(self):
        event = make_event(subagent_type="general-purpose", prompt="no skills")
        self.assertEqual(evaluate(event), ())

    def test_tc3_compliant_executor_passes(self):
        self.assertEqual(evaluate(make_event(prompt=BOTH_LINES)), ())

    def test_tc4_missing_skills_line_is_reported(self):
        reasons = evaluate(make_event(
            subagent_type="exec-sonnet-high",
            prompt="Task T1.\nNever consult the advisor."))
        self.assertTrue(any(NO_SKILLS_MSG in r for r in reasons), reasons)

    def test_tc5_non_planner_without_advisor_line_is_reported(self):
        reasons = evaluate(make_event(
            subagent_type="scout-haiku-low", prompt=SKILLS_ONLY))
        self.assertTrue(any(ADVISOR_MSG in r for r in reasons), reasons)

    def test_tc6_planner_needs_no_advisor_line(self):
        self.assertEqual(
            evaluate(make_event(subagent_type="planner-opus-high", prompt=SKILLS_ONLY)),
            ())

    def test_tc7_model_key_is_reported(self):
        reasons = evaluate(make_event(
            subagent_type="verifier-sonnet-high", prompt=BOTH_LINES, model="opus"))
        self.assertTrue(any(MODEL_MSG in r for r in reasons), reasons)

    def test_tc9_inline_skills_and_advisor_pass(self):
        prompt = ("Fast-lane spec (task ID X). Skills: none. "
                  "Never consult the advisor.")
        self.assertEqual(evaluate(make_event(prompt=prompt)), ())

    def test_tc10_task_tool_name_is_guarded(self):
        reasons = evaluate(make_event(
            tool_name="Task", subagent_type="exec-haiku-low",
            prompt="Never consult the advisor."))
        self.assertTrue(any(NO_SKILLS_MSG in r for r in reasons), reasons)

    def test_tc11_empty_effort_is_not_a_violation(self):
        self.assertEqual(evaluate(make_event(prompt=BOTH_LINES, effort="")), ())

    def test_malformed_shape_does_not_raise(self):
        self.assertEqual(
            evaluate({"tool_name": "Agent", "tool_input": "x"}), ())

    def test_scoped_planner_without_advisor_line_passes(self):
        event = make_event(subagent_type=f"{PLUGIN}:planner-opus-high",
                           prompt=SKILLS_ONLY)
        self.assertEqual(evaluate(event), ())

    def test_scoped_executor_without_skills_is_reported(self):
        reasons = evaluate(make_event(
            subagent_type=f"{PLUGIN}:exec-haiku-low", prompt="Never consult the advisor."))
        self.assertTrue(any(NO_SKILLS_MSG in r for r in reasons), reasons)

    def test_bare_executor_without_skills_is_reported(self):
        reasons = evaluate(make_event(
            subagent_type="exec-haiku-low", prompt="Never consult the advisor."))
        self.assertTrue(any(NO_SKILLS_MSG in r for r in reasons), reasons)

    def test_other_plugin_prefix_is_not_a_tier(self):
        event = make_event(subagent_type="other-plugin:exec-haiku-low",
                           prompt="no lines")
        self.assertEqual(evaluate(event), ())

    def test_inline_marketplace_scope_is_recognized(self):
        reasons = evaluate(make_event(
            subagent_type=f"{PLUGIN}@inline:exec-haiku-low", prompt="no lines"))
        self.assertTrue(any(NO_SKILLS_MSG in r for r in reasons), reasons)

    def test_non_planner_skills_none_without_advisor_is_reported(self):
        reasons = evaluate(make_event(
            subagent_type="exec-sonnet-high", prompt="Task T1. Skills: none."))
        self.assertTrue(any(ADVISOR_MSG in r for r in reasons), reasons)

    def test_non_planner_with_uppercase_advisor_line_passes(self):
        event = make_event(subagent_type="exec-sonnet-high",
                           prompt="Task T1. Skills: none. never consult the ADVISOR.")
        self.assertEqual(evaluate(event), ())

    def test_tier_with_model_sonnet_is_reported(self):
        reasons = evaluate(make_event(
            subagent_type="exec-sonnet-high", prompt=BOTH_LINES, model="sonnet"))
        self.assertTrue(any(MODEL_MSG in r for r in reasons), reasons)

    def test_empty_model_is_not_a_violation(self):
        self.assertEqual(evaluate(make_event(prompt=BOTH_LINES, model="")), ())

    def test_whitespace_model_is_not_a_violation(self):
        self.assertEqual(evaluate(make_event(prompt=BOTH_LINES, model="   ")), ())

    def test_effort_high_is_reported(self):
        reasons = evaluate(make_event(
            subagent_type="exec-sonnet-high", prompt=BOTH_LINES, effort="high"))
        self.assertTrue(any(EFFORT_MSG in r for r in reasons), reasons)

    def test_non_tier_general_purpose_with_model_passes(self):
        event = make_event(subagent_type="general-purpose", prompt="no lines",
                           model="opus")
        self.assertEqual(evaluate(event), ())

    def test_all_three_violations_are_reported_in_order(self):
        reasons = evaluate(make_event(
            subagent_type="exec-haiku-low", prompt="Task T1.", model="opus"))
        self.assertEqual(len(reasons), 3, reasons)
        self.assertIn(NO_SKILLS_MSG, reasons[0])
        self.assertIn(ADVISOR_MSG, reasons[1])
        self.assertIn(MODEL_MSG, reasons[2])

    def test_skills_with_only_spaces_is_reported(self):
        reasons = evaluate(make_event(
            subagent_type="exec-haiku-low",
            prompt="Skills:   \nNever consult the advisor."))
        self.assertTrue(any(NO_SKILLS_MSG in r for r in reasons), reasons)

    def test_non_dict_tool_input_is_ignored(self):
        event = {"tool_name": "Agent", "tool_input": ["exec-haiku-low"]}
        self.assertEqual(evaluate(event), ())


class TestMainInProcess(unittest.TestCase):
    def test_evaluate_error_fails_open(self):
        stderr = io.StringIO()
        with mock.patch.object(dg, "evaluate", side_effect=RuntimeError("boom")):
            code = dg.main(argv=[], stdin=io.StringIO(json.dumps(make_event())),
                           stderr=stderr)
        self.assertEqual(code, 0)
        self.assertEqual(stderr.getvalue(), "")


class TestScriptExitCodes(unittest.TestCase):
    def test_tc1_bash_tool_exits_zero_silently(self):
        event = make_event(tool_name="Bash", prompt="")
        result = run_script(json.dumps(event))
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stderr, "")

    def test_tc4_missing_skills_exits_two(self):
        event = make_event(subagent_type="exec-sonnet-high",
                           prompt="Task T1.\nNever consult the advisor.")
        result = run_script(json.dumps(event))
        self.assertEqual(result.returncode, 2)
        self.assertIn(NO_SKILLS_MSG, result.stderr)
        self.assertTrue(result.stderr.startswith(f"{PLUGIN} dispatch guard:"),
                        result.stderr)

    def test_tc5_missing_advisor_exits_two(self):
        event = make_event(subagent_type="scout-haiku-low", prompt=SKILLS_ONLY)
        result = run_script(json.dumps(event))
        self.assertEqual(result.returncode, 2)
        self.assertIn(ADVISOR_MSG, result.stderr)

    def test_tc7_model_key_exits_two(self):
        event = make_event(subagent_type="verifier-sonnet-high",
                           prompt=BOTH_LINES, model="opus")
        result = run_script(json.dumps(event))
        self.assertEqual(result.returncode, 2)
        self.assertIn(MODEL_MSG, result.stderr)

    def test_tc8_malformed_json_exits_zero(self):
        result = run_script("{not json")
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")

    def test_non_dict_json_exits_zero(self):
        result = run_script("[1, 2, 3]")
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stderr, "")

    def test_tc10_task_tool_missing_skills_exits_two(self):
        event = make_event(tool_name="Task", subagent_type="exec-haiku-low",
                           prompt="Never consult the advisor.")
        result = run_script(json.dumps(event))
        self.assertEqual(result.returncode, 2)
        self.assertIn(NO_SKILLS_MSG, result.stderr)

    def test_tc11_empty_effort_exits_zero(self):
        event = make_event(prompt=BOTH_LINES, effort="")
        result = run_script(json.dumps(event))
        self.assertEqual(result.returncode, 0)

    def test_three_violations_write_three_lines_in_order(self):
        event = make_event(subagent_type="exec-haiku-low",
                           prompt="Task T1.", model="opus")
        result = run_script(json.dumps(event))
        self.assertEqual(result.returncode, 2)
        lines = result.stderr.splitlines()
        self.assertEqual(len(lines), 3, lines)
        self.assertIn(NO_SKILLS_MSG, lines[0])
        self.assertIn(ADVISOR_MSG, lines[1])
        self.assertIn(MODEL_MSG, lines[2])

    def test_scoped_planner_exits_zero(self):
        event = make_event(subagent_type=f"{PLUGIN}:planner-opus-high",
                           prompt=SKILLS_ONLY)
        result = run_script(json.dumps(event))
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stderr, "")

    def test_missing_config_fails_open(self):
        with tempfile.TemporaryDirectory() as tmp:
            missing = Path(tmp) / "absent.json"
            result = run_script(json.dumps(make_event(prompt="no lines")),
                                "--config", str(missing))
        self.assertEqual(result.returncode, 0)
        self.assertIn("config unavailable", result.stderr)


if __name__ == "__main__":
    unittest.main()
