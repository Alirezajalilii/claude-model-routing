"""Verifier and executor agent bodies, tier descriptions and the log template for batch verification."""
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OLDER_PLAN_SENTENCE = "An older plan's `Verify: yes` counts as `Verify: task`."


def agent_files(prefix):
    return sorted((ROOT / "agents").glob(prefix + "-*.md"))


def read(path):
    return Path(path).read_text(encoding="utf-8")


def tier_descriptions():
    config = json.loads(read(ROOT / "config" / "routing.json"))
    return {tier["name"]: tier["description"] for tier in config["tiers"]}


class AgentBatchPolicyTests(unittest.TestCase):
    def test_tc1_verifier_bodies_know_batch_mode(self):
        files = agent_files("verify")
        self.assertTrue(files)
        for path in files:
            text = read(path)
            for phrase in (
                "`Verify: task` or `Verify: batch`",
                "a batch verifier receives several",
                "tasks=<id>:<verdict>,...",
                "REPLAN-design",
                "10. In a batch, do steps 1-9 for each task",
            ):
                self.assertIn(phrase, text, f"{path.name}: {phrase}")

    def test_tc2_executor_bodies_tag_tests_and_run_red_and_guard(self):
        files = agent_files("exec")
        self.assertTrue(files)
        for path in files:
            text = read(path)
            for phrase in (
                "each named or commented with its ID (`TC1`)",
                "Run the task's `red:` and `guard:` commands",
                "5. The red and guard run before the implementation",
            ):
                self.assertIn(phrase, text, f"{path.name}: {phrase}")
            self.assertNotIn("2. Run them and confirm they fail for the expected reason.", text)

    def test_tc3_tier_descriptions(self):
        tiers = tier_descriptions()
        for name in ("verify-sonnet-med", "verify-sonnet-high", "verify-opus-high"):
            self.assertIn("Verify: task or batch", tiers[name], name)
            self.assertIn("task ID (several for a batch)", tiers[name], name)
        xhigh = tiers["exec-sonnet-xhigh"]
        self.assertIn("only for tasks with three yes answers", xhigh)
        self.assertNotIn("security-sensitive code", xhigh)

    def test_tc4_log_template(self):
        text = read(ROOT / "templates" / "model-routing-log.md")
        for phrase in ("K = contract", "below planned tier, or sample", "propose Verify: batch for it"):
            self.assertIn(phrase, text)

    def test_tc5_guard_sizes_and_pinned_phrase(self):
        for path in agent_files("exec") + agent_files("verify"):
            self.assertLessEqual(len(read(path)), 14000 if path.name.startswith("verify-") else 12000, path.name)
        for path in agent_files("verify"):
            self.assertIn("the task ran below its planned executor tier", read(path), path.name)

    def test_tc6_verify_yes_is_gone(self):
        paths = [ROOT / "skills" / "routing-policy" / "SKILL.md", ROOT / "config" / "routing.json"]
        paths += [p for p in (ROOT / "policy").rglob("*") if p.is_file()]
        paths += [p for p in (ROOT / "agents").glob("*.md")]
        paths += sorted((ROOT / "templates").glob("*.md"))
        for path in paths:
            text = read(path).replace(OLDER_PLAN_SENTENCE, "")
            self.assertNotIn("Verify: yes", text, str(path.relative_to(ROOT)))

    def test_verifier_step_five_names_contract(self):
        text = read(ROOT / "policy" / "agents" / "verifier.md")
        self.assertIn("red, integrity, coverage, scope, contract or report", text)


if __name__ == "__main__":
    unittest.main()
