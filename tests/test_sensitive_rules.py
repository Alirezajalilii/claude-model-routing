from __future__ import annotations

import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import unittest

from sensitive_rules import (
    DenyFileError,
    Finding,
    compile_deny,
    decode_content,
    scan_unit,
    unescape,
)

# Sensitive-looking literals are built by concatenation so that this file
# does not match any built-in rule when the repository is scanned.
SECRET_CASE = "OPENROUTER_" + "API_KEY=" + '"' + "a1b2c3d4e5f6g7h8" + '"'
HOME_TEXT = "/" + "home/" + "alice/x"


def findings_for(line: str, rule: str) -> list[Finding]:
    return [finding for finding in scan_unit(line, "x", ()) if finding.rule == rule]


class SecretAssignmentPositiveTests(unittest.TestCase):
    CASES = (
        SECRET_CASE,
        "GITHUB_" + "TOKEN='" + "a1b2c3d4e5f6g7h8" + "'",
        '{"api' + '_key": "' + "a1b2c3d4e5f6g7h8" + '"}',
        "TOK" + "EN=" + "A1b2C3d4E5f6G7h8",
        "pass" + "word: " + "hunter2hunter2hunter2",
        "db_pass" + "word = " + '"' + "x9y8z7w6v5u4t3" + '"',
    )

    def test_each_form_gives_exactly_one_finding(self) -> None:
        for line in self.CASES:
            with self.subTest(line=line):
                self.assertEqual(len(findings_for(line, "secret-assignment")), 1)

    def test_secret_excerpt_is_masked_to_six_characters(self) -> None:
        excerpts = [finding.excerpt for finding in findings_for(SECRET_CASE, "secret-assignment")]
        self.assertEqual(excerpts, ["OPENRO..."])


class SecretAssignmentNegativeTests(unittest.TestCase):
    CASES = (
        "tok" + "en = match.group(1)",
        "api_" + "key = config.api_key",
        "API_" + "KEY=your-key-here",
        '"pass' + 'word": "${DB_PASSWORD}"',
        "pass" + 'word: "<your password>"',
        "Tok" + "ens: about 36K prompt tokens",
        "secret_" + "value = settings.client_secret_value",
        "TOK" + "EN=" + "abcdefghijklmnopqrst",
    )

    def test_no_line_gives_a_secret_assignment_finding(self) -> None:
        for line in self.CASES:
            with self.subTest(line=line):
                self.assertEqual(findings_for(line, "secret-assignment"), [])


class TokenTests(unittest.TestCase):
    POSITIVE = (
        "sk" + "-proj-" + "A1b2" * 6,
        "sk" + "-or-v1-" + "a1b2" * 8,
        "my_" + "sk-" + "a1b2" * 6,
        "ey" + "J" + "hbGciOiJIUzI1NiJ9" + ".ey" + "J" + "zdWIiOiIxMjM0NTY3ODkwIn0" + "." + "SflKxwRJSMeKKF2QT4fw",
        "glpat" + "-" + "a1B2" * 5,
        "sk" + "_live_" + "a1B2" * 6,
        "hf" + "_" + "a1B2" * 8,
    )
    NEGATIVE = (
        "risk-" + "assessment-framework-documentation",
        "sk-" + "short",
        "ey" + "J" + "only-one-part",
    )

    def test_current_formats_give_a_masked_token_finding(self) -> None:
        for line in self.POSITIVE:
            with self.subTest(line=line):
                findings = findings_for(line, "token")
                self.assertTrue(findings)
                self.assertEqual(len(findings[0].excerpt), 9)
                self.assertTrue(findings[0].excerpt.endswith("..."))

    def test_lookalikes_give_no_token_finding(self) -> None:
        for line in self.NEGATIVE:
            with self.subTest(line=line):
                self.assertEqual(findings_for(line, "token"), [])


class ArabicScriptTests(unittest.TestCase):
    def test_added_ranges_are_flagged(self) -> None:
        for code_point in (0x0750, 0x08A0, 0xFEFB):
            with self.subTest(code_point=hex(code_point)):
                self.assertTrue(findings_for("x" + chr(code_point), "arabic-script"))

    def test_byte_order_mark_is_not_flagged(self) -> None:
        self.assertEqual(findings_for(chr(0xFEFF) + "hello", "arabic-script"), [])
        self.assertEqual(findings_for("hel" + chr(0xFEFF) + "lo", "arabic-script"), [])


class UnescapedViewTests(unittest.TestCase):
    def test_unicode_escape_of_arabic_is_flagged(self) -> None:
        self.assertTrue(findings_for("\\" + "u0627" + "\\" + "u0644", "arabic-script"))

    def test_hex_character_reference_is_flagged(self) -> None:
        self.assertTrue(findings_for("&#x" + "627;", "arabic-script"))

    def test_decimal_character_reference_is_flagged(self) -> None:
        self.assertTrue(findings_for("&#" + "1575;", "arabic-script"))

    def test_escaped_windows_path_is_flagged(self) -> None:
        self.assertTrue(findings_for("C:" + "\\\\" + "Users" + "\\\\" + "bob", "home-path"))

    def test_escaped_slash_path_is_flagged(self) -> None:
        self.assertTrue(findings_for("\\/" + "home" + "\\/" + "dave", "home-path"))

    def test_raw_view_wins_over_unescaped_duplicate(self) -> None:
        line = "/" + "home/" + "alice " + "\\/" + "home" + "\\/" + "alice"
        self.assertEqual(len(findings_for(line, "home-path")), 1)

    def test_invalid_surrogate_escape_is_unchanged(self) -> None:
        text = "\\" + "uD800"
        self.assertEqual(unescape(text), text)


class DecodeContentTests(unittest.TestCase):
    CASES = (
        (b"\xef\xbb\xbf" + b"hello", ("hello", False)),
        ("hi".encode("utf-16"), ("hi", False)),
        ("hello world".encode("utf-16-le"), ("hello world", False)),
        ("hello world".encode("utf-16-be"), ("hello world", False)),
        ("hi".encode("utf-32"), ("hi", False)),
        (b"\x00\x01ab\x00" + b"printable-run-1" + b"\x00xy\x00", ("printable-run-1", True)),
        (b"plain text", ("plain text", False)),
    )

    def test_decoding_table(self) -> None:
        for data, expected in self.CASES:
            with self.subTest(data=data):
                self.assertEqual(decode_content(data), expected)


class CompileDenyTests(unittest.TestCase):
    def test_comments_and_blank_lines_are_skipped(self) -> None:
        patterns = compile_deny(["# c", "", "acme-internal"])
        self.assertEqual(len(patterns), 1)
        self.assertIsNotNone(patterns[0].search("ACME-Internal"))

    def test_invalid_regex_reports_its_line_number(self) -> None:
        with self.assertRaises(DenyFileError) as raised:
            compile_deny(["ok", "("])
        self.assertEqual(raised.exception.line_no, 2)


if __name__ == "__main__":
    unittest.main()
