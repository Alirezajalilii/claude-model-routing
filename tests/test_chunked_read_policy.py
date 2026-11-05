import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import routing_config as rc  # noqa: E402

SKILL_MD = ROOT / "skills" / "routing-policy" / "SKILL.md"
CHUNK_LIMIT = "in chunks of at most 250 lines"
READ_AGAIN = "read that range again in smaller chunks"
SKILL_CHUNKS = "read its SKILL.md in chunks as Core rules describe, until you have seen every line"
WHOLE_SKILL = "(it returns the whole skill)"
NO_OFFSET = "(no offset or limit)"


def _agent_text(tier):
    return (ROOT / "agents" / f"{tier.name}.md").read_text(encoding="utf-8")


class ChunkedReadPolicyTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config = rc.load_config()
        cls.skill_text = SKILL_MD.read_text(encoding="utf-8")

    def each(self):
        for tier in self.config.tiers:
            yield tier, _agent_text(tier)

    def test_every_tier_body_reads_in_chunks(self):
        for tier, text in self.each():
            self.assertIn(CHUNK_LIMIT, text, tier.name)
            self.assertIn(READ_AGAIN, text, tier.name)

    def test_every_tier_body_loads_skills_in_chunks(self):
        for tier, text in self.each():
            self.assertIn(SKILL_CHUNKS, text, tier.name)
            self.assertIn(WHOLE_SKILL, text, tier.name)

    def test_no_tier_body_reads_in_one_call(self):
        for tier, text in self.each():
            self.assertNotIn(NO_OFFSET, text, tier.name)

    def test_routing_policy_states_chunk_limit(self):
        self.assertIn(CHUNK_LIMIT, self.skill_text)


if __name__ == "__main__":
    unittest.main()
