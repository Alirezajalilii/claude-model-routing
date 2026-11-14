"""Policy text for the mr-gate gate step, the Gate section and batch verification."""
import copy
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import policy_text as pt  # noqa: E402
import routing_config as rc  # noqa: E402


class GatePolicyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config = rc.load_config()
        cls.part2 = pt.render_part(cls.config, 2)
        cls.part5 = pt.render_part(cls.config, 5)

    def test_tc1_gate_section_after_task_contracts_in_part_five(self):
        sections = list(self.config.policy_sections)
        self.assertEqual(sections[sections.index("task-contracts") + 1], "gate")
        last = self.config.dispatcher_parts[-1]
        title = last["title"] if isinstance(last, dict) else last.title
        names = last["sections"] if isinstance(last, dict) else last.sections
        self.assertEqual(title, "Handoffs between agents")
        self.assertEqual(list(names), ["handoffs", "task-contracts", "gate"])

    def test_tc2_part_two_runs_mr_gate(self):
        self.assertIn(
            "`mr-gate <plan path> <task-id> <worktree path> --commits <shas from the status line>"
            " --report <report path> --out <gate file> --base <integration branch>`",
            self.part2,
        )
        self.assertIn("never repeat its checks by hand", self.part2)
        self.assertNotIn("the main session runs these checks itself", self.part2)

    def test_tc3_part_five_gate_section(self):
        for phrase in (
            "## Gate",
            "every `guard:` command passes",
            "unless the plan marked them guard",
            "matches the `files:` or `tests:` line",
            "also fails on the task's base commit",
            "resume the plan's planner to add Gate blocks (not a REPLAN",
            "merge it with `git merge --squash` instead of folding its commits",
            "gate it again with `--base <the base sha in its first gate file>`",
        ):
            self.assertIn(phrase, self.part5)

    def test_tc4_part_two_batch_verification(self):
        for phrase in (
            "groups of at most 6 tasks whose verifier Skills lines together name at most 6 skills",
            "a task that ran below the plan's executor tier, even if the plan marked it Verify: no",
            "a batch verifier gets every task ID with its report and gate file paths",
            # TC11: kept-worktree batch verification pin
            "it checks and fixes each task in that task's kept worktree (see Gate).",
            "An older plan's `Verify: yes` counts as `Verify: task`.",
            "(`checks=green`): resume the same executor instance through SendMessage with the gate file path",
        ):
            self.assertIn(phrase, self.part2)

    def test_tc5_batch_verify_max_tasks_tunable(self):
        self.assertEqual(self.config.tunables["batch_verify_max_tasks"], 6)
        self.assertEqual(pt.base_values(self.config)["batch_verify_max_tasks"], "6")
        raw = json.loads(rc.CONFIG_PATH.read_text(encoding="utf-8"))
        bad = copy.deepcopy(raw)
        bad["tunables"]["batch_verify_max_tasks"] = 0
        self.assertIn("tunables.batch_verify_max_tasks: must be an integer >= 1", rc.validate(bad))
        gone = copy.deepcopy(raw)
        del gone["tunables"]["batch_verify_max_tasks"]
        self.assertIn("tunables.batch_verify_max_tasks: missing", rc.validate(gone))

    def test_tc6_part_sizes(self):
        self.assertLessEqual(len(self.part2), 9000)
        self.assertLessEqual(len(self.part5), 9000)


if __name__ == "__main__":
    unittest.main()
