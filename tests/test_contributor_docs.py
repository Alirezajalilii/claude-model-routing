"""Checks for the self-contained contributor docs: AGENTS.md, CONTRIBUTING.md, SECURITY.md and docs/architecture.md (PL7)."""
from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AGENTS = ROOT / "AGENTS.md"
CONTRIBUTING = ROOT / "CONTRIBUTING.md"
SECURITY = ROOT / "SECURITY.md"
ARCHITECTURE = ROOT / "docs" / "architecture.md"

LAUNCHERS = (
    "mr-usage", "mr-audit", "mr-skills", "mr-init",
    "mr-plan", "mr-gate", "mr-cost", "mr-doctor",
)
# The home-directory workspace path is built by concatenation so that this file does not contain it.
BANNED_IN_AGENTS = (
    "workspace standard", "~/" + "Work", "TODO(agent)", "agent/T09", "Deviations from",
)
KEPT_IN_AGENTS = ("effort_labels", "--keep-data", "make check-install")
CONTRIBUTING_PHRASES = (
    "make test", "make lint", "scan_sensitive.py --history", "git-ignored", "make check-install",
)
CONTRIBUTING_BANNED = ("claude plugin validate . --strict",)
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
ALLOWED_DOMAIN = "@example.com"


def read(path):
    return path.read_text(encoding="utf-8")


class ContributorDocsTest(unittest.TestCase):
    def test_agents_self_contained(self):
        # TC1: AGENTS.md describes this repository alone: no workspace or branch leftovers.
        text = read(AGENTS)
        for phrase in BANNED_IN_AGENTS:
            self.assertNotIn(phrase, text, phrase)

    def test_agents_launchers(self):
        # TC2: AGENTS.md names every launcher in bin/, and bin/ holds only those launchers.
        text = read(AGENTS)
        for name in LAUNCHERS:
            self.assertIn(name, text, name)
        for path in sorted((ROOT / "bin").iterdir()):
            if path.is_file():
                self.assertIn(path.name, LAUNCHERS, path.name)

    def test_agents_kept_strings(self):
        # TC3 (guard): the strings the existing tests need stay in AGENTS.md.
        text = read(AGENTS)
        for phrase in KEPT_IN_AGENTS:
            self.assertIn(phrase, text, phrase)

    def test_contributing(self):
        # TC4: CONTRIBUTING.md names the real checks and no longer the old validate command.
        text = read(CONTRIBUTING)
        for phrase in CONTRIBUTING_PHRASES:
            self.assertIn(phrase, text, phrase)
        for phrase in CONTRIBUTING_BANNED:
            self.assertNotIn(phrase, text, phrase)

    def test_security(self):
        # TC5: SECURITY.md routes reports through GitHub; any contact address ends with @example.com.
        text = read(SECURITY)
        self.assertIn("Report a vulnerability", text)
        for address in EMAIL_RE.findall(text):
            self.assertTrue(address.endswith(ALLOWED_DOMAIN), address)

    def test_architecture(self):
        # TC6: docs/architecture.md lists the two new launchers.
        text = read(ARCHITECTURE)
        for name in ("mr-cost", "mr-doctor"):
            self.assertIn(name, text, name)


if __name__ == "__main__":
    unittest.main()
