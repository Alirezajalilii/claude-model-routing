"""Docs checks for verifiers that fix what they find (plan task T4)."""

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class DocsRedTest(unittest.TestCase):
    def setUp(self):
        self.readme = (ROOT / "README.md").read_text(encoding="utf-8")

    def test_tc1_review_node_says_verifier_fixes(self):
        # TC1: the mermaid review node says the verifier reviews and fixes the task.
        self.assertIn(
            'review["Verifier reviews and fixes it, on Opus for high risk"]',
            self.readme,
        )
        self.assertNotIn(
            'review["Verifier reviews it, on Opus for high risk"]',
            self.readme,
        )

    def test_tc2_verify_row_says_fixes_and_gate_rechecks(self):
        # TC2: the Verify row says the verifier fixes defects on the task branch
        # and that the gate then re-checks its commits.
        self.assertIn(
            "and fixes the defects it finds itself on the task branch; "
            "the gate then re-checks its commits.",
            self.readme,
        )


if __name__ == "__main__":
    unittest.main()
