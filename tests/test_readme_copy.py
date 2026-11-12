import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COST = "docs/cost.md"
TABLE_HEADING = "## Results with 5-minute cache writes"
LINK = re.compile(r"\]\(([^)]+)\)")
BANNED_WORDS = (
    "game-changing",
    "revolutionary",
    "world-class",
    "cutting-edge",
    "seamless",
    "supercharge",
    "effortless",
    "blazing",
    "unleash",
    "unlock",
    "leverage",
    "delve",
    "elevate",
    "empower",
    "next-level",
)
HOOK_SCRIPTS = ("session_context.py", "dispatch_guard.py", "stall_watch.py", "routing_audit.py")


def read(name):
    return (ROOT / name).read_text(encoding="utf-8")


def cells(row):
    return [cell.strip() for cell in row.strip().strip("|").split("|")]


def cost_table_rows():
    """Return the header, separator and body rows of the 5-minute table in docs/cost.md."""
    lines = read(COST).splitlines()
    start = lines.index(TABLE_HEADING)
    rows = []
    for line in lines[start + 1:]:
        if line.startswith("|"):
            rows.append(line)
        elif rows:
            break
    return rows


class ReadmeCopyTest(unittest.TestCase):
    def test_placeholders_filled(self):
        # TC2: no unfilled {PLACEHOLDER} remains in README.md.
        self.assertEqual(re.findall(r"\{[A-Z_]+\}", read("README.md")), [])

    def test_cost_rows(self):
        # TC4: every row of the 5-minute table in docs/cost.md appears verbatim in README.md.
        lines = read("README.md").splitlines()
        rows = cost_table_rows()
        self.assertGreaterEqual(len(rows), 3)
        for row in rows:
            self.assertIn(row, lines)

    def test_hero_numbers(self):
        # TC5: the hero paragraph quotes the exec row of the 5-minute table.
        readme = read("README.md")
        exec_row = next(row for row in cost_table_rows() if cells(row)[0] == "exec")
        actual, sonnet, opus = cells(exec_row)[2:5]
        for value in (actual, sonnet, opus):
            self.assertIn("about " + value, readme)

    def test_relative_links(self):
        # TC6: README links to docs/cost.md, CONTRIBUTING.md and LICENSE, and every relative
        # link target exists in the repository.
        readme = read("README.md")
        for target in ("docs/cost.md", "CONTRIBUTING.md", "LICENSE"):
            self.assertIn("](" + target + ")", readme)
        missing = []
        for target in LINK.findall(readme):
            if target.startswith(("http", "#")):
                continue
            if not (ROOT / target.split("#")[0]).exists():
                missing.append(target)
        self.assertEqual(missing, [])

    def test_no_dashes(self):
        # TC7: README.md contains no em dash (U+2014) and no en dash (U+2013).
        self.assertEqual(re.findall("[\u2013\u2014]", read("README.md")), [])

    def test_sections(self):
        # TC8: README.md has the required sections and mentions all four hook scripts.
        readme = read("README.md")
        lines = readme.splitlines()
        for heading in (
            "## What runs on your machine",
            "## Usage limits on Pro and Max",
            "## Requirements",
            "## Uninstall",
        ):
            self.assertIn(heading, lines)
        for script in HOOK_SCRIPTS:
            self.assertIn(script, readme)

    def test_no_banned_words(self):
        # TC9: README.md uses none of the banned words, case-insensitively.
        text = read("README.md").lower()
        self.assertEqual([word for word in BANNED_WORDS if word in text], [])


if __name__ == "__main__":
    unittest.main()
