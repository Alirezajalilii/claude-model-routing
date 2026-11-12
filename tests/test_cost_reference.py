"""Cost reference in the routing policy: current prices, no unlogged claim, pointer to mr-cost."""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import policy_text as pt  # noqa: E402
import routing_config as rc  # noqa: E402
import session_context as sc  # noqa: E402

COST_SECTION = ROOT / "policy" / "sections" / "cost.md"
ROUTING_SKILL = ROOT / "skills" / "routing-policy" / "SKILL.md"
TOO_LONG = "This part is too long for session-start context"


class CostReferenceTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.lines = COST_SECTION.read_text(encoding="utf-8").splitlines()
        cls.skill = ROUTING_SKILL.read_text(encoding="utf-8")

    def test_line_two(self):
        # TC1: line 2 states current prices with cache reads and points to mr-cost.
        line = self.lines[1]
        self.assertTrue(line.startswith("Prices as of 2026-11-12;"), line)
        for text in (
            "Haiku 5.5 0.10 / 0.50 / 0.01",
            "Sonnet 5.5 2 / 10 / 0.10",
            "Opus 5.5 4 / 20 / 0.20",
            "{{plugin_name}}-cost",
        ):
            self.assertIn(text, line)

    def test_old_claim_removed(self):
        # TC2: the unlogged 2026-10-29 sentence and its figures are gone.
        text = COST_SECTION.read_text(encoding="utf-8")
        for stale in ("five Sonnet-planned tasks", "shipped defects", "2026-10-29"):
            self.assertNotIn(stale, text)

    def test_skill_rendered(self):
        # TC3: the generated routing-policy skill carries the new reference.
        self.assertIn("`mr-cost` prices a session's subagent tokens", self.skill)
        self.assertIn("Prices as of 2026-11-12", self.skill)

    def test_parts_fit(self):
        # TC4 (guard): every session-start part renders within the context limit.
        config = rc.load_config()
        for part in range(1, pt.part_count(config) + 1):
            with self.subTest(part=part):
                text = sc.build_context(config, part, {}, {})
                self.assertNotIn(TOO_LONG, text)


if __name__ == "__main__":
    unittest.main()
