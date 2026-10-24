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


class ReadJsonlTest(unittest.TestCase):
    def test_keeps_only_dict_records(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = Path(tmp.name) / "session.jsonl"
        good = json.dumps({"type": "user", "n": 1})
        path.write_text(f"{good}\n\nnot json\n[1]\n", encoding="utf-8")
        self.assertEqual(tr.read_jsonl(path), ({"type": "user", "n": 1},))


if __name__ == "__main__":
    unittest.main()
