from __future__ import annotations

import hashlib
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import sensitive_rules  # noqa: E402
from sensitive_rules import (  # noqa: E402
    ALLOWED_FINDINGS,
    SECRET_RE,
    is_allowed_finding,
    scan_content,
    scan_text,
)

# Every address, home path and key assignment below is built by concatenation at run
# time, so this file does not match any built-in rule when the repository is scanned.


def _findings_of(rule, line):
    return [finding for finding in scan_text(line, "line", ()) if finding.rule == rule]


def _home(name):
    return "/" + "Users/" + name


class SshAddressTest(unittest.TestCase):
    def test_tc4_ssh_clone_hosts_give_no_email_finding(self):
        # TC4 (R-A): the SSH user at the three hosting services is not a finding
        for host in ("github.com", "gitlab.com", "bitbucket.org"):
            with self.subTest(host=host):
                line = "clone = " + "git" + "@" + host + ":owner/repo.git"
                self.assertEqual(_findings_of("email", line), [])

    def test_tc4_other_addresses_stay_email_findings(self):
        # TC4 (R-A): other addresses, including at the same domains, are still findings
        personal = "contact = " + "alice" + "@" + "github.com"
        other_ssh = "remote = " + "git" + "@" + "mail-host.io"
        self.assertEqual(len(_findings_of("email", personal)), 1)
        self.assertEqual(len(_findings_of("email", other_ssh)), 1)


class EnvVarNameValueTest(unittest.TestCase):
    def test_tc5_env_var_name_as_quoted_value_is_not_a_finding(self):
        # TC5 (R-B): the shapes of tests/test_doctor.py line 30
        upper_name = "API" + "_KEY"
        upper_value = "ANTHROPIC" + "_API_KEY"
        assignment = upper_name + " = " + '"' + upper_value + '"'
        json_style = '"' + "api" + "_key" + '": "' + upper_value + '"'
        for line in (assignment, json_style):
            with self.subTest(line=line):
                self.assertIsNotNone(SECRET_RE.search(line))
                self.assertEqual(_findings_of("secret-assignment", line), [])

    def test_tc5_values_with_a_digit_or_mixed_case_are_findings(self):
        # TC5 (R-B): a digit or mixed case keeps the value a finding
        digit_value = "SUPERSECRET" + "_VALUE_9"
        mixed_value = "AbcDef" + "GhiJkl12"
        digit_line = "api" + "_key = " + '"' + digit_value + '"'
        mixed_line = "api" + "_key = " + '"' + mixed_value + '"'
        for line in (digit_line, mixed_line):
            with self.subTest(line=line):
                self.assertEqual(len(_findings_of("secret-assignment", line)), 1)


class FingerprintTest(unittest.TestCase):
    def setUp(self):
        self.text = _home("someone")
        self.digest = hashlib.sha256(self.text.encode("utf-8")).hexdigest()
        self.entries = (("tests/fixture.py", "home-path", self.digest),)

    def test_tc6_listed_path_rule_and_text_are_allowed(self):
        # TC6 (fingerprint): only the exact path, rule and text pass
        with patch.object(sensitive_rules, "ALLOWED_FINDINGS", self.entries):
            self.assertTrue(is_allowed_finding("tests/fixture.py", "home-path", self.text))
            self.assertFalse(is_allowed_finding("scripts/fixture.py", "home-path", self.text))
            self.assertFalse(
                is_allowed_finding("tests/fixture.py", "home-path", _home("another"))
            )
            self.assertFalse(is_allowed_finding("tests/fixture.py", "email", self.text))

    def test_tc7_allowlisted_path_drops_only_the_listed_home_path(self):
        # TC7 (fingerprint wiring): file-level entry point scan_content gets a file's
        # bytes and its path; the listed text is dropped, a second home path is kept.
        listed = _home("someone")
        second = _home("another")
        data = ("listed " + listed + "\nother " + second + "\n").encode("utf-8")
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "fixture.py"
            target.write_bytes(data)
            with patch.object(sensitive_rules, "ALLOWED_FINDINGS", self.entries):
                found = scan_content(
                    target.read_bytes(), "tests/fixture.py", (), path="tests/fixture.py"
                )
        homes = [finding for finding in found if finding.rule == "home-path"]
        self.assertEqual(len(homes), 1)
        self.assertEqual(homes[0].location, "tests/fixture.py:2")
        self.assertIn("another", homes[0].excerpt)


class AllowlistShapeTest(unittest.TestCase):
    def test_tc8_shipped_allowlist_has_exactly_the_two_fixture_entries(self):
        # TC8 (allowlist shape): F-1 and F-2 and nothing else
        self.assertEqual(len(ALLOWED_FINDINGS), 2)
        pairs = sorted((path, rule) for path, rule, _ in ALLOWED_FINDINGS)
        self.assertEqual(
            pairs,
            [
                ("tests/test_doctor.py", "secret-assignment"),
                ("tests/test_routing_audit.py", "home-path"),
            ],
        )

    def test_tc8_hashes_are_lowercase_sha256_hex(self):
        # TC8 (allowlist shape): 64-character lower-case hex digests
        for _, _, digest in ALLOWED_FINDINGS:
            self.assertRegex(digest, r"^[0-9a-f]{64}$")

    def test_tc8_paths_are_exact_not_globs(self):
        # TC8 (allowlist shape): no wildcard characters in any path
        for path, _, _ in ALLOWED_FINDINGS:
            for wildcard in "*?[":
                self.assertNotIn(wildcard, path)


if __name__ == "__main__":
    unittest.main()
