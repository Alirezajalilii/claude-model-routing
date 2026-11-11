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

import dispatch_guard as dg  # noqa: E402
import routing_audit as ra  # noqa: E402
import routing_config as rc  # noqa: E402

TS = "2026-10-24T10:00:00.000Z"
SONNET_PROMPT = ("Skills: example-plugin:tdd-workflow\n"
                 "Never consult the advisor.\nImplement the change.")
HAIKU_PROMPT = ("Skills: none\nNever consult the advisor.\n"
                "Plan docs/plans/2026-10-24-x.md task FL-1")
NO_PLAN_PROMPT = "Skills: none\nNever consult the advisor.\nImplement it."


def sid(n: int) -> str:
    """Return a fake session id for fixture number n."""
    return f"00000000-0000-4000-8000-0000000000{n:02d}"


def agent(aid, atype, prompt, calls=(), ts=TS, requests=(), final=None):
    """Describe one subagent for the fixture writer.

    requests: (message id, model, prompt tokens) tuples, one assistant record each.
    final: text of a closing assistant message.
    """
    return {"id": aid, "type": atype, "prompt": prompt, "calls": list(calls),
            "ts": ts, "requests": list(requests), "final": final}


def assistant(ts, content, mid=None, model=None, prompt_tokens=None):
    """Build one assistant transcript record."""
    message = {"role": "assistant", "content": content}
    if mid is not None:
        message["id"] = mid
        message["model"] = model
        message["usage"] = {"input_tokens": prompt_tokens, "output_tokens": 1}
    return {"type": "assistant", "timestamp": ts, "message": message}


def agent_call(tid, subagent_type, **params):
    """Return an Agent tool_use block as the main session would emit it."""
    return {"type": "tool_use", "id": tid, "name": "Agent",
            "input": {"subagent_type": subagent_type, **params}}


def reads(n):
    """Return n Read tool calls."""
    return [("Read", {"file_path": f"/repo/file{i}.md"}) for i in range(n)]


