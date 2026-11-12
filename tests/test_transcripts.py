import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import json  # noqa: E402
import tempfile  # noqa: E402
import unittest  # noqa: E402

import transcripts as tr  # noqa: E402

SID = "00000000-0000-4000-8000-000000000001"
AGENT = "agent-aaaaaaaaaaaaaaa1"


def make_session(claude_dir: Path) -> Path:
    """Create <claude>/projects/proj/<SID>/subagents and the sibling transcript."""
    base = claude_dir / "projects" / "proj" / SID
    (base / "subagents").mkdir(parents=True)
    base.with_name(SID + ".jsonl").write_text("", encoding="utf-8")
    (base / "subagents" / (AGENT + ".jsonl")).write_text("", encoding="utf-8")
    return base


class ResolveSessionTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.claude = Path(tmp.name) / "claude"
        self.claude.mkdir()
        self.base = make_session(self.claude)
        self.agent_path = self.base / "subagents" / (AGENT + ".jsonl")

    def test_resolves_session_id_under_projects(self):
        files = tr.resolve_session(SID, self.claude)
        self.assertEqual(files.session_id, SID)
        self.assertEqual(files.main, self.base.with_name(SID + ".jsonl"))
        self.assertEqual(files.subagents, (self.agent_path,))

    def test_resolves_session_directory(self):
        files = tr.resolve_session(str(self.base), self.claude)
        self.assertEqual(files.session_id, SID)
        self.assertEqual(files.subagents, (self.agent_path,))

    def test_resolves_main_transcript_path(self):
        files = tr.resolve_session(str(self.base) + ".jsonl", self.claude)
        self.assertEqual(files.session_id, SID)
        self.assertEqual(files.main, self.base.with_name(SID + ".jsonl"))
        self.assertEqual(len(files.subagents), 1)

    def test_resolves_agent_transcript_path(self):
        files = tr.resolve_session(str(self.agent_path), self.claude)
        self.assertEqual(files.session_id, AGENT)
        self.assertIsNone(files.main)
        self.assertEqual(files.subagents, (self.agent_path,))

    def test_unknown_id_raises(self):
        with self.assertRaises(tr.SessionNotFound):
            tr.resolve_session("00000000-0000-4000-8000-0000000000ff", self.claude)

    def test_empty_reference_raises(self):
        with self.assertRaises(tr.SessionNotFound):
            tr.resolve_session("", self.claude)


class BareIdWithoutSubagentFolderTest(unittest.TestCase):
    """A session with a main transcript and no subagent folder must resolve by bare id."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.claude = Path(tmp.name) / "claude"
        self.transcript = self.claude / "projects" / "p" / (SID + ".jsonl")
        self.transcript.parent.mkdir(parents=True)
        self.transcript.write_text("", encoding="utf-8")

    def test_bare_id_resolves_to_main_transcript(self):
        # TC1: only projects/p/<id>.jsonl exists; the bare id resolves to it.
        files = tr.resolve_session(SID, self.claude)
        self.assertEqual(files.session_id, SID)
        self.assertEqual(files.main, self.transcript)
        self.assertEqual(files.subagents, ())

    def test_bare_id_matches_the_main_transcript_path(self):
        # TC1: the bare id and the .jsonl path give the same answer.
        by_id = tr.resolve_session(SID, self.claude)
        by_path = tr.resolve_session(str(self.transcript), self.claude)
        self.assertEqual(by_id, by_path)

    def test_id_with_neither_directory_nor_transcript_raises(self):
        # TC2: no directory and no .jsonl for the id, so SessionNotFound.
        with self.assertRaises(tr.SessionNotFound):
            tr.resolve_session("00000000-0000-4000-8000-0000000000ff", self.claude)


class ReadJsonlTest(unittest.TestCase):
    def test_keeps_only_dict_records(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = Path(tmp.name) / "session.jsonl"
        good = json.dumps({"type": "user", "n": 1})
        path.write_text(f"{good}\n\nnot json\n[1]\n", encoding="utf-8")
        self.assertEqual(tr.read_jsonl(path), ({"type": "user", "n": 1},))


def assistant_record(msg_id, usage=None, model="claude-haiku-5-5", kind="assistant"):
    message = {"id": msg_id, "model": model, "content": []}
    if usage is not None:
        message["usage"] = usage
    return {"type": kind, "message": message}


def usage_of(inp, cache_read=0):
    return {"input_tokens": inp, "output_tokens": 1, "cache_creation_input_tokens": 0,
            "cache_read_input_tokens": cache_read}


class RequestUsageTest(unittest.TestCase):
    def test_last_record_per_id_wins_and_prompt_sums_input_and_cache(self):
        events = [
            assistant_record("m1", usage_of(10)),
            assistant_record("m1", usage_of(30, cache_read=5)),
        ]
        self.assertEqual(
            tr.request_usage(events),
            (tr.RequestUsage("m1", "claude-haiku-5-5", 35),),
        )

    def test_records_without_id_usage_or_assistant_type_are_ignored(self):
        events = [
            {"type": "assistant", "message": {"model": "m", "usage": usage_of(5)}},
            assistant_record("m2", usage=None),
            assistant_record("m3", usage_of(7), kind="user"),
        ]
        self.assertEqual(tr.request_usage(events), ())
        self.assertEqual(tr.request_usage([]), ())

    def test_order_follows_first_appearance(self):
        events = [
            assistant_record("m1", usage_of(1)),
            assistant_record("m2", usage_of(2)),
            assistant_record("m1", usage_of(3)),
        ]
        ids = [item.message_id for item in tr.request_usage(events)]
        self.assertEqual(ids, ["m1", "m2"])

    def test_non_int_usage_value_counts_zero(self):
        bad = {"input_tokens": 4, "output_tokens": 1, "cache_creation_input_tokens": 0,
               "cache_read_input_tokens": "x"}
        events = [assistant_record("m1", bad)]
        self.assertEqual(tr.request_usage(events)[0].prompt_tokens, 4)


def dispatch_block(tool_id, subagent_type, name="Agent"):
    """Assistant record holding one Agent or Task tool_use."""
    block = {"type": "tool_use", "id": tool_id, "name": name,
             "input": {"subagent_type": subagent_type, "prompt": "Do it."}}
    return {"type": "assistant", "message": {"role": "assistant", "content": [block]}}


def result_record(tool_id, agent_id=None):
    """User record holding the tool_result of one call; agent_id adds Claude Code's toolUseResult."""
    record = {"type": "user", "message": {"role": "user", "content": [
        {"type": "tool_result", "tool_use_id": tool_id, "content": "done"}]}}
    if agent_id is not None:
        record["toolUseResult"] = {"status": "completed", "agentId": agent_id}
    return record


