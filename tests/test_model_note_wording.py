import contextlib
import dataclasses
import io
import json
import os
import re
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import routing_audit as ra  # noqa: E402
import routing_config as rc  # noqa: E402
import session_context as sc  # noqa: E402

SPAWN_OK = {"CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH": "1"}
OPUS = "claude-opus-5-5"
NOTE_MARKER = "this session runs on"
FORBIDDEN_ON_NOTE = ("picker", "/model", "please switch", "switch to", "mismatch")
FORBIDDEN_RENDERED = ("fable", "advisorModel", "pick Sonnet", "model picker",
                      "ask the user to switch")
ALLOWED_SENTENCE = "never ask the user to switch"


def part_one(event, sections_dir=None, config=None):
    """Run the SessionStart hook for part 1; return (exit code, context text)."""
    out, err = io.StringIO(), io.StringIO()
    code = sc.main(["--part", "1"], stdin=io.StringIO(json.dumps(event)), stdout=out,
                   stderr=err, env=SPAWN_OK, config=config, sections_dir=sections_dir)
    text = ""
    if out.getvalue():
        text = json.loads(out.getvalue())["hookSpecificOutput"]["additionalContext"]
    return code, text


def note_lines(text):
    return [ln for ln in text.splitlines() if NOTE_MARKER in ln]


class NoteTest(unittest.TestCase):
    def test_tc1_off_family_model_gets_informational_note(self):
        code, text = part_one({"hook_event_name": "SessionStart", "source": "startup",
                               "model": OPUS})
        self.assertEqual(code, 0)
        lines = note_lines(text)
        self.assertEqual(len(lines), 1)
        self.assertIn(f"this session runs on {OPUS}", lines[0])
        self.assertIn("Do not ask the user to switch models.", lines[0])
        for word in FORBIDDEN_ON_NOTE:
            self.assertNotIn(word, lines[0].lower())

    def test_tc2_matching_family_has_no_note(self):
        _, text = part_one({"hook_event_name": "SessionStart", "source": "startup",
                            "model": "claude-sonnet-5-5"})
        self.assertEqual(note_lines(text), [])

    def test_tc3_missing_model_has_no_note(self):
        code, text = part_one({"hook_event_name": "SessionStart", "source": "startup"})
        self.assertEqual(code, 0)
        self.assertEqual(note_lines(text), [])

    def test_tc4_note_survives_oversized_part_one(self):
        base = rc.load_config()
        parts = (rc.DispatcherPart(title="Alpha", sections=("sec-a",)),)
        config = dataclasses.replace(base, dispatcher_parts=parts)
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "sec-a.md").write_text("x" * 12000, encoding="utf-8")
            _, text = part_one({"hook_event_name": "SessionStart", "source": "startup",
                                "model": OPUS}, sections_dir=Path(tmp), config=config)
        self.assertIn("mr:routing-policy", text)
        self.assertNotIn("x" * 100, text)
        lines = note_lines(text)
        self.assertEqual(len(lines), 1)
        self.assertIn(f"this session runs on {OPUS}", lines[0])
        self.assertIn("Do not ask the user to switch models.", lines[0])


class AuditInfoTest(unittest.TestCase):
    def test_tc5_main_model_is_info_not_a_flag(self):
        with tempfile.TemporaryDirectory() as tmp:
            claude = os.path.join(tmp, "claude")
            base = os.path.join(claude, "projects", "proj", "00000000-0000-4000-8000-000000000071")
            os.makedirs(os.path.join(base, "subagents"))
            record = {"type": "assistant", "timestamp": "2026-10-24T10:00:00.000Z",
                      "message": {"role": "assistant", "content": [], "id": "m1",
                                  "model": OPUS, "usage": {"input_tokens": 1, "output_tokens": 1}}}
            with open(base + ".jsonl", "w") as f:
                f.write(json.dumps(record) + "\n")
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                code = ra.main([base, "--claude-dir", claude])
        report = out.getvalue()
        self.assertEqual(code, 0)
        self.assertIn("info: main session model", report)
        self.assertIn(OPUS, report)
        self.assertTrue(report.rstrip().endswith("None"), report)
        self.assertNotIn("the policy expects", report)


class RenderedPolicyTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config = rc.load_config()
        texts = [sc.build_context(cls.config, n, {}, SPAWN_OK)
                 for n in range(1, len(cls.config.dispatcher_parts) + 1)]
        texts.append((ROOT / "skills" / "routing-policy" / "SKILL.md").read_text(encoding="utf-8"))
        cls.rendered = "\n".join(texts)

    def test_tc6_no_forbidden_phrases(self):
        text = re.sub(re.escape(ALLOWED_SENTENCE), "", self.rendered, flags=re.IGNORECASE).lower()
        for phrase in FORBIDDEN_RENDERED:
            with self.subTest(phrase=phrase):
                self.assertNotIn(phrase.lower(), text)

    def test_tc7_replacement_sentences_present(self):
        self.assertIn("The user may run a session on another model by choice", self.rendered)
        self.assertIn("never ask the user to switch", self.rendered)
        self.assertIn("The advisor is whatever model the user's settings choose.", self.rendered)


if __name__ == "__main__":
    unittest.main()
