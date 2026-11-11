"""Tests for scripts/plan_contract.py: plan grammar, parsing and validation messages."""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import plan_contract as pc  # noqa: E402

E1 = "no tasks found: task headings must read '### Task <id>: <title>'"
PROVIDE = "- provides: symbol x in a.py -- (a) -> b"


def _plan(*lines):
    return "\n".join(lines) + "\n"


def _line(text, needle, occurrence=1):
    hits = [n for n, line in enumerate(text.splitlines(), 1) if needle in line]
    return hits[occurrence - 1]


def _at(text, needle, body, occurrence=1):
    return "line %d: %s" % (_line(text, needle, occurrence), body)


def _contract_plan(*items):
    return _plan("### Task T1: A", "Contract:", *items)


def _two_tasks(requires_item, provide=PROVIDE):
    return _plan(
        "### Task T1: A",
        "Contract:",
        provide,
        "",
        "### Task T2: B",
        "Contract:",
        requires_item,
    )


TWO_TASKS = _plan(
    "# Plan",
    "",
    "### Task T1: Parser",
    "Contract:",
    "- provides: symbol parse_plan in scripts/plan_contract.py -- (text: str) -> PlanContract",
    "",
    "### Task T2: Waves",
    "Contract:",
    "- requires: T1 parse_plan -- (text: str) -> PlanContract",
)


class ParseTest(unittest.TestCase):
    def test_tc01_two_tasks_parse_and_validate(self):
        plan = pc.parse_plan(TWO_TASKS)
        self.assertEqual(tuple(t.task_id for t in plan.tasks), ("T1", "T2"))
        self.assertEqual(tuple(t.title for t in plan.tasks), ("Parser", "Waves"))
        provide = plan.tasks[0].provides[0]
        self.assertEqual(
            provide,
            pc.Provide(
                task="T1",
                kind="symbol",
                name="parse_plan",
                path="scripts/plan_contract.py",
                shape="(text: str) -> PlanContract",
                line=_line(TWO_TASKS, "- provides: symbol parse_plan"),
            ),
        )
        require = plan.tasks[1].requires[0]
        self.assertEqual(require.provider, "T1")
        self.assertEqual(require.name, "parse_plan")
        self.assertEqual(pc.validate(plan), [])

    def test_tc02_backticks_are_removed(self):
        text = _contract_plan("- provides: symbol `parse_plan` in `scripts/plan_contract.py`")
        provide = pc.parse_plan(text).tasks[0].provides[0]
        self.assertEqual(provide.name, "parse_plan")
        self.assertEqual(provide.path, "scripts/plan_contract.py")

    def test_tc03_em_dash_separates_shape(self):
        text = _contract_plan("- provides: flag --waves in scripts/plan_cli.py — prints waves")
        provide = pc.parse_plan(text).tasks[0].provides[0]
        self.assertEqual(
            (provide.kind, provide.name, provide.shape),
            ("flag", "--waves", "prints waves"),
        )

    def test_tc04_file_provide(self):
        text = _contract_plan("- provides: file scripts/plan_waves.py")
        provide = pc.parse_plan(text).tasks[0].provides[0]
        self.assertEqual(
            (provide.kind, provide.name, provide.path),
            ("file", "scripts/plan_waves.py", ""),
        )
        self.assertEqual(pc.validate(pc.parse_plan(text)), [])

    def test_tc05_contract_none_has_no_items(self):
        for contract_line in ("Contract: none", "**Contract:** none", "Contract:none"):
            with self.subTest(line=contract_line):
                text = _plan("### Task T1: A", contract_line)
                task = pc.parse_plan(text).tasks[0]
                self.assertEqual(len(task.contract_lines), 1)
                self.assertEqual((task.provides, task.requires, task.after), ((), (), ()))
                self.assertEqual(pc.validate(pc.parse_plan(text)), [])

    def test_tc06_after_ids(self):
        text = _plan(
            "### Task T1: A",
            "Contract: none",
            "",
            "### Task T2: B",
            "Contract:",
            "- after: T1, T3",
            "",
            "### Task T3: C",
            "Contract: none",
        )
        task = pc.parse_plan(text).tasks[1]
        self.assertEqual(tuple(task_id for task_id, _ in task.after), ("T1", "T3"))
        self.assertEqual(pc.validate(pc.parse_plan(text)), [])

    def test_tc07_block_ends_at_blank_line_and_bold_bullet(self):
        text = _plan(
            "### Task T1: A",
            "Contract:",
            "- provides: symbol one in a.py",
            "",
            "- provides: symbol other in a.py",
        )
        task = pc.parse_plan(text).tasks[0]
        self.assertEqual(tuple(p.name for p in task.provides), ("one",))
        self.assertEqual(pc.parse_plan(text).errors, ())

        text = _plan(
            "### Task T1: A",
            "- **Contract:**",
            "  - provides: symbol a in a.py",
            "- **Steps:**",
            "  1. do it",
        )
        plan = pc.parse_plan(text)
        self.assertEqual(len(plan.tasks[0].provides), 1)
        self.assertEqual(plan.errors, ())

    def test_tc07b_bulleted_contract_none(self):
        text = _plan("### Task T1: A", "- Contract: none")
        task = pc.parse_plan(text).tasks[0]
        self.assertEqual(len(task.contract_lines), 1)
        self.assertEqual((task.provides, task.requires, task.after), ((), (), ()))
        self.assertEqual(pc.validate(pc.parse_plan(text)), [])

    def test_tc08_contract_under_risks_is_not_attributed(self):
        text = _plan(
            "### Task T1: A",
            "Contract:",
            "- provides: symbol a in a.py",
            "",
            "## Risks",
            "Contract:",
            "- provides: symbol b in a.py",
        )
        task = pc.parse_plan(text).tasks[0]
        self.assertEqual(tuple(p.name for p in task.provides), ("a",))
        self.assertEqual(task.contract_lines, (_line(text, "Contract:"),))

    def test_tc09_fenced_block_is_ignored(self):
        text = _plan(
            "### Task T1: A",
            "```markdown",
            "## Heading",
            "Contract:",
            "- provides: symbol fake in a.py",
            "```",
            "Contract:",
            "- provides: symbol real in a.py",
        )
        plan = pc.parse_plan(text)
        self.assertEqual(len(plan.tasks), 1)
        task = plan.tasks[0]
        self.assertEqual(tuple(p.name for p in task.provides), ("real",))
        self.assertEqual(task.contract_lines, (_line(text, "Contract:", 2),))

    def test_tc25_parse_never_raises(self):
        for text in ("", "\x00### Task"):
            with self.subTest(text=text):
                self.assertIsInstance(pc.parse_plan(text), pc.PlanContract)


