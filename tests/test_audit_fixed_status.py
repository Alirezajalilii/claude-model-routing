import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import routing_audit  # noqa: E402


class FixedStatusRedTest(unittest.TestCase):
    def test_tc1_fixed_status_lines_match(self):
        # TC1: a verifier's FIXED reply is a status line, not a stray reply.
        self.assertIsNotNone(
            routing_audit.STATUS_RE.match(
                "FIXED docs/handoffs/x/verdict-T1.md commits=abc123,def456"))
        self.assertIsNotNone(
            routing_audit.STATUS_RE.match(
                "FIXED docs/handoffs/x/verdict-b1.md tasks=T1:PASS,T2:FIXED"))


class FixedStatusGuardTest(unittest.TestCase):
    def test_tc2_existing_status_lines_still_match(self):
        # TC2 (guard): older status words keep matching.
        for line in ("PASS x", "FIX x", "REPLAN x fix=small",
                     "BLOCKED x reason=y", "DONE x commits=a1"):
            with self.subTest(line=line):
                self.assertIsNotNone(routing_audit.STATUS_RE.match(line))

    def test_tc3_similar_words_do_not_match(self):
        # TC3 (guard): the word boundary keeps look-alike words out.
        self.assertIsNone(routing_audit.STATUS_RE.match("FIXME x"))
        self.assertIsNone(routing_audit.STATUS_RE.match("Fixed it"))


if __name__ == "__main__":
    unittest.main()
