import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(name):
    return (ROOT / name).read_text(encoding="utf-8")


class InstallDocsTests(unittest.TestCase):
    def test_readme_sections_and_commands(self):
        readme = read("README.md")
        lines = readme.splitlines()
        self.assertIn("## Install the plugin", lines)
        self.assertIn("## Update the plugin", lines)
        for text in (
            "claude plugin marketplace add git@github.com:<owner>/model-routing.git",
            "claude plugin install model-routing@claude-model-routing --scope user",
            "claude plugin marketplace update claude-model-routing",
            "claude plugin update model-routing@claude-model-routing",
            "make check-install",
        ):
            self.assertIn(text, readme)

    def test_no_directory_source_or_home_paths(self):
        for name in ("README.md", "CONTRIBUTING.md", "AGENTS.md", "CHANGELOG.md"):
            text = read(name)
            self.assertIsNone(re.search(r"marketplace add\s+[/.~]", text), name)
            self.assertNotIn("/Users/", text, name)

    def test_makefile_and_guides(self):
        self.assertTrue(
            any(l.startswith("check-install:") for l in read("Makefile").splitlines())
        )
        contributing = read("CONTRIBUTING.md")
        self.assertIn("make check-install", contributing)
        self.assertIn("git-ignored", contributing)
        self.assertIn("make check-install", read("AGENTS.md"))


if __name__ == "__main__":
    unittest.main()
