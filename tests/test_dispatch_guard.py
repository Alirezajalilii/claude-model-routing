import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import io  # noqa: E402
import os  # noqa: E402
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

OUTPUT_MSG = "has no Output line"
NON_TIER_MSG = "is not a routing tier"
SKILL_PATH_MSG = "not a readable absolute SKILL.md path"

OUT = "Output: /tmp/handoff/report.md"
BOTH_LINES = f"Task T1. Skills: none.\nNever consult the advisor.\n{OUT}"
SKILLS_ONLY = f"Task T1.\nSkills: none.\n{OUT}"
COMPLIANT = f"Skills: none.\nNever consult the advisor.\n{OUT}"


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

    def test_tc2_non_tier_agent_is_denied(self):
        reasons = evaluate(make_event(subagent_type="general-purpose",
                                      prompt=COMPLIANT))
        self.assertEqual(len(reasons), 1, reasons)
        self.assertIn("subagent type 'general-purpose' is not a routing tier",
                      reasons[0])

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
            evaluate(make_event(subagent_type="plan-opus-high", prompt=SKILLS_ONLY)),
            ())

    def test_tc7_model_key_is_reported(self):
        reasons = evaluate(make_event(
            subagent_type="verify-sonnet-high", prompt=BOTH_LINES, model="opus"))
        self.assertTrue(any(MODEL_MSG in r for r in reasons), reasons)

    def test_tc9_inline_skills_and_advisor_pass(self):
        prompt = ("Fast-lane spec (task ID X). Skills: none. "
                  "Never consult the advisor. Output: /tmp/handoff/report.md")
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
        event = make_event(subagent_type=f"{PLUGIN}:plan-opus-high",
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

    def test_other_plugin_prefix_is_denied_as_non_tier(self):
        reasons = evaluate(make_event(
            subagent_type="other-plugin:exec-haiku-low", prompt=COMPLIANT))
        self.assertEqual(len(reasons), 1, reasons)
        self.assertIn(NON_TIER_MSG, reasons[0])

    def test_inline_marketplace_scope_is_recognized(self):
        reasons = evaluate(make_event(
            subagent_type=f"{PLUGIN}@inline:exec-haiku-low", prompt="no lines"))
        self.assertTrue(any(NO_SKILLS_MSG in r for r in reasons), reasons)

    def test_non_planner_skills_none_without_advisor_is_reported(self):
        reasons = evaluate(make_event(
            subagent_type="exec-sonnet-high", prompt=f"Task T1. Skills: none. {OUT}"))
        self.assertTrue(any(ADVISOR_MSG in r for r in reasons), reasons)

    def test_non_planner_with_uppercase_advisor_line_passes(self):
        event = make_event(subagent_type="exec-sonnet-high",
                           prompt=f"Task T1. Skills: none. never consult the ADVISOR. {OUT}")
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

    def test_non_tier_general_purpose_with_model_gets_two_reasons(self):
        reasons = evaluate(make_event(subagent_type="general-purpose",
                                      prompt=COMPLIANT, model="opus"))
        self.assertEqual(len(reasons), 2, reasons)
        self.assertIn(NON_TIER_MSG, reasons[0])
        self.assertIn(MODEL_MSG, reasons[1])

    def test_all_four_violations_are_reported_in_order(self):
        reasons = evaluate(make_event(
            subagent_type="exec-haiku-low", prompt="Task T1.", model="opus"))
        self.assertEqual(len(reasons), 4, reasons)
        self.assertIn(NO_SKILLS_MSG, reasons[0])
        self.assertIn(ADVISOR_MSG, reasons[1])
        self.assertIn(OUTPUT_MSG, reasons[2])
        self.assertIn(MODEL_MSG, reasons[3])

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
        event = make_event(subagent_type="verify-sonnet-high",
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

    def test_four_violations_write_four_lines_in_order(self):
        event = make_event(subagent_type="exec-haiku-low",
                           prompt="Task T1.", model="opus")
        result = run_script(json.dumps(event))
        self.assertEqual(result.returncode, 2)
        lines = result.stderr.splitlines()
        self.assertEqual(len(lines), 4, lines)
        self.assertIn(NO_SKILLS_MSG, lines[0])
        self.assertIn(ADVISOR_MSG, lines[1])
        self.assertIn(OUTPUT_MSG, lines[2])
        self.assertIn(MODEL_MSG, lines[3])

    def test_scoped_planner_exits_zero(self):
        event = make_event(subagent_type=f"{PLUGIN}:plan-opus-high",
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


class TestHandoffRules(unittest.TestCase):
    def reasons(self, agent, prompt=COMPLIANT, **extra):
        return evaluate(make_event(subagent_type=agent, prompt=prompt, **extra))

    def test_tc2_missing_subagent_type_defaults_to_general_purpose(self):
        event = {"tool_name": "Agent", "tool_input": {"prompt": COMPLIANT}}
        reasons = evaluate(event)
        self.assertEqual(len(reasons), 1, reasons)
        self.assertIn("'general-purpose'", reasons[0])

    def test_tc3_fork_is_denied(self):
        reasons = self.reasons("fork")
        self.assertEqual(len(reasons), 1, reasons)
        self.assertIn("'fork'", reasons[0])
        self.assertIn(NON_TIER_MSG, reasons[0])

    def test_tc4_explore_is_denied(self):
        reasons = self.reasons("Explore")
        self.assertEqual(len(reasons), 1, reasons)
        self.assertIn(NON_TIER_MSG, reasons[0])

    def test_tc6_allowlisted_agent_passes(self):
        self.assertEqual(self.reasons("statusline-setup", prompt="do it"), ())

    def test_tc7_allowlisted_agent_with_model_gets_parameter_reason(self):
        reasons = self.reasons("claude-code-guide", model="haiku")
        self.assertEqual(len(reasons), 1, reasons)
        self.assertIn(MODEL_MSG, reasons[0])

    def test_tc9_compliant_tier_passes(self):
        self.assertEqual(self.reasons("exec-haiku-low"), ())

    def test_tc10_missing_output_line_is_reported(self):
        reasons = self.reasons(
            "exec-haiku-low", "Skills: none.\nNever consult the advisor.")
        self.assertEqual(len(reasons), 1, reasons)
        self.assertIn(OUTPUT_MSG, reasons[0])

    def test_tc11_relative_output_path_is_reported(self):
        reasons = self.reasons(
            "exec-haiku-low",
            "Skills: none.\nNever consult the advisor.\nOutput: report.md")
        self.assertEqual(len(reasons), 1, reasons)
        self.assertIn(OUTPUT_MSG, reasons[0])

    def test_tc12_skill_name_instead_of_path_is_reported(self):
        reasons = self.reasons(
            "exec-haiku-low",
            "Skills: tdd-workflow\nNever consult the advisor.\nOutput: /tmp/r.md")
        self.assertEqual(len(reasons), 1, reasons)
        self.assertIn("names 'tdd-workflow'", reasons[0])
        self.assertIn(SKILL_PATH_MSG, reasons[0])

    def skills_prompt(self, value):
        return f"Skills: {value}\nNever consult the advisor.\nOutput: /tmp/r.md"

    def test_tc13_existing_and_missing_skill_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            a = Path(tmp) / "a" / "SKILL.md"
            b = Path(tmp) / "b" / "SKILL.md"
            for f in (a, b):
                f.parent.mkdir()
                f.write_text("x")
            self.assertEqual(
                self.reasons("exec-haiku-low", self.skills_prompt(f"{a}, {b}")), ())
            missing = "/nonexistent/x/SKILL.md"
            reasons = self.reasons(
                "exec-haiku-low", self.skills_prompt(f"{a}, {missing}"))
            self.assertEqual(len(reasons), 1, reasons)
            self.assertIn(missing, reasons[0])

    def test_tc14_non_skill_file_name_is_reported(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = Path(tmp) / "a" / "README.md"
            f.parent.mkdir()
            f.write_text("x")
            reasons = self.reasons("exec-haiku-low", self.skills_prompt(str(f)))
            self.assertEqual(len(reasons), 1, reasons)
            self.assertIn(SKILL_PATH_MSG, reasons[0])

    def test_tc15_home_relative_skill_path_is_accepted(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = Path(tmp) / "skills" / "x" / "SKILL.md"
            f.parent.mkdir(parents=True)
            f.write_text("x")
            with mock.patch.dict(os.environ, {"HOME": tmp}):
                reasons = self.reasons(
                    "exec-haiku-low", self.skills_prompt("~/skills/x/SKILL.md"))
            self.assertEqual(reasons, ())

    def test_tc16_inline_prompt_passes(self):
        prompt = "Skills: none. Never consult the advisor. Output: /tmp/r.md"
        self.assertEqual(self.reasons("exec-haiku-low", prompt), ())

    def test_tc17_uppercase_none_passes(self):
        prompt = "Skills: NONE\nNever consult the advisor.\nOutput: /tmp/r.md"
        self.assertEqual(self.reasons("exec-haiku-low", prompt), ())

    def test_tc18_planner_needs_output_but_no_advisor_line(self):
        prompt = "Skills: none\nOutput: /tmp/docs/plans/x.md"
        self.assertEqual(self.reasons("plan-opus-high", prompt), ())
        reasons = self.reasons("plan-opus-high", "Skills: none")
        self.assertEqual(len(reasons), 1, reasons)
        self.assertIn(OUTPUT_MSG, reasons[0])

    def test_tc19_four_reasons_in_order(self):
        reasons = self.reasons("exec-haiku-low", "Task T1.", model="opus")
        self.assertEqual(len(reasons), 4, reasons)
        for reason, marker in zip(
                reasons, (NO_SKILLS_MSG, ADVISOR_MSG, OUTPUT_MSG, MODEL_MSG)):
            self.assertIn(marker, reason)

    def test_tc24_scoped_tier_with_effort_gets_parameter_reason(self):
        reasons = self.reasons(f"{PLUGIN}:exec-haiku-low", effort="high")
        self.assertEqual(len(reasons), 1, reasons)
        self.assertIn(EFFORT_MSG, reasons[0])

    def test_tc25_backtick_none_with_reason_passes(self):
        prompt = ("`Skills: none` (no applicable skill in the inventory)\n"
                  "Never consult the advisor.\nOutput: /tmp/r.md")
        self.assertEqual(self.reasons("exec-haiku-low", prompt), ())

    def test_tc26_none_followed_by_text_passes(self):
        prompt = ("Skills: none, see the plan\nNever consult the advisor.\n"
                  "Output: /tmp/r.md")
        self.assertEqual(self.reasons("exec-haiku-low", prompt), ())

    def test_tc27_backtick_wrapped_path_is_accepted(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = Path(tmp) / "a" / "SKILL.md"
            f.parent.mkdir()
            f.write_text("x")
            reasons = self.reasons("exec-haiku-low", self.skills_prompt(f"`{f}`"))
            self.assertEqual(reasons, ())


class TestHandoffScript(unittest.TestCase):
    def test_tc20_general_purpose_exits_two(self):
        event = make_event(subagent_type="general-purpose", prompt=COMPLIANT)
        result = run_script(json.dumps(event))
        self.assertEqual(result.returncode, 2)
        self.assertTrue(result.stderr.startswith(f"{PLUGIN} dispatch guard:"),
                        result.stderr)
        self.assertIn(NON_TIER_MSG, result.stderr)

    def test_tc21_allowlisted_agent_exits_zero_silently(self):
        event = make_event(subagent_type="statusline-setup", prompt="do it")
        result = run_script(json.dumps(event))
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stderr, "")

    def test_tc22_missing_config_with_off_policy_agent_fails_open(self):
        with tempfile.TemporaryDirectory() as tmp:
            missing = Path(tmp) / "absent.json"
            event = make_event(subagent_type="general-purpose", prompt="x")
            result = run_script(json.dumps(event), "--config", str(missing))
        self.assertEqual(result.returncode, 0)
        self.assertIn("config unavailable", result.stderr)


if __name__ == "__main__":
    unittest.main()