class DispatchedAgentTypesTest(unittest.TestCase):
    def test_tc1_agent_id_maps_to_the_dispatched_subagent_type(self):
        # TC1: toolUseResult.agentId of the tool_result is keyed to the subagent_type of its tool_use.
        events = [dispatch_block("toolu_1", "mr:exec-haiku-low"), result_record("toolu_1", "a1b2")]
        self.assertEqual(tr.dispatched_agent_types(events), {"a1b2": "mr:exec-haiku-low"})

    def test_tc2_task_tool_is_read_like_agent(self):
        # TC2: the older Task tool name carries subagent_type the same way.
        events = [dispatch_block("toolu_2", "exec-sonnet-high", name="Task"),
                  result_record("toolu_2", "c3d4")]
        self.assertEqual(tr.dispatched_agent_types(events), {"c3d4": "exec-sonnet-high"})

    def test_tc3_results_without_agent_id_or_dispatch_are_skipped(self):
        # TC3: a result with no agentId, and a result of a non-dispatch tool, give no mapping.
        read_use = {"type": "assistant", "message": {"role": "assistant", "content": [
            {"type": "tool_use", "id": "toolu_r", "name": "Read", "input": {"file_path": "/x"}}]}}
        events = [dispatch_block("toolu_3", "exec-haiku-low"), result_record("toolu_3"),
                  read_use, result_record("toolu_r", "e5f6")]
        self.assertEqual(tr.dispatched_agent_types(events), {})


class AgentTypeOfTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.jsonl = Path(tmp.name) / "agent-a1b2.jsonl"
        self.jsonl.write_text("", encoding="utf-8")

    def write_meta(self, meta):
        tr.meta_path_for(self.jsonl).write_text(json.dumps(meta), encoding="utf-8")

    def test_tc4_meta_file_wins_over_the_dispatch_record(self):
        # TC4: the agent's own meta file is read first.
        self.write_meta({"agentType": "exec-haiku-low"})
        self.assertEqual(tr.agent_type_of(self.jsonl, {"a1b2": "exec-sonnet-high"}), "exec-haiku-low")

    def test_tc5_missing_meta_takes_the_dispatch_record_type(self):
        # TC5: no meta file, so the agent id (from agent-<id>.jsonl) is looked up in the dispatch map.
        self.assertEqual(tr.agent_type_of(self.jsonl, {"a1b2": "exec-sonnet-high"}), "exec-sonnet-high")

    def test_tc5_meta_without_agent_type_takes_the_dispatch_record_type(self):
        # TC5: a meta file that holds no agentType falls back to the dispatch record too.
        self.write_meta({"model": "haiku"})
        self.assertEqual(tr.agent_type_of(self.jsonl, {"a1b2": "exec-sonnet-high"}), "exec-sonnet-high")

    def test_tc6_no_meta_and_no_dispatch_gives_none(self):
        # TC6: neither source has the type.
        self.assertIsNone(tr.agent_type_of(self.jsonl, {}))


class DispatchTypesOfSessionTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.claude = Path(tmp.name) / "claude"
        self.claude.mkdir()
        self.base = make_session(self.claude)
        self.main = self.base.with_name(SID + ".jsonl")
        self.agent_path = self.base / "subagents" / (AGENT + ".jsonl")

    def write_main(self, records):
        self.main.write_text("".join(json.dumps(r) + "\n" for r in records), encoding="utf-8")

    def test_tc7_agent_file_target_reads_the_parent_main_transcript(self):
        # TC7: an agent-*.jsonl target has no main transcript in its SessionFiles; the parent's is read.
        self.write_main([dispatch_block("toolu_7", "exec-sonnet-high"),
                         result_record("toolu_7", "aaaaaaaaaaaaaaa1")])
        files = tr.resolve_session(str(self.agent_path), self.claude)
        self.assertEqual(tr.dispatch_types_of(files), {"aaaaaaaaaaaaaaa1": "exec-sonnet-high"})

    def test_tc8_session_without_main_transcript_gives_empty_map(self):
        # TC8: no main transcript, so no dispatch record can be read.
        self.main.unlink()
        files = tr.resolve_session(SID, self.claude)
        self.assertEqual(tr.dispatch_types_of(files), {})


if __name__ == "__main__":
    unittest.main()
