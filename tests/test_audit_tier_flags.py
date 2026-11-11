import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import json  # noqa: E402
import tempfile  # noqa: E402
import unittest  # noqa: E402

import routing_audit as ra  # noqa: E402
import routing_config as rc  # noqa: E402

PLAN = "docs/plans/2026-11-12-x.md"
DONE_TEXT = "DONE /x/exec-T1.md commits=abc"
LIMIT_TEXT = "You've hit your weekly limit · resets Nov 11 at 8:30pm (Europe/Berlin)"
LIMIT_LABEL = ("stopped by the usage limit (" + LIMIT_TEXT + "): "
               "dispatch its task again after the reset")
NO_PRIOR_MARK = "exec-sonnet-xhigh with no earlier"
NO_PRIOR_LINE = ("exec-sonnet-xhigh with no earlier exec-haiku-high or exec-sonnet-high run "
                 "of this task (allowed only as a three-yes plan tier or after a failure "
                 "at exec-sonnet-high)")


def prompt_for(task: str, plan: str = PLAN, skills: str = "Skills: none") -> str:
    return f"{skills}\nNever consult the advisor.\nPlan {plan} task {task}"


def make_row(agent_type, task="T1", minute=0, plan=PLAN, prompt=None,
             final_text=DONE_TEXT, final_error=""):
    stamp = f"2026-11-12T10:{minute:02d}:00.000Z"
    return ra.AgentRow(stamp, stamp, agent_type, prompt or prompt_for(task, plan), (),
                       f"short{minute:04d}", final_text=final_text, final_error=final_error)


def no_prior_lines(rows):
    return [line for line in ra.flag_lines(rows, rc.load_config()) if NO_PRIOR_MARK in line]


def labels_of(row):
    return ra.row_flags(row, rc.load_config())


def usage_labels(row):
    return [label for label in labels_of(row) if label.startswith("stopped by the usage limit")]


class XhighPriorRunTest(unittest.TestCase):
    def test_tc1_haiku_high_then_xhigh_is_allowed(self):
        rows = [make_row("exec-haiku-high", "T1", 0), make_row("exec-sonnet-xhigh", "T1", 30)]
        self.assertEqual(no_prior_lines(rows), [])

    def test_tc2_sonnet_high_then_prefixed_xhigh_is_allowed(self):
        rows = [make_row("exec-sonnet-high", "T2", 0), make_row("mr:exec-sonnet-xhigh", "T2", 30)]
        self.assertEqual(no_prior_lines(rows), [])

    def test_tc3_lone_xhigh_is_flagged_with_exact_line(self):
        rows = [make_row("exec-sonnet-xhigh", "T3", 0)]
        self.assertEqual(
            no_prior_lines(rows),
            [f"- exec-sonnet-xhigh `short0000` (10:00 UTC): {NO_PRIOR_LINE}"])

    def test_tc4_prior_sonnet_med_does_not_count(self):
        rows = [make_row("exec-sonnet-med", "T4", 0), make_row("exec-sonnet-xhigh", "T4", 30)]
        self.assertEqual(len(no_prior_lines(rows)), 1)

    def test_tc5_prior_run_of_another_task_does_not_count(self):
        rows = [make_row("exec-haiku-high", "T5", 0), make_row("exec-sonnet-xhigh", "T6", 30)]
        self.assertEqual(len(no_prior_lines(rows)), 1)

    def test_tc6_xhigh_without_task_id_is_flagged(self):
        prompt = f"Skills: none\nNever consult the advisor.\nPlan {PLAN}"
        rows = [make_row("exec-sonnet-xhigh", prompt=prompt, minute=0)]
        self.assertEqual(len(no_prior_lines(rows)), 1)

    def test_tc7_prior_run_of_another_plan_does_not_count(self):
        rows = [
            make_row("exec-haiku-high", "T1", 0, plan="docs/plans/2026-11-12-a.md"),
            make_row("exec-sonnet-xhigh", "T1", 30, plan="docs/plans/2026-11-12-b.md"),
        ]
        self.assertEqual(len(no_prior_lines(rows)), 1)

    def test_tc8_later_prior_run_does_not_count(self):
        rows = [make_row("exec-sonnet-xhigh", "T8", 0), make_row("exec-haiku-high", "T8", 30)]
        lines = no_prior_lines(rows)
        self.assertEqual(len(lines), 1)
        self.assertIn("(10:00 UTC)", lines[0])

    def test_tc9_task_word_case_and_trailing_period_are_handled(self):
        first = f"Skills: none\nNever consult the advisor.\nPlan {PLAN} Task ID: T9."
        second = f"Skills: none\nNever consult the advisor.\nPlan {PLAN} Task ID: T9."
        rows = [
            make_row("exec-sonnet-high", prompt=first, minute=0),
            make_row("exec-sonnet-xhigh", prompt=second, minute=30),
        ]
        self.assertEqual(no_prior_lines(rows), [])


