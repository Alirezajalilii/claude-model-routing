from __future__ import annotations

import concurrent.futures
import dataclasses
import io
import json
import os
import re
import stat
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from typing import Optional
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import routing_config as rc  # noqa: E402
import stall_watch as sw  # noqa: E402

CONFIG = rc.load_config()
PREFIX = "mr stall watch:"
ENV = "CLAUDE_PLUGIN_DATA"
STATE_DIR = "stall-watch"
BASH_CMD = "python3 -m unittest"
BASH_DENIED = f"{PREFIX} you made this exact Bash call 4 times"
HOOK = "scripts/stall_watch.py"
HOOK_COMMAND = 'python3 -B "${CLAUDE_PLUGIN_ROOT}/scripts/stall_watch.py"'
HEX16 = re.compile(r"[0-9a-f]{16}")


def event(tool: str, tool_input: object, agent_id: str = "a1",
          agent_type: str = "mr:exec-haiku-low") -> dict:
    return {"tool_name": tool, "tool_input": tool_input,
            "agent_id": agent_id, "agent_type": agent_type}


def bash_event(cmd: str, **kwargs: str) -> dict:
    return event("Bash", {"command": cmd}, **kwargs)


def read_event(path: str, **kwargs: str) -> dict:
    return event("Read", {"file_path": path}, **kwargs)


def without(ev: dict, key: str) -> dict:
    return {k: v for k, v in ev.items() if k != key}


def smoke_event(n: int, agent_id: str = "a1") -> dict:
    """Call n of the live-run smoke: same command, description reworded each time."""
    return event("Bash", {"command": "git status --short",
                          "description": f"Run git status --short (call {n} of 5)"},
                 agent_id=agent_id)