def write_session(root, session_id, agents, project="proj", main_events=()):
    """Write <root>/<project>/<session_id>/subagents and the sibling transcript."""
    base = os.path.join(root, project, session_id)
    sub = os.path.join(base, "subagents")
    os.makedirs(sub, exist_ok=True)
    with open(base + ".jsonl", "w") as f:
        for e in main_events:
            f.write(json.dumps(e) + "\n")
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
        events += [assistant(a["ts"], [], *r) for r in a["requests"]]
        if a["final"] is not None:
            events.append(assistant(a["ts"], [{"type": "text", "text": a["final"]}]))
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
            agent("pppppppppppppp1", "mr:exec-haiku-low",
                  HAIKU_PROMPT),
            agent("qqqqqqqqqqqqqq2", "exec-haiku-low", HAIKU_PROMPT),
        ])
        _, out = self.run_report(base)
        self.assertIn("- exec-haiku-low: 2", out)
        self.assertNotIn("mr:exec-haiku-low: ", out)

    def test_tc2_planner_budget_six_is_flagged(self):
        base = write_session(self.root, sid(2), [
            agent("ccccccccccccccc3", "plan-opus-high",
                  "Skills: none\nPlan the change.", reads(6)),
        ])
        _, out = self.run_report(base)
        self.assertIn("over the planner evidence budget (6 calls)", out)

    def test_tc2_planner_budget_five_is_not_flagged(self):
        base = write_session(self.root, sid(3), [
            agent("ddddddddddddddd4", "plan-opus-high",
                  "Skills: none\nPlan the change.", reads(5)),
        ])
        _, out = self.run_report(base)
        self.assertNotIn("evidence budget", out)

    def test_tc3_scout_missing_skills_and_advisor_line(self):
        base = write_session(self.root, sid(4), [
            agent("eeeeeeeeeeeeeee5", "scout-haiku-med", "Find the files."),
        ])
        _, out = self.run_report(base)
        scout = lines_for(out, "eeeeeeeeee")
        self.assertTrue(any("missing Skills line" in ln for ln in scout), out)
        self.assertTrue(any("no 'Never consult the advisor' line" in ln
                            for ln in scout), out)

    def test_tc3_scoped_every_use_tier_is_flagged(self):
        base = write_session(self.root, sid(11), [
            agent("rrrrrrrrrrrrrrr3", "mr:scout-sonnet-high",
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
            agent("jjjjjjjjjjjjjjj0", "plan-opus-high",
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

    def test_tc4_hook_writes_report_for_non_tier_only_session(self):
        base = write_session(self.root, sid(14), [
            agent("mmmmmmmmmmmmmmm3", "general-purpose", "Do a thing."),
        ])
        event = json.dumps({"session_id": sid(14),
                            "transcript_path": base + ".jsonl"})
        code, out = self.run_hook(event, plugin_data=self.plugin_data)
        self.assertEqual(code, 0)
        self.assertEqual(out, "")
        expected = os.path.join(
            self.audits_dir(),
            f"{datetime.date.today().isoformat()}-00000000.md")
        self.assertTrue(os.path.isfile(expected))

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

    def test_tc5_hook_with_only_allowlisted_agents_writes_nothing(self):
        base = write_session(self.root, sid(16), [
            agent("nnnnnnnnnnnnnnn4", "statusline-setup", "Do a thing."),
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

    def flags_of(self, out):
        return out.split("## Flags", 1)[1]

    def haiku_session(self, n, requests, atype="exec-haiku-med", final="DONE x"):
        return write_session(self.root, sid(n), [
            agent("hh%014d" % n, atype, HAIKU_PROMPT, requests=requests, final=final),
        ])

    def test_tc1_general_purpose_only_is_flagged(self):
        base = write_session(self.root, sid(30), [
            agent("gp00000000000001", "general-purpose", "Do a thing."),
        ])
        _, out = self.run_report(base)
        self.assertIn("- non-tier agent `general-purpose` dispatched", out)

    def test_tc2_fork_next_to_tier_agent_is_flagged(self):
        base = write_session(self.root, sid(31), [
            agent("fk00000000000001", "exec-haiku-low", HAIKU_PROMPT),
            agent("fk00000000000002", "fork", "Do a thing."),
        ])
        _, out = self.run_report(base)
        self.assertIn("- non-tier agent `fork` dispatched", out)

    def test_tc3_allowlisted_agent_gives_no_non_tier_line(self):
        base = write_session(self.root, sid(32), [
            agent("sl00000000000001", "statusline-setup", "Do a thing."),
        ])
        _, out = self.run_report(base)
        self.assertNotIn("non-tier agent", out)

    def test_tc6_haiku_requests_over_limit_deduplicated(self):
        m = "claude-haiku-5-5"
        base = self.haiku_session(33, [("m1", m, 50000), ("m2", m, 320000),
                                       ("m3", m, 350000), ("m2", m, 320000)])
        _, out = self.run_report(base)
        self.assertIn("2 Haiku requests over 300000 prompt tokens (peak 350000)", out)

    def test_tc7_haiku_request_at_limit_is_not_flagged(self):
        base = self.haiku_session(34, [("m1", "claude-haiku-5-5", 300000)])
        _, out = self.run_report(base)
        self.assertNotIn("Haiku requests over", out)

    def test_tc8_sonnet_over_limit_is_not_flagged(self):
        base = self.haiku_session(35, [("m1", "claude-sonnet-5-5", 350000)],
                                  atype="exec-sonnet-high")
        _, out = self.run_report(base)
        self.assertNotIn("Haiku requests over", out)

    def test_tc9_non_tier_haiku_agent_is_flagged(self):
        base = write_session(self.root, sid(36), [
            agent("gh00000000000001", "general-purpose", "Do a thing.",
                  requests=[("m1", "claude-haiku-5-5", 320000)]),
        ])
        _, out = self.run_report(base)
        self.assertIn("1 Haiku requests over 300000 prompt tokens (peak 320000)", out)

    def test_tc10_status_line_check(self):
        good = self.haiku_session(37, [], final="DONE /tmp/h/report.md commits=abc,def")
        _, out = self.run_report(good)
        self.assertNotIn("not a status line", out)
        long_report = "DONE\n" + "x" * 1995
        _, out = self.run_report(self.haiku_session(38, [], final=long_report))
        self.assertIn("reply is not a status line (2000 chars)", out)
        _, out = self.run_report(self.haiku_session(39, [], final="DONE " + "y" * 396))
        self.assertIn("reply is not a status line (401 chars)", out)
        _, out = self.run_report(self.haiku_session(40, [], final="Here is my report"))
        self.assertIn("reply is not a status line", out)
        base = write_session(self.root, sid(41), [
            agent("lg00000000000001", "general-purpose", "Do a thing.",
                  final="Here is my long report\n" * 50),
        ])
        _, out = self.run_report(base)
        self.assertNotIn("not a status line", out)

    def test_tc11_main_session_model_and_effort_params(self):
        block = agent_call("t1", "exec-haiku-low", model="opus", effort="")
        base = write_session(self.root, sid(42), [], main_events=[
            assistant(TS, [block]), assistant(TS, [block])])
        _, out = self.run_report(base)
        self.assertEqual(
            out.count("- main session: Agent call to `exec-haiku-low` passed `model`"), 1)
        self.assertNotIn("passed `effort`", out)

    def test_tc11_effort_param_gives_its_own_line(self):
        block = agent_call("t2", "exec-haiku-low", model="opus", effort="high")
        base = write_session(self.root, sid(43), [], main_events=[assistant(TS, [block])])
        _, out = self.run_report(base)
        lines = [ln for ln in out.splitlines() if ln.startswith("- main session: Agent")]
        self.assertEqual(len(lines), 2)
        self.assertIn("`model`", lines[0])
        self.assertIn("`effort`", lines[1])

    def test_tc12_main_session_model_family(self):
        base = write_session(self.root, sid(44), [], main_events=[
            assistant(TS, [], "a1", "claude-opus-5-5", 1),
            assistant(TS, [], "a2", "claude-sonnet-5-5", 1),
            assistant(TS, [], "a3", "<synthetic>", 1)])
        _, out = self.run_report(base)
        self.assertNotIn("the policy expects", out)
        lines = [ln for ln in out.splitlines() if ln.startswith("info: main session model")]
        self.assertEqual(lines, ["info: main session model claude-opus-5-5 "
                                 "(policy default sonnet)"])
        _, out = self.run_report(write_session(self.root, sid(45), []))
        self.assertNotIn("main session", out)

    def test_tc13_flags_order(self):
        block = agent_call("t3", "exec-haiku-low", model="opus")
        base = write_session(self.root, sid(46), [
            agent("or00000000000001", "scout-haiku-low", "Find it."),
            agent("or00000000000002", "general-purpose", "Do a thing."),
        ], main_events=[assistant(TS, [block])])
        _, out = self.run_report(base)
        flags = self.flags_of(out)
        main_at = flags.index("- main session")
        agent_at = flags.index("missing Skills line")
        tier_at = flags.index("non-tier agent")
        self.assertLess(main_at, agent_at)
        self.assertLess(agent_at, tier_at)

    def test_f8_exempt_planner_reads_do_not_count(self):
        prompt = ("Skills: none\nNever consult the advisor.\n"
                  "Plan from /repo/evidence/scout-1.md")
        exempt = [("Read", {"file_path": p}) for p in (
            "/repo/evidence/scout-1.md",
            "/Users/me/.claude/skills/routing-policy/SKILL.md",
            "/repo/AGENTS.md",
            "/repo/CLAUDE.md",
            "/repo/evidence/scout-1.md",
            "/repo/AGENTS.md",
        )]
        others = [("Grep", {"pattern": f"needle{i}"}) for i in range(5)]
        base = write_session(self.root, sid(47), [
            agent("pe00000000000001", "plan-opus-high", prompt, exempt + others),
        ])
        _, out = self.run_report(base)
        self.assertNotIn("evidence budget", out)

    def test_f8_other_planner_calls_still_count(self):
        prompt = "Skills: none\nNever consult the advisor.\nPlan it."
        base = write_session(self.root, sid(48), [
            agent("pe00000000000002", "plan-opus-high", prompt,
                  [("Grep", {"pattern": f"needle{i}"}) for i in range(6)]),
        ])
        _, out = self.run_report(base)
        self.assertIn("over the planner evidence budget (6 calls)", out)

    def test_f8_long_exempt_skill_path_is_exempt(self):
        long_skill = "/Users/me/" + "nested/" * 15 + "SKILL.md"
        self.assertGreater(len(long_skill), 90)
        prompt = "Skills: none\nNever consult the advisor.\nPlan it."
        calls = [("Read", {"file_path": long_skill})] * 6 + \
            [("Grep", {"pattern": f"needle{i}"}) for i in range(5)]
        base = write_session(self.root, sid(49), [
            agent("pe00000000000003", "plan-opus-high", prompt, calls),
        ])
        _, out = self.run_report(base)
        self.assertNotIn("evidence budget", out)

    def test_tc7_unknown_session_exits_two_with_stderr(self):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = ra.main([sid(99), "--claude-dir", self.claude])
        self.assertEqual(code, 2)
        self.assertEqual(out.getvalue(), "")
        self.assertTrue(err.getvalue().startswith("routing_audit:"))

    def _append_events(self, base, aid, events):
        path = Path(base) / "subagents" / f"agent-{aid}.jsonl"
        with open(path, "a") as f:
            for e in events:
                f.write(json.dumps(e) + "\n")
        return path

    def test_instruction_files_tier_agent_label(self):
        base = write_session(self.root, sid(30), [
            agent("ins0000000000001", "exec-haiku-med", HAIKU_PROMPT),
        ])
        path = self._append_events(base, "ins0000000000001", [
            nested_memory("/work/projects/CLAUDE.md"),
            nested_memory("/work/projects/app/AGENTS.md"),
            nested_memory("/work/projects/CLAUDE.md"),
        ])
        row = ra.summarize([path])[0]
        self.assertEqual(row.instruction_files, (
            "/work/projects/CLAUDE.md",
            "/work/projects/app/AGENTS.md",
            "/work/projects/CLAUDE.md",
        ))
        flags = ra.row_flags(row, rc.load_config())
        self.assertIn("3 instruction-file attachments despite omitClaudeMd "
                      "(2 files: /work/projects/CLAUDE.md, /work/projects/app/AGENTS.md)",
                      flags)

    def test_instruction_files_label_shows_three_then_count(self):
        base = write_session(self.root, sid(31), [
            agent("ins0000000000002", "exec-haiku-med", HAIKU_PROMPT),
        ])
        path = self._append_events(base, "ins0000000000002", [
            nested_memory(f"/work/{name}/CLAUDE.md") for name in "abcde"
        ])
        row = ra.summarize([path])[0]
        flags = ra.row_flags(row, rc.load_config())
        self.assertIn("5 instruction-file attachments despite omitClaudeMd "
                      "(5 files: /work/a/CLAUDE.md, /work/b/CLAUDE.md, /work/c/CLAUDE.md, +2 more)",
                      flags)

    def test_instruction_files_other_attachment_types_no_label(self):
        base = write_session(self.root, sid(32), [
            agent("ins0000000000003", "exec-haiku-med", HAIKU_PROMPT),
        ])
        path = self._append_events(base, "ins0000000000003", [
            {"type": "attachment", "attachment": {"type": "session_context"}},
            {"type": "attachment", "attachment": {"type": "hook_success"}},
        ])
        row = ra.summarize([path])[0]
        self.assertEqual(row.instruction_files, ())
        flags = ra.row_flags(row, rc.load_config())
        self.assertFalse(any("instruction-file" in f for f in flags), flags)

    def test_instruction_files_non_tier_agent_no_label(self):
        base = write_session(self.root, sid(33), [
            agent("ins0000000000004", "general-purpose", "Do a thing."),
        ])
        path = self._append_events(base, "ins0000000000004", [
            nested_memory("/work/projects/CLAUDE.md"),
        ])
        row = ra.summarize([path])[0]
        flags = ra.row_flags(row, rc.load_config())
        self.assertFalse(any("instruction-file" in f for f in flags), flags)

    def test_instruction_files_malformed_entries_ignored(self):
        base = write_session(self.root, sid(34), [
            agent("ins0000000000005", "exec-haiku-med", HAIKU_PROMPT),
        ])
        path = self._append_events(base, "ins0000000000005", [
            {"type": "attachment"},
            {"type": "attachment", "attachment": "x"},
            {"type": "attachment", "attachment": {"type": "nested_memory"}},
            {"type": "attachment",
             "attachment": {"type": "nested_memory", "path": 7}},
        ])
        row = ra.summarize([path])[0]
        self.assertEqual(row.instruction_files, ())
        flags = ra.row_flags(row, rc.load_config())
        self.assertFalse(any("instruction-file" in f for f in flags), flags)


class SkillLoadFlagTest(unittest.TestCase):
    """A tier agent that did not load every skill on its Skills line is flagged."""

    LABEL = "listed skills not loaded"

    def labels(self, prompt, calls=()):
        """Return the skill-load labels that row_flags gives a tier agent row."""
        row = ra.AgentRow(TS, TS, "exec-haiku-low", prompt, tuple(calls),
                          "skl0000000000001")
        flags = ra.row_flags(row, rc.load_config())
        return [flag for flag in flags if flag.startswith(self.LABEL)]

    def test_tc1_all_listed_skills_read_is_not_flagged(self):
        calls = [(TS, "Read", "/x/a/SKILL.md"), (TS, "Read", "/x/b/SKILL.md")]
        self.assertEqual(self.labels("Skills: /x/a/SKILL.md, /x/b/SKILL.md", calls), [])

    def test_tc2_one_unread_listed_skill_is_flagged(self):
        calls = [(TS, "Read", "/x/a/SKILL.md")]
        self.assertEqual(self.labels("Skills: /x/a/SKILL.md, /x/b/SKILL.md", calls),
                         ["listed skills not loaded: 1 of 2"])

    def test_tc3_skills_none_is_not_flagged(self):
        self.assertEqual(self.labels("Skills: none\nNever consult the advisor."), [])

    def test_tc4_skill_tool_by_folder_name_counts_as_loaded(self):
        prompt = "Skills: /x/p/skills/tdd-workflow/SKILL.md"
        self.assertEqual(self.labels(prompt, [(TS, "Skill", "tdd-workflow")]), [])
        self.assertEqual(self.labels(prompt, [(TS, "Skill", "ecc:tdd-workflow")]), [])

    def test_tc5_skill_tool_with_other_name_does_not_count(self):
        calls = [(TS, "Skill", "b")]
        self.assertEqual(self.labels("Skills: /x/a/SKILL.md", calls),
                         ["listed skills not loaded: 1 of 1"])

    def test_tc6_read_of_expanded_home_path_counts_as_loaded(self):
        calls = [(TS, "Read", os.path.expanduser("~/s/a/SKILL.md"))]
        self.assertEqual(self.labels("Skills: ~/s/a/SKILL.md", calls), [])

    def test_tc7_skill_items_lists_paths_or_nothing(self):
        self.assertEqual(dg.skill_items("Skills: /x/a/SKILL.md, /x/b/SKILL.md"),
                         ["/x/a/SKILL.md", "/x/b/SKILL.md"])
        self.assertEqual(dg.skill_items("Skills: none"), [])


def nested_memory(path):
    """Return an attachment transcript entry of type nested_memory for path."""
    return {"type": "attachment", "attachment": {"type": "nested_memory", "path": path}}


if __name__ == "__main__":
    unittest.main()
