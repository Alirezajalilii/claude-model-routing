import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import routing_config as rc  # noqa: E402

SECTION_HEADING = "## Long-running commands"
MONITOR_PHRASE = "use Monitor with an until-loop"
TASKSTOP_PHRASE = "stop every background shell you started with TaskStop"
PLACEHOLDER = "{{section:agent-shell}}"
SHELL_ROLES = ("scout", "executor", "verifier")


class AgentShellPolicyTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config = rc.load_config()
        cls.bodies = [
            (t, (ROOT / "agents" / f"{t.name}.md").read_text(encoding="utf-8"))
            for t in cls.config.tiers
        ]

    def test_1_shell_roles_contain_long_running_section(self):
        checked = 0
        for t, text in self.bodies:
            if t.role not in SHELL_ROLES:
                continue
            checked += 1
            self.assertIn(SECTION_HEADING, text, t.name)
            self.assertIn(MONITOR_PHRASE, text, t.name)
            self.assertIn(TASKSTOP_PHRASE, text, t.name)
        self.assertGreater(checked, 0)

    def test_2_planner_bodies_have_no_long_running_section(self):
        checked = 0
        for t, text in self.bodies:
            if t.role != "planner":
                continue
            checked += 1
            self.assertNotIn(SECTION_HEADING, text, t.name)
        self.assertGreater(checked, 0)

    def test_3_section_file_starts_with_heading(self):
        path = ROOT / "policy" / "sections" / "agent-shell.md"
        self.assertTrue(path.exists())
        first = path.read_text(encoding="utf-8").split("\n", 1)[0]
        self.assertEqual(first, SECTION_HEADING)

    def test_4_placeholder_is_rendered(self):
        for t, text in self.bodies:
            self.assertNotIn(PLACEHOLDER, text, t.name)


if __name__ == "__main__":
    unittest.main()