class HookCase(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.data_dir = str(self.tmp)
        patcher = mock.patch.dict(os.environ, {ENV: self.data_dir})
        patcher.start()
        self.addCleanup(patcher.stop)

    def state_file(self, agent_id: str = "a1") -> Path:
        return self.tmp / STATE_DIR / f"{agent_id}.json"

    def evaluate(self, ev: dict) -> Optional[str]:
        return sw.evaluate(ev, CONFIG, self.data_dir, time.time())

    def run_calls(self, events: list) -> list:
        return [self.evaluate(ev) for ev in events]

    def run_main(self, ev: dict) -> tuple:
        err = io.StringIO()
        code = sw.main(stdin=io.StringIO(json.dumps(ev)), stderr=err)
        return code, err.getvalue()


class StatePathTest(unittest.TestCase):
    def test_blank_data_dir_gives_none(self) -> None:
        for data_dir in ("", "   "):
            with self.subTest(data_dir=data_dir):
                self.assertIsNone(sw.state_path(data_dir, "a1"))

    def test_unsafe_agent_id_gives_none(self) -> None:
        for agent_id in ("../x", "", 5, "a" * 65):
            with self.subTest(agent_id=agent_id):
                self.assertIsNone(sw.state_path("D", agent_id))

    def test_safe_agent_id_maps_to_state_file(self) -> None:
        self.assertEqual(sw.state_path("D", "a1"), Path("D") / STATE_DIR / "a1.json")


class ScopeTest(HookCase):
    def test_event_without_agent_id_is_ignored(self) -> None:
        ev = without(bash_event(BASH_CMD), "agent_id")
        self.assertEqual(self.run_calls([ev] * 4), [None] * 4)
        self.assertFalse((self.tmp / STATE_DIR).exists())

    def test_other_agent_types_are_not_watched(self) -> None:
        for agent_type in ("mr:verify-sonnet-med", "general-purpose", None):
            with self.subTest(agent_type=agent_type):
                ev = bash_event(BASH_CMD)
                if agent_type is None:
                    ev = without(ev, "agent_type")
                else:
                    ev["agent_type"] = agent_type
                self.assertEqual(self.run_calls([ev] * 4), [None] * 4)
        self.assertFalse(self.state_file().exists())

    def test_bare_tier_name_is_watched(self) -> None:
        ev = bash_event(BASH_CMD, agent_type="exec-haiku-low")
        results = self.run_calls([ev] * 4)
        self.assertIsNone(results[2])
        self.assertIsNotNone(results[3])
        self.assertTrue(results[3].startswith(BASH_DENIED), results[3])


class SwitchTest(HookCase):
    def test_disabled_watch_does_nothing(self) -> None:
        stall = dataclasses.replace(CONFIG.stall_watch, enabled=False)
        cfg = dataclasses.replace(CONFIG, stall_watch=stall)
        results = [sw.evaluate(bash_event(BASH_CMD), cfg, self.data_dir, time.time())
                   for _ in range(4)]
        self.assertEqual(results, [None] * 4)
        self.assertFalse(self.state_file().exists())

    def test_monitor_is_ignored(self) -> None:
        self.assertIsNone(self.evaluate(event("Monitor", {"command": "sleep 5"})))
        self.assertFalse(self.state_file().exists())

    def test_blank_data_dir_is_ignored(self) -> None:
        results = [sw.evaluate(bash_event(BASH_CMD), CONFIG, "", time.time())
                   for _ in range(4)]
        self.assertIsNone(results[3])

    def test_missing_fcntl_fails_open(self) -> None:
        with mock.patch.object(sw, "fcntl", None):
            results = self.run_calls([bash_event(BASH_CMD)] * 4)
        self.assertEqual(results, [None] * 4)
        self.assertFalse(self.state_file().exists())


class RepeatTest(HookCase):
    def test_fourth_identical_call_is_denied(self) -> None:
        results = self.run_calls([bash_event(BASH_CMD)] * 4)
        self.assertEqual(results[:3], [None] * 3)
        self.assertIsNotNone(results[3])
        self.assertTrue(results[3].startswith(BASH_DENIED), results[3])
        state = sw.state_from_json(self.state_file().read_text(encoding="utf-8"))
        self.assertEqual(state.nudges, 1)

    def test_agents_have_separate_state(self) -> None:
        calls = []
        for _ in range(3):
            calls.append(bash_event(BASH_CMD, agent_id="a1"))
            calls.append(bash_event(BASH_CMD, agent_id="a2"))
        self.assertEqual(self.run_calls(calls), [None] * 6)
        message = self.evaluate(bash_event(BASH_CMD, agent_id="a1"))
        self.assertIsNotNone(message)
        self.assertTrue(message.startswith(BASH_DENIED), message)

    def test_corrupt_state_is_treated_as_fresh(self) -> None:
        path = self.state_file()
        path.parent.mkdir(parents=True)
        path.write_text("not json", encoding="utf-8")
        self.assertIsNone(self.evaluate(read_event("f")))
        state = sw.state_from_json(path.read_text(encoding="utf-8"))
        self.assertEqual(state.streak, 1)
        self.assertEqual(len(state.history), 1)


class RepeatWithDescriptionHookTest(HookCase):
    def test_fourth_call_with_new_description_is_denied(self) -> None:
        results = [self.run_main(smoke_event(n)) for n in range(1, 6)]
        self.assertEqual(results[:3], [(0, "")] * 3)
        code, err = results[3]
        self.assertEqual(code, 2)
        self.assertTrue(err.startswith(BASH_DENIED), err)
        self.assertEqual(err.count("\n"), 1)
        self.assertEqual(results[4], (0, ""))

    def test_state_keeps_digests_not_raw_description(self) -> None:
        for n in range(1, 4):
            self.assertEqual(self.run_main(smoke_event(n)), (0, ""))
        state = sw.state_from_json(self.state_file().read_text(encoding="utf-8"))
        self.assertEqual(len(state.history), 3)
        for key in state.history:
            self.assertIsNotNone(HEX16.fullmatch(key), key)
        self.assertNotIn("Run git status", self.state_file().read_text(encoding="utf-8"))

    def test_each_agent_has_its_own_count(self) -> None:
        for n in range(1, 6):
            with self.subTest(n=n):
                self.assertEqual(self.run_main(smoke_event(n, agent_id=f"agent{n}")), (0, ""))


class StateFileTest(HookCase):
    def test_state_file_is_private(self) -> None:
        self.evaluate(read_event("f"))
        mode = stat.S_IMODE(self.state_file().stat().st_mode)
        self.assertEqual(mode, 0o600)

    def test_symlink_at_state_path_is_not_followed(self) -> None:
        state_dir = self.tmp / STATE_DIR
        state_dir.mkdir()
        victim = self.tmp / "victim.txt"
        victim.write_text("keep", encoding="utf-8")
        os.symlink(victim, state_dir / "a1.json")
        code, _ = self.run_main(read_event("f"))
        self.assertEqual(code, 0)
        self.assertEqual(victim.read_text(encoding="utf-8"), "keep")


class PruneTest(HookCase):
    def test_prunes_only_old_regular_state_files(self) -> None:
        state_dir = self.tmp / STATE_DIR
        state_dir.mkdir()
        now = time.time()
        old = now - 48 * 3600
        target = self.tmp / "target.json"
        target.write_text("{}", encoding="utf-8")
        os.utime(target, (old, old))
        for name, when in (("old.json", old), ("notes.txt", old), ("fresh.json", now)):
            path = state_dir / name
            path.write_text("{}", encoding="utf-8")
            os.utime(path, (when, when))
        os.symlink(target, state_dir / "link.json")
        sw.evaluate(read_event("f", agent_id="newagent"), CONFIG, self.data_dir, now)
        names = sorted(p.name for p in state_dir.iterdir())
        self.assertEqual(names, ["fresh.json", "link.json", "newagent.json", "notes.txt"])
        self.assertTrue(target.exists())


class MainTest(HookCase):
    def test_unparseable_or_non_object_stdin_is_ignored(self) -> None:
        for text in ("not json", "[]", "{}"):
            with self.subTest(text=text):
                err = io.StringIO()
                code = sw.main(stdin=io.StringIO(text), stderr=err)
                self.assertEqual(code, 0)
                self.assertEqual(err.getvalue(), "")

    def test_event_without_agent_id_skips_config(self) -> None:
        ev = without(bash_event(BASH_CMD), "agent_id")
        with mock.patch.object(sw.rc, "load_config") as load:
            code, _ = self.run_main(ev)
        self.assertEqual(code, 0)
        load.assert_not_called()

    def test_config_error_is_reported_and_fails_open(self) -> None:
        with mock.patch.object(sw.rc, "load_config", side_effect=rc.ConfigError("bad")):
            code, err = self.run_main(bash_event(BASH_CMD))
        self.assertEqual(code, 0)
        self.assertIn("stall watch: config unavailable (bad)", err)

    def test_unexpected_error_fails_open_silently(self) -> None:
        with mock.patch.object(sw, "evaluate", side_effect=RuntimeError("boom")):
            code, err = self.run_main(bash_event(BASH_CMD))
        self.assertEqual(code, 0)
        self.assertEqual(err, "")

    def test_denial_writes_one_stderr_line(self) -> None:
        ev = bash_event(BASH_CMD)
        for _ in range(3):
            self.assertEqual(self.run_main(ev), (0, ""))
        code, err = self.run_main(ev)
        self.assertEqual(code, 2)
        self.assertTrue(err.startswith(BASH_DENIED), err)
        self.assertTrue(err.endswith("\n"))
        self.assertEqual(err.count("\n"), 1)


class ConcurrencyTest(HookCase):
    def test_parallel_calls_keep_every_update(self) -> None:
        def one(i: int) -> Optional[str]:
            return sw.evaluate(read_event(f"f{i}"), CONFIG, self.data_dir, time.time())

        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(one, range(8)))
        self.assertEqual(results, [None] * 8)
        state = sw.state_from_json(self.state_file().read_text(encoding="utf-8"))
        self.assertEqual(state.streak, 8)
        self.assertEqual(len(state.history), 8)


