import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import io  # noqa: E402
import json  # noqa: E402
import tempfile  # noqa: E402
import unittest  # noqa: E402
from contextlib import redirect_stderr, redirect_stdout  # noqa: E402

import subagent_usage as su  # noqa: E402

SID = "00000000-0000-4000-8000-000000000001"
MISSING = "00000000-0000-4000-8000-000000000099"
PLUGIN_TYPE = "model-routing:exec-haiku-low"
BARE_TYPE = "exec-haiku-low"


def usage(inp, out):
    return {
        "input_tokens": inp,
        "output_tokens": out,
        "cache_creation_input_tokens": 0,
        "cache_read_input_tokens": 0,
    }


def assistant(msg_id, content=(), model="claude-haiku-5-5", tokens=None):
    message = {"id": msg_id, "model": model, "content": list(content)}
    if tokens is not None:
        message["usage"] = tokens
    return {"type": "assistant", "message": message}


def api_request(effort=None, tools=("Read",)):
    params = {"model": "claude-haiku-5-5", "tools": [{"name": t} for t in tools]}
    if effort is not None:
        params["output_config"] = {"effort": effort}
    return {"type": "api-request", "params": params}


def write_jsonl(path, records):
    text = "".join(json.dumps(record) + "\n" for record in records)
    path.write_text(text, encoding="utf-8")


def run(argv):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = su.main(argv)
    return code, out.getvalue(), err.getvalue()


class SessionFixture(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.claude = Path(tmp.name) / "claude"
        self.session = self.claude / "projects" / "proj" / SID
        (self.session / "subagents").mkdir(parents=True)
        self.session.with_name(SID + ".jsonl").write_text("", encoding="utf-8")

    def add_agent(self, name, agent_type, records, model="haiku"):
        path = self.session / "subagents" / f"agent-{name}.jsonl"
        write_jsonl(path, records)
        meta = {"agentType": agent_type, "model": model}
        path.with_name(f"agent-{name}.meta.json").write_text(json.dumps(meta), encoding="utf-8")
        return path

    def run_json(self, *args):
        code, out, err = run([*args, "--claude-dir", str(self.claude), "--json"])
        return code, json.loads(out) if code == 0 else None, err


class DedupAndTotalsTest(SessionFixture):
    def test_same_message_id_counts_once_in_totals(self):
        self.add_agent("a", PLUGIN_TYPE, [
            assistant("msg_1", tokens=usage(10, 1)),
            assistant("msg_1", tokens=usage(10, 7)),
            assistant("msg_2", tokens=usage(10, 2)),
        ])
        code, rows, _ = self.run_json(SID)
        self.assertEqual(code, 0)
        self.assertEqual(rows[0]["input_tokens"], 20)
        self.assertEqual(rows[0]["output_tokens"], 9)
        self.assertEqual(rows[0]["messages"], 2)


class ModelAndEffortTest(SessionFixture):
    def test_observed_model_comes_from_message_model(self):
        self.add_agent("a", PLUGIN_TYPE, [
            assistant("msg_1", model="claude-haiku-5-5", tokens=usage(1, 1)),
        ], model="haiku")
        _, rows, _ = self.run_json(SID)
        self.assertEqual(rows[0]["resolved_models"], ["claude-haiku-5-5"])
        self.assertEqual(rows[0]["model_alias"], "haiku")
        self.assertEqual(rows[0]["agent_type"], PLUGIN_TYPE)

    def test_request_effort_is_extracted_from_output_config(self):
        self.add_agent("a", PLUGIN_TYPE, [api_request(effort="low")])
        _, rows, _ = self.run_json(SID)
        self.assertEqual(rows[0]["request_effort"], ["low"])

    def test_request_without_output_config_reports_not_sent(self):
        self.add_agent("a", PLUGIN_TYPE, [api_request(effort=None)])
        _, rows, _ = self.run_json(SID)
        self.assertEqual(rows[0]["request_effort"], ["<not sent>"])


class AgentTypeFilterTest(SessionFixture):
    def setUp(self):
        super().setUp()
        self.add_agent("a", PLUGIN_TYPE, [api_request()])
        self.add_agent("b", BARE_TYPE, [api_request()])
        self.add_agent("c", "model-routing:exec-haiku-medium", [api_request()])

    def matched_types(self, filter_name):
        _, rows, _ = self.run_json(SID, "--agent-type", filter_name)
        return [row["agent_type"] for row in rows]

    def test_bare_filter_keeps_scoped_and_bare_agents(self):
        self.assertEqual(self.matched_types(BARE_TYPE), [PLUGIN_TYPE, BARE_TYPE])

    def test_scoped_filter_keeps_bare_and_scoped_agents(self):
        self.assertEqual(self.matched_types(PLUGIN_TYPE), [PLUGIN_TYPE, BARE_TYPE])

    def test_non_matching_agent_is_excluded(self):
        self.assertNotIn("model-routing:exec-haiku-medium", self.matched_types(BARE_TYPE))


class ToolAndSkillCallsTest(SessionFixture):
    def test_tool_calls_skill_names_and_advisor_are_counted(self):
        content = [
            {"type": "tool_use", "name": "Read", "input": {}},
            {"type": "tool_use", "name": "Skill", "input": {"skill": "example-plugin:tdd-workflow"}},
            {"type": "tool_use", "name": "Skill", "input": {"skill": "example-plugin:python-patterns"}},
            {"type": "server_tool_use", "name": "advisor", "input": {}},
        ]
        self.add_agent("a", PLUGIN_TYPE, [assistant("msg_1", content=content, tokens=usage(1, 1))])
        _, rows, _ = self.run_json(SID)
        self.assertEqual(rows[0]["tool_calls"], ["Read", "Skill", "Skill"])
        self.assertEqual(rows[0]["skill_calls"], ["example-plugin:tdd-workflow", "example-plugin:python-patterns"])
        self.assertEqual(rows[0]["advisor_calls"], 1)


class SingleAgentPathTest(SessionFixture):
    def test_agent_jsonl_path_gives_one_agent_report(self):
        path = self.add_agent("a", PLUGIN_TYPE, [api_request()])
        self.add_agent("b", BARE_TYPE, [api_request()])
        code, rows, _ = self.run_json(str(path))
        self.assertEqual(code, 0)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["transcript"], str(path))


