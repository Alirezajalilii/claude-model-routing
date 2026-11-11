from __future__ import annotations

import dataclasses
import json
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import routing_config as rc  # noqa: E402
import stall_watch as sw  # noqa: E402

SETTINGS = rc.load_config().stall_watch
PREFIX = "mr stall watch:"
HEX16 = re.compile(r"[0-9a-f]{16}")
REPEAT_CMD = "python3 -m unittest"
EDIT_NEW = "2"


def settings(**changes) -> rc.StallWatch:
    return dataclasses.replace(SETTINGS, **changes)


def bash(cmd: str) -> tuple:
    return ("Bash", {"command": cmd})


def read(path: str) -> tuple:
    return ("Read", {"file_path": path})


def edit(new: str) -> tuple:
    return ("Edit", {"file_path": "a.py", "old_string": "1", "new_string": new})


def fold(calls, cfg=SETTINGS, state=None):
    """Feed (tool, input) pairs through observe in order; return the final state and each verdict."""
    state = sw.WatchState() if state is None else state
    verdicts = []
    for tool, tool_input in calls:
        state, verdict = sw.observe(state, tool, tool_input, cfg, PREFIX)
        verdicts.append(verdict)
    return state, verdicts


def reads(*paths: str) -> list:
    return [read(path) for path in paths]


def reach_cut(cfg) -> tuple:
    """Return the state and the cut verdict after one nudged streak and a second streak."""
    state, _ = fold(reads("a", "b", "c"), cfg)
    state, verdicts = fold(reads("d", "e", "f"), cfg, state)
    return state, verdicts[2]


class CallKeyTest(unittest.TestCase):
    def test_key_ignores_dict_order(self) -> None:
        self.assertEqual(
            sw.call_key("Read", {"a": 1, "b": 2}), sw.call_key("Read", {"b": 2, "a": 1}))

    def test_key_differs_by_input_or_tool(self) -> None:
        base = sw.call_key("Read", {"a": 1})
        self.assertNotEqual(base, sw.call_key("Read", {"a": 2}))
        self.assertNotEqual(base, sw.call_key("Grep", {"a": 1}))

    def test_key_is_16_lowercase_hex(self) -> None:
        self.assertIsNotNone(HEX16.fullmatch(sw.call_key("Read", {"a": 1})))

    def test_unserialisable_input_still_keys(self) -> None:
        key = sw.call_key("Bash", {"x": object()})
        self.assertIsNotNone(HEX16.fullmatch(key))


class IsReadOnlyTest(unittest.TestCase):
    def test_read_tools_and_write_tools(self) -> None:
        for tool in ("Read", "Grep", "Glob"):
            with self.subTest(tool=tool):
                self.assertTrue(sw.is_read_only(tool, {"file_path": "a"}, SETTINGS))
        for tool in ("Edit", "Write", "Skill"):
            with self.subTest(tool=tool):
                self.assertFalse(sw.is_read_only(tool, {"file_path": "a"}, SETTINGS))

    def test_bash_read_only_commands(self) -> None:
        commands = (
            "git status --short",
            "ls -la && wc -l x.py",
            "cat a | grep b",
            "sed -n '1,20p' f",
            "  git log --oneline -1",
        )
        for cmd in commands:
            with self.subTest(cmd=cmd):
                self.assertTrue(sw.is_read_only("Bash", {"command": cmd}, SETTINGS))

    def test_bash_writes_and_malformed_inputs(self) -> None:
        commands = (
            "sed -i s/a/b/ f",
            "python3 -m unittest",
            "ls && rm x",
            "",
            "lsof",
            "git statusx",
        )
        inputs = [{"command": cmd} for cmd in commands] + [{}, "ls"]
        for tool_input in inputs:
            with self.subTest(tool_input=tool_input):
                self.assertFalse(sw.is_read_only("Bash", tool_input, SETTINGS))


