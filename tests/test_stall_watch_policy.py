import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import policy_text as pt  # noqa: E402
import routing_config as rc  # noqa: E402

SECTION = "stall-watch"
PART_TITLE = "Calibration, logging and limits"
SECTION_FILE = ROOT / "policy" / "sections" / "stall-watch.md"
SKILL_FILE = ROOT / "skills" / "routing-policy" / "SKILL.md"
AGENTS_FILE = ROOT / "AGENTS.md"
RENDERED_PHRASES = (
    "## Stall watch",
    "reason=stalled",
    "skip its remaining FIX rounds",
    "never consults the advisor",
    "fails open",
    "REPLAN",
    "stall_watch.roles",
    "Monitor calls are not counted",
    "not small and clear",
)
CONFIG_KEYS = (
    "repeat_limit",
    "repeat_window",
    "read_only_streak_limit",
    "max_nudges",
    "handback_tools",
    "call_key_fields",
)
AGENTS_PHRASES = (
    "scripts/stall_watch.py",
    "$CLAUDE_PLUGIN_DATA/stall-watch/<agent_id>.json",
    "mr stall watch:",
    "call_key_fields",
)


class StallWatchPolicyTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config = rc.load_config()
        cls.raw = json.loads((ROOT / "config" / "routing.json").read_text(encoding="utf-8"))

    def test_section_listed_in_calibration_part_only(self):
        self.assertIn(SECTION, self.config.policy_sections)
        holders = [part.title for part in self.config.dispatcher_parts if SECTION in part.sections]
        self.assertEqual(holders, [PART_TITLE])

    def test_rendered_part_four_states_the_stall_policy(self):
        index = next(i for i, part in enumerate(self.config.dispatcher_parts, 1) if part.title == PART_TITLE)
        text = pt.render_part(self.config, index)
        for phrase in RENDERED_PHRASES:
            self.assertIn(phrase, text, phrase)
        self.assertLess(len(text), 9000, f"part {index} is {len(text)} characters")

    def test_generated_skill_contains_section(self):
        self.assertIn("## Stall watch", SKILL_FILE.read_text(encoding="utf-8"))

    def test_agent_bodies_do_not_mention_stall_watch(self):
        for path in sorted((ROOT / "agents").glob("*.md")):
            text = path.read_text(encoding="utf-8")
            self.assertNotIn("Stall watch", text, path.name)
            self.assertNotIn("stall_watch", text, path.name)

    def test_config_keys_named_in_section(self):
        text = SECTION_FILE.read_text(encoding="utf-8")
        for key in CONFIG_KEYS:
            self.assertIn(key, text, key)
            self.assertIn(key, self.raw["stall_watch"], key)

    def test_agents_guide_names_watch_script_state_and_prefix(self):
        text = AGENTS_FILE.read_text(encoding="utf-8")
        for phrase in AGENTS_PHRASES:
            self.assertIn(phrase, text, phrase)


if __name__ == "__main__":
    unittest.main()
