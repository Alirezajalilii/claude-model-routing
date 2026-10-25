import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import generate as gen  # noqa: E402
import policy_text as pt  # noqa: E402
import routing_config as rc  # noqa: E402

TIER_TOKEN = re.compile(r"\b(scout|planner|exec|verifier)-(haiku|sonnet|opus|fable)-(low|medium|high|xhigh|max)\b")
SECTIONS = ROOT / "policy" / "sections"
TEMPLATES = ROOT / "policy" / "agents"


def policy_files():
    files = []
    for sub in ("policy", "agents"):
        files += sorted(p for p in (ROOT / sub).rglob("*.md"))
    files.append(ROOT / "skills" / "routing-policy" / "SKILL.md")
    return files


class PolicyConsistencyTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config = rc.load_config()

    def test_sections_match_config_and_start_with_heading(self):
        stems = {p.stem for p in SECTIONS.glob("*.md")}
        self.assertEqual(stems, set(self.config.policy_sections))
        headings = []
        for path in sorted(SECTIONS.glob("*.md")):
            first = path.read_text(encoding="utf-8").split("\n", 1)[0]
            self.assertTrue(first.startswith("## "), path.name)
            headings.append(first)
        self.assertEqual(len(headings), len(set(headings)))

    def test_everything_renders(self):
        values = pt.base_values(self.config)
        for name in self.config.policy_sections:
            pt.render(f"{{{{section:{name}}}}}", values, SECTIONS)
        for tier in self.config.tiers:
            role = self.config.roles[tier.role].name
            template = (TEMPLATES / f"{role}.md").read_text(encoding="utf-8")
            pt.render(template, gen.tier_values(self.config, tier), SECTIONS)
        for index in range(1, pt.part_count(self.config) + 1):
            pt.render_part(self.config, index)

    def test_dispatcher_part_sizes(self):
        for index in range(1, pt.part_count(self.config) + 1):
            limit = 8000 if index == 1 else 9000
            size = len(pt.render_part(self.config, index))
            self.assertLessEqual(size, limit, f"part {index} is {size} characters")

    def test_tier_tokens_are_configured(self):
        known = {t.name for t in self.config.tiers}
        for path in policy_files():
            text = path.read_text(encoding="utf-8")
            for match in TIER_TOKEN.finditer(text):
                self.assertIn(match.group(0), known, f"{path.name}: {match.group(0)}")

    def test_no_home_claude_paths(self):
        for path in policy_files():
            self.assertNotIn("~/.claude/", path.read_text(encoding="utf-8"), path.name)

    def test_agent_rules(self):
        budget = f"at most {self.config.tunables['planner_evidence_budget']} Read/Grep/Glob calls"
        for tier in self.config.tiers:
            text = (ROOT / "agents" / f"{tier.name}.md").read_text(encoding="utf-8")
            if tier.role == "planner":
                self.assertIn(budget, text)
                self.assertIn("## Plan Contract", text)
                self.assertIn("## Executor tier selection (made by the planner)", text)
                self.assertIn("OUT_OF_TOPIC", text)
                self.assertIn("NO_PLAN_NEEDED", text)
                self.assertIn("Do not consult it again to check the revision.", text)
                self.assertIn("One instance per topic", text)
                self.assertIn("tools: Read, Grep, Glob, Skill, Write, Edit", text)
            else:
                self.assertIn("Never consult the advisor.", text, tier.name)

    def test_dispatcher_planner_scope(self):
        count = pt.part_count(self.config)
        text = "\n".join(pt.render_part(self.config, i) for i in range(1, count + 1))
        for phrase in (
            "passes it the problem, not a solution",
            "One planner instance per topic",
            "never spawns or resumes a planner",
            "It never consults again to check the revision.",
        ):
            self.assertIn(phrase, text)

    def test_committed_outputs_are_fresh(self):
        outputs = gen.expected_outputs(self.config, ROOT)
        self.assertEqual(gen.check_outputs(outputs, ROOT), [])


if __name__ == "__main__":
    unittest.main()
