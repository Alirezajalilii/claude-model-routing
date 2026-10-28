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
                self.assertIn("tools: Read, Grep, Glob, Write, Edit", text)
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

class LeanAgentFilesTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config = rc.load_config()

    def test_committed_agents_are_lean(self):
        for tier in self.config.tiers:
            text = (ROOT / "agents" / f"{tier.name}.md").read_text(encoding="utf-8")
            head = text.split("\n---\n", 1)[0]
            lines = head.split("\n")
            self.assertIn("omitClaudeMd: true", lines, tier.name)
            tools = next(ln for ln in lines if ln.startswith("tools: "))
            self.assertNotIn("Skill", tools, tier.name)
            self.assertEqual(
                "autoCompactWindow: 100000" in lines, tier.family == "haiku", tier.name
            )

    def test_new_tunables_render(self):
        values = pt.base_values(self.config)
        self.assertEqual(values["haiku_max_tool_calls"], "25")
        self.assertEqual(values["haiku_prompt_flag_tokens"], "100000")
        self.assertEqual(values["status_line_max_chars"], "400")


def _agent_text(tier):
    return (ROOT / "agents" / f"{tier.name}.md").read_text(encoding="utf-8")


class AgentBodyHandoffTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config = rc.load_config()

    def each(self):
        for tier in self.config.tiers:
            yield tier, _agent_text(tier)

    def test_shared_sections_once(self):
        for tier, text in self.each():
            for heading in ("## Core rules", "## Skills", "## Output and status line", "## Output file"):
                self.assertEqual(len(re.findall(rf"^{re.escape(heading)}$", text, re.M)), 1, f"{tier.name}: {heading}")

    def test_no_skill_tool_or_skill_loading(self):
        for tier, text in self.each():
            self.assertNotIn("Skill tool", text, tier.name)
            self.assertNotIn("## Skill loading", text, tier.name)

    def test_project_rules_and_output_lines(self):
        for tier, text in self.each():
            self.assertIn("Project rules:", text, tier.name)
            self.assertIn("Output:", text, tier.name)

    def test_status_lines_per_role(self):
        wanted = {
            "scout": ["DONE <output path>", "BLOCKED <output path> reason=<one line>"],
            "executor": ["commits=<sha>,<sha>", "BLOCKED <output path> reason=<one line>", "never `git add -A`"],
            "verifier": [
                "PASS <output path>",
                "FIX <output path>",
                "REPLAN <output path> fix=small",
                "REPLAN <output path> fix=design",
                "BLOCKED <output path> reason=<one line>",
            ],
            "planner": [
                "READY <plan path>",
                "NEED_EVIDENCE <requests path> scouts=<k>",
                "## Scout <k>: <scout tier>",
                "OUT_OF_TOPIC",
                "NO_PLAN_NEEDED",
            ],
        }
        for tier, text in self.each():
            for phrase in wanted[tier.role]:
                self.assertIn(phrase, text, f"{tier.name}: {phrase}")

    def test_write_exceptions(self):
        for tier, text in self.each():
            if tier.role == "scout":
                self.assertIn("The one exception is your Output file", text, tier.name)
            if tier.role == "verifier":
                self.assertIn("the only file you write is your Output file", text, tier.name)

    def test_advisor_line_for_non_planners(self):
        for tier, text in self.each():
            if tier.role != "planner":
                self.assertIn("Never consult the advisor.", text, tier.name)

    def test_size_limits(self):
        for tier, text in self.each():
            limit = 26000 if tier.role == "planner" else 10000
            self.assertLessEqual(len(text), limit, f"{tier.name} is {len(text)} characters")

    def test_new_sections_not_in_dispatcher_parts(self):
        ids = ("agent-core", "agent-skills", "agent-output")
        for name in ids:
            self.assertIn(name, self.config.policy_sections)
        for part in self.config.dispatcher_parts:
            for name in ids:
                self.assertNotIn(name, part["sections"] if isinstance(part, dict) else part.sections)

    def test_executor_fact_sheet_rule(self):
        for tier, text in self.each():
            if tier.role == "executor":
                self.assertIn("fact sheet", text, tier.name)
                self.assertIn("--help", text, tier.name)


class DispatcherHandoffTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config = rc.load_config()
        count = pt.part_count(cls.config)
        cls.text = "\n".join(pt.render_part(cls.config, i) for i in range(1, count + 1))

    def test_handoffs_section_and_part(self):
        self.assertIn("handoffs", self.config.policy_sections)
        parts = self.config.dispatcher_parts
        self.assertEqual(len(parts), 5)
        self.assertEqual(parts[-1]["title"] if isinstance(parts[-1], dict) else parts[-1].title, "Handoffs between agents")
        sections = parts[-1]["sections"] if isinstance(parts[-1], dict) else parts[-1].sections
        self.assertEqual(list(sections)[0], "handoffs")

    def test_session_start_hooks_cover_five_parts(self):
        import json

        hooks = json.loads((ROOT / "hooks" / "hooks.json").read_text(encoding="utf-8"))
        cmds = [h["command"] for g in hooks["hooks"]["SessionStart"] for h in g["hooks"]]
        self.assertEqual(len(cmds), 5)
        for n, cmd in enumerate(cmds, 1):
            self.assertTrue(cmd.endswith(f"--part {n}"), cmd)

    def test_rendered_parts_contain_handoff_policy(self):
        for phrase in (
            "never reads these files",
            "BLOCKED <plan path> reason=<one line>",
            "does not count against the budget",
            "Output:",
            "Project rules:",
            "findings=<n>",
            "reason=<one line>",
            "fix=small|design",
            "`fix=small` goes to the fast lane",
            "dispatch.allow_agents",
            "omitClaudeMd",
            "general-purpose",
            "SKILL.md path",
            "model-routing-skills --out",
            "executor's report path",
            "the verdict file path",
        ):
            self.assertIn(phrase, self.text)

    def test_old_report_gate_wording_removed(self):
        self.assertNotIn("the executor's claims match the diff", self.text)

    def test_planner_files_carry_docs_and_haiku_rules(self):
        for tier in self.config.tiers:
            if tier.role != "planner":
                continue
            text = _agent_text(tier)
            for phrase in (
                "more than about 25 tool calls",
                "fact sheet",
                "Docs that state commands, procedures or behavior",
                "wording-only docs",
                "the Project rules line",
                "alone on its own line",
            ):
                self.assertIn(phrase, text, f"{tier.name}: {phrase}")

    def test_part_five_session_context(self):
        import io
        import json

        import session_context as sc

        out = io.StringIO()
        code = sc.main(
            ["--part", "5"],
            stdin=io.StringIO("{}"),
            stdout=out,
            stderr=io.StringIO(),
            env={"CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH": "1"},
        )
        self.assertEqual(code, 0)
        ctx = json.loads(out.getvalue())["hookSpecificOutput"]["additionalContext"]
        self.assertTrue(ctx.startswith("# model-routing policy, part 5 of 5:"), ctx[:80])


if __name__ == "__main__":
    unittest.main()
