"""Tests for scripts/plan_gate.py: the Gate block, Test Case ID and Skills line parser."""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import plan_contract as pc  # noqa: E402
import plan_gate as pg  # noqa: E402

GATE = ("Gate:", "- files: scripts/a.py", "- green: make test")


def _plan(*lines):
    return "\n".join(lines) + "\n"


def _one(*body):
    return _plan("### Task T1: A", *body)


def _skills_of(*body):
    return pg.parse_gate(_one(*GATE, *body), "T1").skills


def _error(text, task_id):
    try:
        pg.parse_gate(text, task_id)
    except pg.GateError as error:
        return str(error)
    raise AssertionError("parse_gate did not raise GateError")


class GateParseTest(unittest.TestCase):
    def test_tc01_items_are_read_in_order(self):
        text = _plan(
            "### Task T1: A",
            "Gate:",
            "- files: scripts/a.py, `docs/b.md`",
            "- tests: tests/test_a.py",
            "- red: `python3 -B -m unittest tests.test_a.RedTest`",
            "- guard: python3 -B -m unittest tests.test_a.GuardTest",
            "- green: make test",
            "- green: make lint",
        )
        gate = pg.parse_gate(text, "T1")
        self.assertEqual(gate.task_id, "T1")
        self.assertEqual(gate.line, 2)
        self.assertEqual(gate.files, ("scripts/a.py", "docs/b.md"))
        self.assertEqual(gate.tests, ("tests/test_a.py",))
        self.assertEqual(gate.red, ("python3 -B -m unittest tests.test_a.RedTest",))
        self.assertEqual(gate.guard, ("python3 -B -m unittest tests.test_a.GuardTest",))
        self.assertEqual(gate.green, ("make test", "make lint"))

    def test_tc02_inner_backticks_are_kept(self):
        gate = pg.parse_gate(_one("Gate:", "- files: a.py", "- green: echo `date` ok"), "T1")
        self.assertEqual(gate.green, ("echo `date` ok",))

    def test_tc03_bold_and_bulleted_gate_lines_are_recognised(self):
        for gate_line in ("**Gate:**", "- Gate:"):
            with self.subTest(gate_line=gate_line):
                text = _plan("### Task T1: A", gate_line, "- files: a.py", "- green: make test")
                gate = pg.parse_gate(text, "T1")
                self.assertEqual(gate.line, 2)
                self.assertEqual(gate.files, ("a.py",))

    def test_tc04_test_case_ids_in_plan_order_and_fences_ignored(self):
        text = _plan(
            "### Task T1: A",
            "Gate:",
            "- files: a.py",
            "- green: make test",
            "",
            "Test Cases:",
            "- TC1: first",
            "- TC2 (guard): second",
            "* **TC3**: third",
            "```",
            "- TC9: inside a fence",
            "```",
        )
        self.assertEqual(pg.parse_gate(text, "T1").case_ids, ("TC1", "TC2", "TC3"))

    def test_tc05_skills_line(self):
        self.assertEqual(
            _skills_of("Skills: /a/x/SKILL.md, `/b/y/SKILL.md`"),
            ("/a/x/SKILL.md", "/b/y/SKILL.md"),
        )
        self.assertEqual(_skills_of("Skills: none"), ())
        self.assertEqual(_skills_of("Verifier Skills: /c/SKILL.md"), ())

    def test_tc06_each_task_reads_only_its_own_block(self):
        text = _plan(
            "### Task T1: A",
            "Gate:",
            "- files: a.py",
            "- green: make test",
            "",
            "### Task T2: B",
            "Gate:",
            "- files: b.py",
            "- green: make lint",
        )
        gate = pg.parse_gate(text, "T2")
        self.assertEqual(gate.task_id, "T2")
        self.assertEqual(gate.files, ("b.py",))
        self.assertEqual(gate.green, ("make lint",))

    def test_tc07_unknown_task(self):
        self.assertEqual(_error(_one(*GATE), "T9"), "no task T9 in the plan")

    def test_tc08_task_without_gate_line(self):
        text = _one("Some text", "- green: make test")
        self.assertEqual(_error(text, "T1"), "task T1 has no Gate block")

    def test_tc09_two_gate_lines(self):
        text = _one(
            "Gate:", "- files: a.py", "- green: make test",
            "",
            "Gate:", "- files: b.py", "- green: make lint",
        )
        self.assertEqual(_error(text, "T1"), "task T1: two Gate lines")

    def test_tc10_unknown_gate_item(self):
        text = _one("Gate:", "- files: a.py", "- run: make x", "- green: make test")
        self.assertEqual(
            _error(text, "T1"),
            "task T1: unknown gate item 'run' (use files, tests, red, guard or green)",
        )

    def test_tc11_empty_value(self):
        text = _one("Gate:", "- files: a.py", "- green:")
        self.assertEqual(_error(text, "T1"), "task T1: empty green line")

    def test_tc12_missing_files_and_green_lines(self):
        self.assertEqual(
            _error(_one("Gate:", "- green: make test"), "T1"),
            "task T1: Gate block has no files line",
        )
        self.assertEqual(
            _error(_one("Gate:", "- files: a.py"), "T1"),
            "task T1: Gate block has no green line",
        )

    def test_tc13_red_line_needs_tests_line(self):
        text = _one(
            "Gate:", "- files: a.py", "- red: python3 -B -m unittest x", "- green: make test",
        )
        self.assertEqual(
            _error(text, "T1"), "task T1: red or guard lines need a tests line",
        )

    def test_tc14_duplicate_test_case_id(self):
        text = _one(*GATE, "Test Cases:", "- TC2: a", "- TC2: b")
        self.assertEqual(_error(text, "T1"), "task T1: duplicate Test Case ID TC2")

    def test_tc15_blank_line_ends_the_block(self):
        text = _one("Gate:", "- files: a.py", "- green: make test", "", "- green: make lint")
        self.assertEqual(pg.parse_gate(text, "T1").green, ("make test",))

    def test_tc16_gate_inside_fence_is_ignored(self):
        text = _plan("### Task T1: A", "```", "Gate:", "- files: a.py", "- green: make test", "```")
        self.assertEqual(_error(text, "T1"), "task T1 has no Gate block")

    def test_tc17_helpers_are_public_and_parse_plan_is_unchanged(self):
        self.assertTrue(callable(getattr(pc, "fence_mask", None)))
        self.assertTrue(callable(getattr(pc, "task_spans", None)))
        self.assertFalse(hasattr(pc, "_fence_mask"))
        self.assertFalse(hasattr(pc, "_task_spans"))
        plan = pc.parse_plan(_plan(
            "### Task T1: A", "Contract:", "- provides: symbol f in a.py -- (x) -> y",
        ))
        self.assertEqual(tuple(task.task_id for task in plan.tasks), ("T1",))
        self.assertEqual(len(plan.tasks[0].provides), 1)


if __name__ == "__main__":
    unittest.main()