class MonitorTest(unittest.TestCase):
    def test_monitor_is_ignored_in_any_state(self) -> None:
        fresh = sw.WatchState()
        cut = sw.WatchState((), 0, 1, "3 read-only calls in a row")
        for state in (fresh, cut):
            with self.subTest(state=state):
                new, verdict = sw.observe(
                    state, "Monitor", {"command": "sleep 5"}, SETTINGS, PREFIX)
                self.assertIs(new, state)
                self.assertIsNone(verdict)


class RepeatTest(unittest.TestCase):
    def test_fourth_identical_call_nudges(self) -> None:
        state, verdicts = fold([bash(REPEAT_CMD)] * 4)
        self.assertEqual(verdicts[:3], [None, None, None])
        nudge = verdicts[3]
        self.assertEqual(nudge.kind, "nudge")
        self.assertTrue(nudge.message.startswith(
            "mr stall watch: you made this exact Bash call 4 times"))
        for part in (
            "was not run",
            "run it in the background and wait with Monitor; Monitor calls are not counted",
            "reason=stalled",
            "every tool except Write will be denied",
        ):
            with self.subTest(part=part):
                self.assertIn(part, nudge.message)
        self.assertEqual(state, sw.WatchState((), 0, 1, ""))

    def test_wait_hint_needs_monitor_ignored(self) -> None:
        cfg = settings(ignored_tools=("TaskStop",))
        _, verdicts = fold([bash(REPEAT_CMD)] * 4, cfg)
        self.assertEqual(verdicts[3].kind, "nudge")
        self.assertNotIn("wait with Monitor", verdicts[3].message)


class ChangeTest(unittest.TestCase):
    def test_change_resets_history(self) -> None:
        calls = [bash(REPEAT_CMD)] * 3 + [edit(EDIT_NEW), bash(REPEAT_CMD)]
        _, verdicts = fold(calls)
        self.assertEqual(verdicts, [None] * 5)

    def test_identical_changes_count(self) -> None:
        _, verdicts = fold([edit(EDIT_NEW)] * 4)
        self.assertIsNone(verdicts[2])
        self.assertEqual(verdicts[3].kind, "nudge")
        self.assertIn("this exact Edit call 4 times", verdicts[3].message)


class WindowTest(unittest.TestCase):
    def test_window_forgets_old_calls(self) -> None:
        cfg = settings(repeat_window=5)
        calls = [bash(REPEAT_CMD), bash("echo 1"), bash("echo 2"), bash("echo 3"),
                 bash("echo 4"), bash(REPEAT_CMD), bash(REPEAT_CMD), bash(REPEAT_CMD)]
        state, verdicts = fold(calls, cfg)
        self.assertEqual(verdicts, [None] * 8)
        _, more = fold([bash(REPEAT_CMD)], cfg, state)
        self.assertEqual(more[0].kind, "nudge")


class StreakTest(unittest.TestCase):
    def test_streak_nudges_at_limit(self) -> None:
        cfg = settings(read_only_streak_limit=3)
        state, verdicts = fold(reads("a", "b", "c"), cfg)
        self.assertIsNone(verdicts[0])
        self.assertIsNone(verdicts[1])
        nudge = verdicts[2]
        self.assertEqual(nudge.kind, "nudge")
        self.assertTrue(nudge.message.startswith("mr stall watch: 3 read-only calls in a row"))
        self.assertNotIn("wait with Monitor", nudge.message)
        self.assertEqual(state, sw.WatchState((), 0, 1, ""))

    def test_non_read_call_resets_streak(self) -> None:
        cfg = settings(read_only_streak_limit=3)
        calls = reads("a", "b") + [bash(REPEAT_CMD)] + reads("c", "d")
        _, verdicts = fold(calls, cfg)
        self.assertEqual(verdicts, [None] * 5)


