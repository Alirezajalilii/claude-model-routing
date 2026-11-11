from __future__ import annotations

import ast
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import routing_config as rc  # noqa: E402

CONFIG = rc.load_config()
SW_PATH = ROOT / "scripts" / "stall_watch.py"

# How each executor tool builds its repeat key: "whole" = the whole input,
# "fields" = only the fields in stall_watch.call_key_fields, "ignored" = not watched.
EXPECTED = {"Read": "whole", "Edit": "whole", "Write": "whole", "Grep": "whole",
            "Glob": "whole", "Skill": "whole", "Bash": "fields",
            "Monitor": "ignored", "TaskStop": "ignored"}

# Fields each keyed tool identifies a call by. Changing the shipped list means
# changing this table on purpose.
DOCUMENTED_FIELDS = {"Bash": {"command", "timeout", "run_in_background"}}


def _text_files() -> list:
    bin_files = [p for p in (ROOT / "bin").iterdir() if p.is_file()]
    return sorted([*(ROOT / "scripts").glob("*.py"), *bin_files])


def _functions_referencing(tree: ast.AST, name: str) -> set:
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if any(isinstance(n, ast.Name) and n.id == name for n in ast.walk(node)):
                found.add(node.name)
    return found


class ToolClassTest(unittest.TestCase):
    def test_every_executor_tool_is_classified(self) -> None:
        self.assertEqual(
            set(CONFIG.roles["executor"].tools), set(EXPECTED),
            "classify the new executor tool in tests/test_stall_watch_key_guard.py "
            "and in stall_watch.call_key_fields")

    def test_classes_match_config(self) -> None:
        keyed = dict(CONFIG.stall_watch.call_key_fields)
        ignored = set(CONFIG.stall_watch.ignored_tools)
        for tool, kind in EXPECTED.items():
            with self.subTest(tool=tool, kind=kind):
                self.assertEqual(tool in keyed, kind == "fields")
                self.assertEqual(tool in ignored, kind == "ignored")


class FieldTableTest(unittest.TestCase):
    def test_listed_fields_match_documented_table(self) -> None:
        listed = {tool: set(fields) for tool, fields in CONFIG.stall_watch.call_key_fields}
        self.assertEqual(listed, DOCUMENTED_FIELDS)


class SingleKeyPlaceTest(unittest.TestCase):
    def test_only_stall_watch_builds_identity_from_tool_input(self) -> None:
        offenders = []
        for path in _text_files():
            if path == SW_PATH:
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
            if "tool_input" in text and ("hashlib" in text or "sort_keys" in text):
                offenders.append(path.name)
        self.assertEqual(offenders, [])


class AstKeyTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tree = ast.parse(SW_PATH.read_text(encoding="utf-8"))

    def test_only_call_key_uses_hashlib(self) -> None:
        self.assertEqual(_functions_referencing(self.tree, "hashlib"), {"call_key"})

    def test_observe_and_find_signal_skip_json_and_hashlib(self) -> None:
        for name in ("observe", "_find_signal"):
            for module in ("json", "hashlib"):
                with self.subTest(function=name, module=module):
                    self.assertNotIn(name, _functions_referencing(self.tree, module))


if __name__ == "__main__":
    unittest.main()
