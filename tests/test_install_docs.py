import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MARKET = "claude-" + "model-routing"


def read(name):
    return (ROOT / name).read_text(encoding="utf-8")


class InstallDocsTests(unittest.TestCase):
    # TC1: README.md names mr-clean in its commands table.
    def test_readme_sections_and_commands(self):
        # TC1: the install, update and uninstall strings use the owner shorthand, with no <owner> placeholder.
        readme = read("README.md")
        lines = readme.splitlines()
        self.assertIn("## Install the plugin", lines)
        self.assertIn("## Update the plugin", lines)
        for text in (
            "claude plugin marketplace add Alirezajalilii/" + MARKET,
            "claude plugin install mr@" + MARKET,
            "claude plugin install mr@" + MARKET + " --scope local",
            "claude plugin install mr --marketplace Alirezajalilii/" + MARKET,
            "/plugin install mr --marketplace Alirezajalilii/" + MARKET,
            "claude plugin marketplace update",
            "claude plugin update mr@" + MARKET,
            "claude plugin uninstall mr@" + MARKET + " --keep-data",
            "cp -Rpn",
            "make check-install",
            "CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH",
            "CLAUDE_CODE_PLUGIN_PREFER_HTTPS=1",
            "mr-doctor",
            "mr-cost",
            "mr-clean",  # TC1
            "/mr:init-project",
        ):
            self.assertIn(text, readme)
        self.assertNotIn("<owner>", readme)
        self.assertNotIn("git@github.com:", readme)
        for line in lines:
            self.assertIsNone(re.search("(?<!@)(?<!Alirezajalilii/)" + re.escape(MARKET), line), line)

    def test_readme_and_agents_teach_short_names(self):
        readme = read("README.md")
        self.assertIn("mr:exec-haiku-med", readme)
        self.assertIn("`plan`, `exec`, `verify`", readme)
        agents = read("AGENTS.md")
        self.assertIn("effort_labels", agents)
        self.assertIn("--keep-data", agents)

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