class ErrorAndHelpTest(SessionFixture):
    def test_unknown_session_exits_2_with_prefixed_stderr(self):
        code, out, err = run([MISSING, "--claude-dir", str(self.claude)])
        self.assertEqual(code, 2)
        self.assertEqual(out, "")
        self.assertTrue(err.startswith("subagent_usage:"), err)

    def test_help_exits_0(self):
        with redirect_stdout(io.StringIO()), self.assertRaises(SystemExit) as cm:
            su.main(["--help"])
        self.assertEqual(cm.exception.code, 0)


class ReportHeadTest(SessionFixture):
    def test_report_head_is_first_line_truncated_to_160_chars(self):
        text = "A" * 200 + "\nsecond line"
        content = [{"type": "text", "text": text}]
        self.add_agent("a", PLUGIN_TYPE, [assistant("msg_1", content=content, tokens=usage(1, 1))])
        _, rows, _ = self.run_json(SID)
        self.assertEqual(rows[0]["report_first_line"], "A" * 160)


class TextOutputTest(SessionFixture):
    def test_text_output_keeps_token_line_layout(self):
        self.add_agent("a", PLUGIN_TYPE, [
            assistant("msg_1", tokens=usage(10, 5)),
        ])
        code, out, _ = run([SID, "--claude-dir", str(self.claude)])
        self.assertEqual(code, 0)
        self.assertIn(f"{PLUGIN_TYPE}  alias=haiku", out)
        self.assertIn("tokens: input=10 output=5", out)


if __name__ == "__main__":
    unittest.main()