class CutTest(unittest.TestCase):
    def test_second_streak_cuts(self) -> None:
        cfg = settings(read_only_streak_limit=3, max_nudges=1)
        state, cut = reach_cut(cfg)
        self.assertEqual(cut.kind, "cut")
        self.assertTrue(cut.message.startswith(
            "mr stall watch: stalled (3 read-only calls in a row). "
            "Every tool except Write is now denied"))
        self.assertTrue(cut.message.endswith(
            "reply `BLOCKED <output path> reason=stalled: 3 read-only calls in a row`."))
        self.assertEqual(state.cut_signal, "3 read-only calls in a row")

    def test_cut_state_denies_until_write(self) -> None:
        cfg = settings(read_only_streak_limit=3, max_nudges=1)
        cut_state, cut = reach_cut(cfg)
        probes = [read("z"), edit(EDIT_NEW), ("Write", {"file_path": "a.py"}),
                  ("Monitor", {"command": "sleep 1"})]
        expected = [cut.kind, cut.kind, None, None]
        for (tool, tool_input), kind in zip(probes, expected):
            with self.subTest(tool=tool):
                new, verdict = sw.observe(cut_state, tool, tool_input, cfg, PREFIX)
                self.assertEqual(new, cut_state)
                if kind is None:
                    self.assertIsNone(verdict)
                else:
                    self.assertEqual(verdict.kind, kind)
                    self.assertEqual(verdict.message, cut.message)

    def test_zero_nudges_cuts_at_first_signal(self) -> None:
        cfg = settings(read_only_streak_limit=3, max_nudges=0)
        _, verdicts = fold(reads("a", "b", "c"), cfg)
        self.assertEqual(verdicts[2].kind, "cut")

    def test_second_nudge_warns_third_cuts(self) -> None:
        cfg = settings(read_only_streak_limit=3, max_nudges=2)
        state, first = fold(reads("a", "b", "c"), cfg)
        state, second = fold(reads("d", "e", "f"), cfg, state)
        _, third = fold(reads("g", "h", "i"), cfg, state)
        self.assertEqual(first[2].kind, "nudge")
        self.assertNotIn("If you stall again", first[2].message)
        self.assertEqual(second[2].kind, "nudge")
        self.assertIn("If you stall again", second[2].message)
        self.assertEqual(third[2].kind, "cut")


class PrecedenceTest(unittest.TestCase):
    def test_repeat_signal_beats_reads_signal(self) -> None:
        cfg = settings(read_only_streak_limit=4)
        _, verdicts = fold([read("a")] * 4, cfg)
        self.assertIn("this exact Read call 4 times", verdicts[3].message)


class StateJsonTest(unittest.TestCase):
    def test_round_trip(self) -> None:
        states = (
            sw.WatchState(("k1", "k2"), 3, 1, ""),
            sw.WatchState((), 0, 1, "3 read-only calls in a row"),
        )
        for state in states:
            with self.subTest(state=state):
                self.assertEqual(sw.state_from_json(sw.state_to_json(state)), state)

    def test_invalid_text_gives_empty_state(self) -> None:
        base = {"version": 1, "history": [], "streak": 0, "nudges": 0, "cut_signal": ""}
        bad = (
            {**base, "version": 2},
            {**base, "history": [5]},
            {**base, "streak": -1},
            {**base, "nudges": True},
            {**base, "cut_signal": 5},
        )
        texts = ["", "not json", "[]"] + [json.dumps(item) for item in bad]
        for text in texts:
            with self.subTest(text=text):
                self.assertEqual(sw.state_from_json(text), sw.WatchState())


class MessageLengthTest(unittest.TestCase):
    def test_cut_message_fits_status_line(self) -> None:
        state = sw.WatchState((), 0, 1, "same Bash call 40 times")
        _, verdict = sw.observe(state, "Read", {"file_path": "a"}, SETTINGS, PREFIX)
        self.assertEqual(verdict.kind, "cut")
        self.assertLess(len(verdict.message), 400)


if __name__ == "__main__":
    unittest.main()