class UsageLimitFlagTest(unittest.TestCase):
    def test_tc10_usage_limit_stop_gets_label_and_no_status_label(self):
        rows = [
            make_row("exec-sonnet-high", "T10", 0),
            make_row("exec-sonnet-xhigh", "T10", 30, final_text=LIMIT_TEXT,
                     final_error="usage_limit_reached"),
        ]
        lines = [line for line in ra.flag_lines(rows, rc.load_config()) if "`short0030`" in line]
        self.assertTrue(any(LIMIT_LABEL in line for line in lines), lines)
        self.assertFalse(any("reply is not a status line" in line for line in lines), lines)

    def test_tc11_five_hour_limit_text_is_flagged(self):
        row = make_row("exec-sonnet-high", final_text="You've hit your 5-hour limit · resets 3pm")
        self.assertEqual(len(usage_labels(row)), 1)

    def test_tc12_error_code_alone_is_flagged(self):
        row = make_row("exec-sonnet-high", final_text="Limit.", final_error="usage_limit_reached")
        self.assertEqual(len(usage_labels(row)), 1)

    def test_tc13_out_of_usage_credits_is_flagged(self):
        row = make_row("exec-sonnet-high", final_text="You're out of usage credits")
        self.assertEqual(len(usage_labels(row)), 1)

    def test_tc14_done_line_has_no_usage_label(self):
        row = make_row("exec-sonnet-high", final_text=DONE_TEXT)
        self.assertEqual(usage_labels(row), [])

    def test_tc15_autocompact_thrashing_is_not_a_usage_limit(self):
        row = make_row("exec-sonnet-high",
                       final_text="Autocompact is thrashing: the context refilled",
                       final_error="autocompact_thrashing")
        self.assertEqual(usage_labels(row), [])
        self.assertTrue(any(label.startswith("reply is not a status line")
                            for label in labels_of(row)))

    def test_tc16_non_tier_agent_gets_usage_label(self):
        row = make_row("general-purpose", final_text=LIMIT_TEXT, final_error="usage_limit_reached")
        self.assertEqual(usage_labels(row), [LIMIT_LABEL])

    def test_tc17_summarize_reads_api_error_and_final_text(self):
        records = [
            {"type": "user", "timestamp": "2026-11-12T10:00:00.000Z",
             "message": {"role": "user", "content": prompt_for("T1")}},
            {"type": "assistant", "timestamp": "2026-11-12T10:01:00.000Z",
             "message": {"role": "assistant", "model": "claude-haiku-5-5",
                         "content": [{"type": "tool_use", "id": "tu1", "name": "Read",
                                      "input": {"file_path": "/x/y.md"}}]}},
            {"type": "assistant", "timestamp": "2026-11-12T10:02:00.000Z",
             "isApiErrorMessage": True, "apiError": "usage_limit_reached",
             "message": {"role": "assistant", "model": "<synthetic>",
                         "content": [{"type": "text", "text": LIMIT_TEXT}]}},
        ]
        with tempfile.TemporaryDirectory() as tmp:
            jsonl = Path(tmp) / "agent-lim0000000000001.jsonl"
            jsonl.write_text("\n".join(json.dumps(r) for r in records) + "\n", encoding="utf-8")
            (Path(tmp) / "agent-lim0000000000001.meta.json").write_text(
                json.dumps({"agentType": "mr:verify-opus-high"}), encoding="utf-8")
            rows = ra.summarize([jsonl])
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].final_text, LIMIT_TEXT)
        self.assertEqual(rows[0].final_error, "usage_limit_reached")

    def test_tc18_guard_haiku_low_done_row_gets_no_task_flags(self):
        rows = [make_row("exec-haiku-low", "T1", 0)]
        lines = ra.flag_lines(rows, rc.load_config())
        self.assertFalse(any(NO_PRIOR_MARK in line for line in lines), lines)
        self.assertFalse(any("stopped by the usage limit" in line for line in lines), lines)


if __name__ == "__main__":
    unittest.main()
