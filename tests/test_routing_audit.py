import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import contextlib  # noqa: E402
import datetime  # noqa: E402
import io  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402
import tempfile  # noqa: E402
import unittest  # noqa: E402
from unittest import mock  # noqa: E402

import routing_audit as ra  # noqa: E402

TS = "2026-10-24T10:00:00.000Z"
SONNET_PROMPT = ("Skills: example-plugin:tdd-workflow\n"
                 "Never consult the advisor.\nImplement the change.")
HAIKU_PROMPT = ("Skills: none\nNever consult the advisor.\n"
                "Plan docs/plans/2026-10-24-x.md task FL-1")
NO_PLAN_PROMPT = "Skills: none\nNever consult the advisor.\nImplement it."


def sid(n: int) -> str:
    """Return a fake session id for fixture number n."""
    return f"00000000-0000-4000-8000-0000000000{n:02d}"


def agent(aid, atype, prompt, calls=(), ts=TS):
    """Describe one subagent for the fixture writer."""
    return {"id": aid, "type": atype, "prompt": prompt,
            "calls": list(calls), "ts": ts}


def reads(n):
    """Return n Read tool calls."""
    return [("Read", {"file_path": f"/repo/file{i}.md"}) for i in range(n)]


def write_session(root, session_id, agents, project="proj"):
    """Write <root>/<project>/<session_id>/subagents and the sibling transcript."""
    base = os.path.join(root, project, session_id)
    sub = os.path.join(base, "subagents")
    os.makedirs(sub, exist_ok=True)
    with open(base + ".jsonl", "w") as f:
        f.write("")
    for a in agents:
        with open(os.path.join(sub, f"agent-{a['id']}.meta.json"), "w") as f:
            json.dump({"agentType": a["type"]}, f)
        blocks = [{"type": "tool_use", "name": n, "input": inp}
                  for n, inp in a["calls"]]
        events = [
            {"type": "user", "timestamp": a["ts"],
             "message": {"role": "user", "content": a["prompt"]}},
            {"type": "assistant", "timestamp": a["ts"],
             "message": {"role": "assistant", "content": blocks}},
        ]
        with open(os.path.join(sub, f"agent-{a['id']}.jsonl"), "w") as f:
            for e in events:
                f.write(json.dumps(e) + "\n")
    return base


def lines_for(out, aid):
    """Return the report lines that mention the short agent id."""
    return [ln for ln in out.splitlines() if aid in ln]


class RoutingAuditTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = tmp.name
        self.claude = os.path.join(self.tmp, "claude")
        self.root = os.path.join(self.claude, "projects")
        self.plugin_data = os.path.join(self.tmp, "plugin-data")
        os.makedirs(self.root)

    def run_report(self, target, extra=()):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = ra.main([target, "--claude-dir", self.claude, *extra])
        return code, out.getvalue()

    def run_hook(self, stdin_text, plugin_data=None):
        env = {k: v for k, v in os.environ.items() if k != "CLAUDE_PLUGIN_DATA"}
        if plugin_data is not None:
            env["CLAUDE_PLUGIN_DATA"] = plugin_data
        out = io.StringIO()
        with mock.patch.dict(os.environ, env, clear=True), \
                mock.patch("sys.stdin", io.StringIO(stdin_text)), \
                contextlib.redirect_stdout(out):
            code = ra.main(["--hook", "--claude-dir", self.claude])
        return code, out.getvalue()

    def audits_dir(self):
        return os.path.join(self.plugin_data, "audits")

    def test_tc1_executor_mix_and_plan_flag(self):
        base = write_session(self.root, sid(1), [
            agent("aaaaaaaaaaaaaaa1", "exec-sonnet-high", SONNET_PROMPT),
            agent("bbbbbbbbbbbbbbb2", "exec-haiku-low", HAIKU_PROMPT),
        ])
        code, out = self.run_report(base)
        self.assertEqual(code, 0)
        self.assertIn("- exec-sonnet-high: 50.0%", out)
        self.assertIn("- Haiku overall: 50.0%", out)
        plan_lines = [ln for ln in out.splitlines() if "no planner plan" in ln]
        self.assertEqual(len(plan_lines), 1)
        self.assertIn("aaaaaaaaaa", plan_lines[0])
        self.assertIn("exec-sonnet-high", plan_lines[0])

    def test_tc1_scoped_and_bare_names_share_one_row(self):
        base = write_session(self.root, sid(10), [
            agent("pppppppppppppp1", "claude-model-routing:exec-haiku-low",
                  HAIKU_PROMPT),
            agent("qqqqqqqqqqqqqq2", "exec-haiku-low", HAIKU_PROMPT),
        ])
        _, out = self.run_report(base)
        self.assertIn("- exec-haiku-low: 2", out)
        self.assertNotIn("claude-model-routing:exec-haiku-low: ", out)

    def test_tc2_planner_budget_six_is_flagged(self):
        base = write_session(self.root, sid(2), [
            agent("ccccccccccccccc3", "planner-opus-high",
                  "Skills: none\nPlan the change.", reads(6)),
        ])
        _, out = self.run_report(base)
        self.assertIn("over the planner evidence budget (6 calls)", out)

    def test_tc2_planner_budget_five_is_not_flagged(self):
        base = write_session(self.root, sid(3), [
            agent("ddddddddddddddd4", "planner-opus-high",
                  "Skills: none\nPlan the change.", reads(5)),
        ])
        _, out = self.run_report(base)
        self.assertNotIn("evidence budget", out)

    def test_tc3_scout_missing_skills_and_advisor_line(self):
        base = write_session(self.root, sid(4), [
            agent("eeeeeeeeeeeeeee5", "scout-haiku-medium", "Find the files."),
        ])
        _, out = self.run_report(base)
        scout = lines_for(out, "eeeeeeeeee")
        self.assertTrue(any("missing Skills line" in ln for ln in scout), out)
        self.assertTrue(any("no 'Never consult the advisor' line" in ln
                            for ln in scout), out)

    def test_tc3_scoped_every_use_tier_is_flagged(self):
        base = write_session(self.root, sid(11), [
            agent("rrrrrrrrrrrrrrr3", "claude-model-routing:scout-sonnet-high",
                  "Skills: none\nNever consult the advisor.\nFind it."),
        ])
        _, out = self.run_report(base)
        self.assertTrue(any("every-use tier" in ln and "scout-sonnet-high" in ln
                            for ln in out.splitlines()), out)

    def test_tc4_non_tier_agent_flag_when_tier_dispatched(self):
        base = write_session(self.root, sid(12), [
            agent("sssssssssssssss4", "exec-haiku-low", HAIKU_PROMPT),
            agent("tttttttttttttt5", "general-purpose", "Do a thing."),
        ])
        _, out = self.run_report(base)
        self.assertIn("non-tier agent `general-purpose` dispatched", out)

    def test_tc5_executor_plan_path_flag(self):
        without = write_session(self.root, sid(5), [
            agent("fffffffffffffff6", "exec-haiku-low", NO_PLAN_PROMPT),
        ])
        with_plan = write_session(self.root, sid(6), [
            agent("gggggggggggggggg7", "exec-haiku-low", HAIKU_PROMPT),
        ])
        _, out_without = self.run_report(without)
        _, out_with = self.run_report(with_plan)
        self.assertIn("no planner plan", out_without)
        self.assertNotIn("no planner plan", out_with)

    def test_tc4_jsonl_target_matches_dir_target(self):
        base = write_session(self.root, sid(20), [
            agent("hhhhhhhhhhhhhhh8", "exec-haiku-low", HAIKU_PROMPT),
        ])
        _, from_dir = self.run_report(base)
        _, from_jsonl = self.run_report(base + ".jsonl")
        self.assertEqual(from_dir, from_jsonl)

    def test_session_id_target_matches_dir_target(self):
        base = write_session(self.root, sid(21), [
            agent("iiiiiiiiiiiiiii9", "exec-haiku-low", HAIKU_PROMPT),
        ])
        _, from_dir = self.run_report(base)
        _, from_id = self.run_report(sid(21))
        self.assertEqual(from_dir, from_id)

    def test_verbose_lists_tool_calls(self):
        base = write_session(self.root, sid(22), [
            agent("jjjjjjjjjjjjjjj0", "planner-opus-high",
                  "Skills: none\nPlan.", reads(2)),
        ])
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            ra.main([base, "--claude-dir", self.claude, "-v"])
        self.assertIn("calls=", out.getvalue())
        self.assertIn("Read /repo/file1.md", out.getvalue())

    def test_tc6_hook_writes_report_when_tier_dispatched(self):
        base = write_session(self.root, sid(7), [
            agent("kkkkkkkkkkkkkkk1", "exec-haiku-low", HAIKU_PROMPT),
        ])
        event = json.dumps({"session_id": sid(7),
                            "transcript_path": base + ".jsonl"})
        code, out = self.run_hook(event, plugin_data=self.plugin_data)
        expected = os.path.join(
            self.audits_dir(),
            f"{datetime.date.today().isoformat()}-00000000.md")
        self.assertEqual(code, 0)
        self.assertEqual(out, "")
        self.assertTrue(os.path.isfile(expected))
        with open(expected) as f:
            self.assertIn("Routing audit", f.read())

    def test_tc6_hook_without_plugin_data_writes_nothing(self):
        base = write_session(self.root, sid(13), [
            agent("llllllllllllllll2", "exec-haiku-low", HAIKU_PROMPT),
        ])
        event = json.dumps({"session_id": sid(13),
                            "transcript_path": base + ".jsonl"})
        code, out = self.run_hook(event, plugin_data=None)
        self.assertEqual(code, 0)
        self.assertEqual(out, "")
        self.assertFalse(os.path.exists(self.audits_dir()))

    def test_tc6_hook_without_tier_dispatch_writes_nothing(self):
        base = write_session(self.root, sid(14), [
            agent("mmmmmmmmmmmmmmm3", "general-purpose", "Do a thing."),
        ])
        event = json.dumps({"session_id": sid(14),
                            "transcript_path": base + ".jsonl"})
        code, out = self.run_hook(event, plugin_data=self.plugin_data)
        self.assertEqual(code, 0)
        self.assertEqual(out, "")
        self.assertFalse(os.path.exists(self.audits_dir()))

    def test_tc6_hook_without_subagents_writes_nothing(self):
        transcript = os.path.join(self.root, "proj", "nosub.jsonl")
        os.makedirs(os.path.dirname(transcript))
        with open(transcript, "w") as f:
            f.write("")
        event = json.dumps({"session_id": sid(15),
                            "transcript_path": transcript})
        code, out = self.run_hook(event, plugin_data=self.plugin_data)
        self.assertEqual(code, 0)
        self.assertEqual(out, "")
        self.assertFalse(os.path.exists(self.audits_dir()))

    def test_hook_with_only_non_tier_agents_writes_nothing(self):
        base = write_session(self.root, sid(16), [
            agent("nnnnnnnnnnnnnnn4", "general-purpose", "Do a thing."),
        ])
        event = json.dumps({"session_id": sid(16),
                            "transcript_path": base + ".jsonl"})
        code, out = self.run_hook(event, plugin_data=self.plugin_data)
        self.assertEqual(code, 0)
        self.assertEqual(out, "")
        self.assertFalse(os.path.exists(self.audits_dir()))

    def test_tc6_hook_malformed_stdin_exits_zero(self):
        code, out = self.run_hook("not json {", plugin_data=self.plugin_data)
        self.assertEqual(code, 0)
        self.assertEqual(out, "")
        code, out = self.run_hook("[1]", plugin_data=self.plugin_data)
        self.assertEqual(code, 0)
        self.assertFalse(os.path.exists(self.audits_dir()))

    def test_tc7_unknown_session_exits_two_with_stderr(self):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = ra.main([sid(99), "--claude-dir", self.claude])
        self.assertEqual(code, 2)
        self.assertEqual(out.getvalue(), "")
        self.assertTrue(err.getvalue().startswith("routing_audit:"))


if __name__ == "__main__":
    unittest.main()
