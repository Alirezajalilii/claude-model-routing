"""Tests for scripts/plan_waves.py: dependencies, wave layering, cycles and wave text."""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import plan_contract  # noqa: E402
import plan_waves  # noqa: E402


def _task(task_id, *items):
    lines = ["### Task %s: Title %s" % (task_id, task_id), ""]
    lines.append("Contract:" if items else "Contract: none")
    lines.extend(items)
    lines.append("")
    return lines


def _provide(name):
    return "- provides: symbol %s in m.py -- (x) -> y" % name


def _require(provider, name):
    return "- requires: %s %s" % (provider, name)


def _after(*ids):
    return "- after: %s" % ", ".join(ids)


def _parse(*tasks):
    lines = []  # type: list
    for task_lines in tasks:
        lines.extend(task_lines)
    return plan_contract.parse_plan("\n".join(lines) + "\n")


def _diamond():
    return _parse(
        _task("T1", _provide("a")),
        _task("T2", _require("T1", "a"), _provide("b")),
        _task("T3", _require("T1", "a"), _provide("c")),
        _task("T4", _require("T2", "b"), _after("T3")),
    )


def _cycle():
    return _parse(
        _task("T1", _require("T2", "b"), _provide("a")),
        _task("T2", _require("T1", "a"), _provide("b")),
    )


class DependenciesTest(unittest.TestCase):
    def test_requires_and_after_in_provider_order(self):
        deps = plan_waves.dependencies(_diamond())
        self.assertEqual(deps["T4"], ("T2", "T3"))

    def test_every_task_is_a_key_in_plan_order(self):
        deps = plan_waves.dependencies(_diamond())
        self.assertEqual(list(deps), ["T1", "T2", "T3", "T4"])
        self.assertEqual(deps["T1"], ())

    def test_duplicates_are_removed(self):
        plan = _parse(
            _task("T1", _provide("a"), _provide("b")),
            _task("T2", _require("T1", "a"), _require("T1", "b"), _after("T1")),
        )
        self.assertEqual(plan_waves.dependencies(plan)["T2"], ("T1",))

    def test_unknown_and_self_references_are_ignored(self):
        plan = _parse(
            _task("T1", _after("T9")),
            _task("T2", _after("T2")),
        )
        self.assertEqual(plan_waves.dependencies(plan), {"T1": (), "T2": ()})


class PlanWavesTest(unittest.TestCase):
    def test_independent_tasks_form_one_wave(self):
        plan = _parse(_task("T1"), _task("T2"), _task("T3"))
        wave_plan = plan_waves.plan_waves(plan)
        self.assertEqual(wave_plan.waves, (("T1", "T2", "T3"),))
        self.assertEqual(wave_plan.cycle, "")

    def test_chain_gives_one_task_per_wave(self):
        plan = _parse(
            _task("T1", _provide("a")),
            _task("T2", _require("T1", "a"), _provide("b")),
            _task("T3", _require("T2", "b")),
        )
        wave_plan = plan_waves.plan_waves(plan)
        self.assertEqual(wave_plan.waves, (("T1",), ("T2",), ("T3",)))

    def test_diamond_layers_and_dependencies(self):
        wave_plan = plan_waves.plan_waves(_diamond())
        self.assertEqual(wave_plan.waves, (("T1",), ("T2", "T3"), ("T4",)))
        self.assertEqual(wave_plan.dependencies["T4"], ("T2", "T3"))

    def test_plan_order_is_kept_inside_a_wave(self):
        plan = _parse(_task("T3"), _task("T1"), _task("T2"))
        wave_plan = plan_waves.plan_waves(plan)
        self.assertEqual(wave_plan.waves, (("T3", "T1", "T2"),))

    def test_after_only_dependency(self):
        plan = _parse(_task("T1"), _task("T2", _after("T1")))
        wave_plan = plan_waves.plan_waves(plan)
        self.assertEqual(wave_plan.waves, (("T1",), ("T2",)))

    def test_cycle_stalls_with_no_waves(self):
        wave_plan = plan_waves.plan_waves(_cycle())
        self.assertEqual(wave_plan.waves, ())
        self.assertEqual(wave_plan.cycle, "T1 -> T2 -> T1")

    def test_cycle_reached_through_a_non_cycle_task(self):
        plan = _parse(
            _task("T1", _after("T2")),
            _task("T2", _after("T3")),
            _task("T3", _after("T2")),
        )
        wave_plan = plan_waves.plan_waves(plan)
        self.assertEqual(wave_plan.waves, ())
        self.assertEqual(wave_plan.cycle, "T2 -> T3 -> T2")

    def test_unknown_and_self_references_do_not_block(self):
        plan = _parse(
            _task("T1", _after("T9")),
            _task("T2", _after("T2")),
        )
        wave_plan = plan_waves.plan_waves(plan)
        self.assertEqual(wave_plan.waves, (("T1", "T2"),))
        self.assertEqual(wave_plan.cycle, "")


class FormatWavesTest(unittest.TestCase):
    def test_diamond_text(self):
        text = plan_waves.format_waves(plan_waves.plan_waves(_diamond()))
        self.assertEqual(
            text,
            "wave 1: T1\nwave 2: T2 (T1), T3 (T1)\nwave 3: T4 (T2, T3)",
        )

    def test_independent_tasks_have_no_dependency_suffix(self):
        plan = _parse(_task("T1"), _task("T2"), _task("T3"))
        text = plan_waves.format_waves(plan_waves.plan_waves(plan))
        self.assertEqual(text, "wave 1: T1, T2, T3")

    def test_cycle_text(self):
        text = plan_waves.format_waves(plan_waves.plan_waves(_cycle()))
        self.assertEqual(text, "requires or after form a cycle: T1 -> T2 -> T1")

    def test_no_trailing_newline(self):
        text = plan_waves.format_waves(plan_waves.plan_waves(_diamond()))
        self.assertFalse(text.endswith("\n"))


if __name__ == "__main__":
    unittest.main()
