from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path

# TC1: tests/test_scan_sensitive.py and tests/test_sensitive_rules.py, restored from
# agent/T09, are the gate's own test files; the green commit makes them pass on main,
# including the self-scan of the working tree.

ROOT = Path(__file__).resolve().parents[1]
MAKEFILE = ROOT / "Makefile"


def lint_recipe_lines():
    """Return the tab-indented recipe lines of the Makefile lint target."""
    lines = MAKEFILE.read_text(encoding="utf-8").splitlines()
    start = lines.index("lint:")
    recipe = []
    for line in lines[start + 1:]:
        if line and not line.startswith("\t"):
            break
        recipe.append(line)
    return recipe


class LintWiringTest(unittest.TestCase):
    def test_tc2_lint_recipe_runs_history_scan(self):
        # TC2: the Makefile lint recipe contains scripts/scan_sensitive.py --history
        recipe = "\n".join(lint_recipe_lines())
        self.assertIn("scripts/scan_sensitive.py --history", recipe)

    def test_tc2_lint_recipe_has_no_skip_message(self):
        # TC2: the Makefile lint recipe does not contain "is not on this branch"
        recipe = "\n".join(lint_recipe_lines())
        self.assertNotIn("is not on this branch", recipe)

    def test_tc2_lint_scan_is_unconditional(self):
        # TC2 (supporting): the scan runs on every lint, not only when the file exists
        recipe = "\n".join(lint_recipe_lines())
        self.assertNotIn("-f scripts/scan_sensitive.py", recipe)


class HistoryScanCleanTest(unittest.TestCase):
    def test_tc3_history_scan_exits_zero_at_repo_root(self):
        # TC3: python3 -B scripts/scan_sensitive.py --history, cwd at the repository root, exits 0
        result = subprocess.run(
            [sys.executable, "-B", "scripts/scan_sensitive.py", "--history"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        # Output is not echoed: findings could contain sensitive text.
        self.assertEqual(result.returncode, 0, "scan_sensitive.py --history exited non-zero")


if __name__ == "__main__":
    unittest.main()
