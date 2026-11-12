"""Public-repository hygiene: no empty workspace skeleton, no private paths (PL1)."""

from __future__ import annotations

import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

SKELETON_PREFIXES = (
    "apps/",
    "packages/",
    "infra/",
    "docs/wiki/",
    "docs/api/",
    "docs/runbooks/",
    "docs/specs/",
    "docs/decisions/",
)
SKELETON_EXACT = ("data/.gitkeep",)

# Built by concatenation so this file does not contain the strings it forbids.
PRIVATE_STRINGS = ("~/" + "Work", "Linux " + "workstation")
CLAUDE_SCRIPTS_PATH = "~/.claude/" + "scripts/"
DELETED_DOC_PATHS = (
    "docs/decisions/",
    "docs/specs/",
    "docs/api/",
    "docs/runbooks/",
    "docs/wiki/",
)


def _git_files(*args: str) -> list[str]:
    result = subprocess.run(
        ["git", "ls-files", "-z", *args],
        cwd=ROOT,
        check=True,
        capture_output=True,
    )
    return [p for p in result.stdout.decode("utf-8").split("\0") if p]


def _tracked_and_untracked() -> list[str]:
    return _git_files("--cached", "--others", "--exclude-standard")


class TestNoWorkspaceSkeleton(unittest.TestCase):
    def test_tc1_tracked_tree_has_no_skeleton_paths(self) -> None:
        # TC1: git ls-files lists no skeleton path.
        tracked = _git_files()
        offenders = [
            p
            for p in tracked
            if p.startswith(SKELETON_PREFIXES) or p in SKELETON_EXACT
        ]
        self.assertEqual(offenders, [], "skeleton paths still tracked")


class TestNoPrivatePaths(unittest.TestCase):
    def test_tc2_no_private_strings_in_repo_files(self) -> None:
        # TC2: no tracked or untracked-not-ignored file contains a private string.
        offenders: list[str] = []
        for rel in _tracked_and_untracked():
            path = ROOT / rel
            if not path.is_file():
                continue
            text = path.read_bytes().decode("utf-8", errors="ignore")
            for needle in PRIVATE_STRINGS:
                if needle in text:
                    offenders.append(f"{rel}: {needle}")
        self.assertEqual(offenders, [], "private strings found")

    def test_tc3_subagent_usage_has_no_home_script_path(self) -> None:
        # TC3: scripts/subagent_usage.py does not point at the private script.
        text = (ROOT / "scripts" / "subagent_usage.py").read_text(encoding="utf-8")
        self.assertNotIn(CLAUDE_SCRIPTS_PATH, text)


class TestReadmeLinks(unittest.TestCase):
    def test_tc4_readme_names_no_deleted_doc_paths(self) -> None:
        # TC4: README.md lists none of the deleted doc folders.
        text = (ROOT / "README.md").read_text(encoding="utf-8")
        found = [p for p in DELETED_DOC_PATHS if p in text]
        self.assertEqual(found, [], "README still names deleted doc paths")


if __name__ == "__main__":
    unittest.main()