class ValidateTest(unittest.TestCase):
    def test_tc10_no_task_heading_gives_only_e1(self):
        self.assertEqual(pc.validate(pc.parse_plan("# Plan\n\nno task here\n")), [E1])

    def test_tc11_duplicate_task_id(self):
        text = _plan("### Task T1: A", "Contract: none", "", "### Task T1: B", "Contract: none")
        self.assertEqual(
            pc.validate(pc.parse_plan(text)),
            [_at(text, "### Task T1: B", "duplicate task id T1 (first at line 1)")],
        )

    def test_tc12_task_without_contract_line(self):
        text = _plan("### Task T1: A", "Contract: none", "", "### Task T2: B", "Some prose.")
        self.assertEqual(
            pc.validate(pc.parse_plan(text)),
            [_at(text, "### Task T2", "task T2: no Contract line")],
        )

    def test_tc13_no_contract_line_anywhere(self):
        text = _plan("### Task T1: A", "prose", "", "### Task T2: B", "prose")
        self.assertEqual(pc.validate(pc.parse_plan(text)), ["no task has a Contract line"])

    def test_tc14_unknown_kind(self):
        text = _contract_plan("- provides: widget x in a.py")
        self.assertEqual(
            pc.validate(pc.parse_plan(text)),
            [
                _at(
                    text,
                    "- provides: widget",
                    "task T1: unknown kind 'widget' "
                    "(use symbol, file, config, env, flag, endpoint or id)",
                )
            ],
        )

    def test_tc15_path_rules_for_kinds(self):
        text = _contract_plan("- provides: file a.py in b.py")
        self.assertEqual(
            pc.validate(pc.parse_plan(text)),
            [_at(text, "- provides: file", "task T1: a file provide takes no 'in'")],
        )
        text = _contract_plan("- provides: symbol x")
        self.assertEqual(
            pc.validate(pc.parse_plan(text)),
            [_at(text, "- provides: symbol", "task T1: symbol x needs 'in <path>'")],
        )

    def test_tc16_unsafe_paths(self):
        cases = [
            ("- provides: symbol x in /etc/hosts", "/etc/hosts"),
            ("- provides: symbol x in ../a.py", "../a.py"),
            ("- provides: file ~x/a.py", "~x/a.py"),
        ]
        for item, path in cases:
            with self.subTest(item=item):
                text = _contract_plan(item)
                self.assertEqual(
                    pc.validate(pc.parse_plan(text)),
                    [
                        _at(
                            text,
                            item,
                            "task T1: path '%s' must be relative and stay inside the repository"
                            % path,
                        )
                    ],
                )

    def test_tc17_unknown_item_verb(self):
        text = _contract_plan("- needs: T1 x")
        self.assertEqual(
            pc.validate(pc.parse_plan(text)),
            [
                _at(
                    text,
                    "- needs:",
                    "task T1: unknown contract item 'needs' "
                    "(use provides, requires or after)",
                )
            ],
        )

    def test_tc18_contract_none_with_items(self):
        text = _plan(
            "### Task T1: A",
            "Contract: none",
            "- after: T2",
            "",
            "### Task T2: B",
            "Contract: none",
        )
        self.assertEqual(
            pc.validate(pc.parse_plan(text)),
            [_at(text, "- after: T2", "task T1: Contract: none has items")],
        )

    def test_tc19_two_contract_lines(self):
        text = _plan("### Task T1: A", "Contract:", "- provides: symbol x in a.py", "Contract:")
        self.assertEqual(
            pc.validate(pc.parse_plan(text)),
            [_at(text, "Contract:", "task T1: two Contract lines", occurrence=2)],
        )

    def test_tc20_malformed_items(self):
        text = _contract_plan("- provides: symbol")
        self.assertEqual(
            pc.validate(pc.parse_plan(text)),
            [
                _at(
                    text,
                    "- provides: symbol",
                    "task T1: malformed provides "
                    "(use '<kind> <name> in <path> -- <shape>')",
                )
            ],
        )
        text = _plan(
            "### Task T1: A",
            "Contract:",
            "- provides: symbol x in a.py",
            "",
            "### Task T2: B",
            "Contract:",
            "- requires: T1",
        )
        self.assertEqual(
            pc.validate(pc.parse_plan(text)),
            [
                _at(
                    text,
                    "- requires: T1",
                    "task T2: malformed requires "
                    "(use '<task-id> <name> -- <shape>')",
                )
            ],
        )
        text = _contract_plan("- after:")
        self.assertEqual(
            pc.validate(pc.parse_plan(text)),
            [
                _at(
                    text,
                    "- after:",
                    "task T1: malformed after (use '<task-id>, <task-id>')",
                )
            ],
        )

    def test_tc21_provides_twice(self):
        text = _contract_plan("- provides: symbol x in a.py", "- provides: symbol x in b.py")
        self.assertEqual(
            pc.validate(pc.parse_plan(text)),
            [_at(text, "- provides", "task T1: provides 'x' twice", occurrence=2)],
        )

    def test_tc22_requires_errors(self):
        text = _two_tasks("- requires: T9 x")
        self.assertEqual(
            pc.validate(pc.parse_plan(text)),
            [_at(text, "- requires:", "task T2: requires unknown task T9")],
        )

        text = _plan(
            "### Task T1: A",
            "Contract:",
            "- provides: symbol x in a.py",
            "",
            "### Task T2: B",
            "Contract:",
            "- provides: symbol y in b.py",
            "- requires: T2 y",
        )
        self.assertEqual(
            pc.validate(pc.parse_plan(text)),
            [_at(text, "- requires:", "task T2: requires itself")],
        )

        text = _two_tasks("- requires: T1 missing_name")
        self.assertEqual(
            pc.validate(pc.parse_plan(text)),
            [_at(text, "- requires:", "task T2: T1 provides no 'missing_name'")],
        )

        text = _two_tasks("- requires: T1 x -- (a)  ->  c")
        provide_line = _line(text, "- provides: symbol x")
        self.assertEqual(
            pc.validate(pc.parse_plan(text)),
            [
                _at(
                    text,
                    "- requires:",
                    "task T2: shape differs from T1's provides at line %d" % provide_line,
                )
            ],
        )

        text = _two_tasks("- requires: T1 x -- (a)   ->   b")
        self.assertEqual(pc.validate(pc.parse_plan(text)), [])

        text = _two_tasks("- requires: T1 x")
        self.assertEqual(pc.validate(pc.parse_plan(text)), [])

    def test_tc23_after_errors(self):
        text = _plan(
            "### Task T1: A",
            "Contract:",
            "- after: T9",
            "",
            "### Task T2: B",
            "Contract: none",
        )
        self.assertEqual(
            pc.validate(pc.parse_plan(text)),
            [_at(text, "- after: T9", "task T1: after unknown task T9")],
        )

        text = _plan(
            "### Task T1: A",
            "Contract: none",
            "",
            "### Task T2: B",
            "Contract:",
            "- after: T2",
        )
        self.assertEqual(
            pc.validate(pc.parse_plan(text)),
            [_at(text, "- after: T2", "task T2: after itself")],
        )

    def test_tc24_errors_sorted_by_line(self):
        lines = ["# Plan", "", "### Task T1: A", "Contract:"]
        lines += ["- provides: symbol p%d in a.py -- (a) -> b" % i for i in range(7)]
        lines.append("- provides: widget w in a.py")
        lines += [""] * 15
        lines += ["### Task T2: B", "Contract:", "- requires: T1 p0 -- (a)   ->  c"]
        text = _plan(*lines)
        messages = pc.validate(pc.parse_plan(text))
        self.assertEqual(len(messages), 2, messages)
        self.assertTrue(messages[0].startswith("line 12: "), messages)
        self.assertTrue(messages[1].startswith("line 30: "), messages)


class FindProvideTest(unittest.TestCase):
    def test_tc26_find_provide(self):
        plan = pc.parse_plan(TWO_TASKS)
        found = pc.find_provide(plan, "T1", "parse_plan")
        self.assertIsInstance(found, pc.Provide)
        self.assertEqual(found.name, "parse_plan")
        self.assertIsNone(pc.find_provide(plan, "T1", "nope"))
        self.assertIsNone(pc.find_provide(plan, "T9", "parse_plan"))