class HooksJsonTest(unittest.TestCase):
    def test_stall_watch_group_is_wired(self) -> None:
        hooks = json.loads((ROOT / "hooks" / "hooks.json").read_text(encoding="utf-8"))
        pre = hooks["hooks"]["PreToolUse"]
        self.assertEqual(pre[0]["matcher"], "Agent|Task|Skill")
        self.assertIn("dispatch_guard.py", pre[0]["hooks"][0]["command"])
        groups = [g for g in pre if any("stall_watch.py" in h["command"] for h in g["hooks"])]
        self.assertEqual(len(groups), 1)
        group = groups[0]
        self.assertEqual(len(group["hooks"]), 1)
        self.assertEqual(group["hooks"][0]["type"], "command")
        self.assertEqual(group["hooks"][0]["command"], HOOK_COMMAND)
        self.assertEqual(group["hooks"][0]["timeout"], 10)
        matched = set(group["matcher"].split("|"))
        expected: set = set()
        for role in CONFIG.stall_watch.roles:
            expected |= set(CONFIG.roles[role].tools) - set(CONFIG.stall_watch.ignored_tools)
        self.assertLessEqual(expected, matched)
        self.assertNotIn("Agent", matched)
        self.assertNotIn("Task", matched)


class ProcessTest(HookCase):
    def run_hook(self, stdin_text: str) -> subprocess.CompletedProcess:
        env = {**os.environ, ENV: self.data_dir, "PYTHONDONTWRITEBYTECODE": "1"}
        return subprocess.run(
            [sys.executable, "-B", HOOK], input=stdin_text, capture_output=True,
            text=True, cwd=ROOT, env=env, timeout=30)

    def test_no_agent_id_exits_zero_silently(self) -> None:
        proc = self.run_hook("{}")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(proc.stdout, "")
        self.assertEqual(proc.stderr, "")

    def test_fourth_call_exits_two_in_subprocess(self) -> None:
        text = json.dumps(bash_event(BASH_CMD))
        runs = [self.run_hook(text) for _ in range(4)]
        for proc in runs[:3]:
            self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(runs[3].returncode, 2, runs[3].stderr)
        self.assertTrue(runs[3].stderr.startswith(BASH_DENIED), runs[3].stderr)
        for proc in runs:
            self.assertEqual(proc.stdout, "")

    def test_smoke_descriptions_exit_codes_in_subprocess(self) -> None:
        runs = [self.run_hook(json.dumps(smoke_event(n))) for n in range(1, 6)]
        self.assertEqual([proc.returncode for proc in runs], [0, 0, 0, 2, 0])
        stderr = runs[3].stderr
        self.assertTrue(stderr.startswith(BASH_DENIED), stderr)
        self.assertEqual(stderr.count("\n"), 1, stderr)


if __name__ == "__main__":
    unittest.main()
