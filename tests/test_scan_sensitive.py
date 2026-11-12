from __future__ import annotations

import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import io
import os
import re
import subprocess
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import patch

import scan_sensitive

# Sensitive-looking literals are built by concatenation so that this file
# does not match any built-in rule when the repository is scanned.
HOME_LINE = "/" + "home/" + "alice/x"
HOME_LONG = "/" + "home/" + "a" * 80
WINDOWS_HOME = "C:" + "\\" + "Users" + "\\" + "bob"
EMAIL_CORP = "alice@" + "corp" + ".io"
EMAIL_AUTHOR = "x@" + "corp" + ".io"
EMAIL_EXAMPLE = "alice@" + "example.com"
EMAIL_NOREPLY_GH = "12345+alice@" + "users.noreply." + "github.com"
EMAIL_ANTHROPIC = "noreply@" + "anthropic.com"
IP_PRIVATE = "10.1.2" + ".3"
SK_ANT = "sk" + "-ant-" + "a" * 24
GHP = "ghp" + "_" + "A" * 36
PEM = "-----BEGIN " + "RSA PRIVATE KEY-----"
UUID_BAD = "123e4567-e89b-42d3" + "-a456-426614174000"
SECRET_LINE = "api" + "_key = \"" + "x" * 16 + "\""
ARABIC_LINE = "x" + chr(0x0627) + chr(0x0628) + "\n"
TRAILER = "Co-Authored-By: Claude <" + "noreply@" + "anthropic.com>"

GIT_ENV = {
    "GIT_AUTHOR_NAME": "test",
    "GIT_AUTHOR_EMAIL": "test@example.com",
    "GIT_COMMITTER_NAME": "test",
    "GIT_COMMITTER_EMAIL": "test@example.com",
}


def git(repo: Path, *args: str, env_extra: dict[str, str] | None = None) -> str:
    env = {**os.environ, **GIT_ENV, **(env_extra or {})}
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )
    return result.stdout


def commit(
    repo: Path, message: str, env_extra: dict[str, str] | None = None
) -> None:
    git(
        repo,
        "-c",
        "commit.gpgsign=false",
        "commit",
        "-q",
        "--allow-empty",
        "-m",
        message,
        env_extra=env_extra,
    )


def write(repo: Path, name: str, data: str | bytes) -> None:
    path = repo / name
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(data, str):
        path.write_text(data, encoding="utf-8")
    else:
        path.write_bytes(data)


def track(repo: Path, name: str) -> None:
    git(repo, "add", name)


def run_cli(argv: list[str]) -> tuple[int, str, str]:
    out = io.StringIO()
    err = io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = scan_sensitive.main(argv)
    return code, out.getvalue(), err.getvalue()


def findings_of(out: str) -> list[str]:
    return [
        line
        for line in out.splitlines()
        if not re.fullmatch(r"\d+ findings", line) and line != "no findings"
    ]


class RepoTestCase(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.repo = Path(tmp.name)
        git(self.repo, "init", "-q")

    def scan(self, *extra: str) -> tuple[int, str, str]:
        return run_cli(["--root", str(self.repo), *extra])

    def sha8(self) -> str:
        return git(self.repo, "rev-parse", "HEAD").strip()[:8]


class CleanRepositoryTests(RepoTestCase):
    def test_clean_repository_exits_zero(self) -> None:
        # Arrange
        write(self.repo, "README.md", "# Project\n\nPlain text.\n")
        track(self.repo, "README.md")
        commit(self.repo, "docs: readme")
        # Act
        code, out, _ = self.scan()
        # Assert
        self.assertEqual(code, 0)
        self.assertEqual(out.strip(), "no findings")


class TrackedAndUntrackedTests(RepoTestCase):
    def test_tracked_file_with_home_path_is_flagged(self) -> None:
        write(self.repo, "file.txt", HOME_LINE + "\n")
        track(self.repo, "file.txt")
        code, out, _ = self.scan()
        self.assertEqual(code, 1)
        self.assertTrue(
            any(line.startswith("file.txt:1: home-path: ") for line in out.splitlines()),
            out,
        )
        self.assertTrue(out.strip().endswith("1 findings"), out)

    def test_untracked_email_flagged_and_allowed_domains_not(self) -> None:
        write(
            self.repo,
            "mail.txt",
            "\n".join([EMAIL_CORP, EMAIL_EXAMPLE, EMAIL_NOREPLY_GH, EMAIL_ANTHROPIC])
            + "\n",
        )
        code, out, _ = self.scan()
        findings = findings_of(out)
        self.assertEqual(code, 1)
        self.assertEqual(findings, [f"mail.txt:1: email: {EMAIL_CORP}"])

    def test_same_home_path_twice_on_one_line_is_printed_once(self) -> None:
        write(self.repo, "file.txt", HOME_LINE + " " + HOME_LINE + "\n")
        code, out, _ = self.scan()
        matching = [line for line in out.splitlines() if line.startswith("file.txt:1: home-path")]
        self.assertEqual(code, 1)
        self.assertEqual(len(matching), 1, out)

    def test_excerpt_is_truncated_to_sixty_characters(self) -> None:
        write(self.repo, "file.txt", HOME_LONG + "\n")
        code, out, _ = self.scan()
        findings = findings_of(out)
        self.assertEqual(code, 1)
        self.assertEqual(len(findings), 1, out)
        excerpt = findings[0].split(": ", 2)[2]
        self.assertLessEqual(len(excerpt), 60)
        self.assertTrue(excerpt.startswith("/" + "home/" + "aaa"), excerpt)


class IgnoredFileTests(RepoTestCase):
    def test_ignored_file_with_home_path_is_not_flagged(self) -> None:
        write(self.repo, ".gitignore", "ignored.txt\n")
        track(self.repo, ".gitignore")
        commit(self.repo, "chore: ignore")
        write(self.repo, "ignored.txt", HOME_LINE + "\n")
        code, out, _ = self.scan()
        self.assertEqual(code, 0)
        self.assertEqual(out.strip(), "no findings")


class PatternRuleTests(RepoTestCase):
    def test_ipv4_flags_private_address_and_skips_allowed_and_version(self) -> None:
        write(
            self.repo,
            "net.txt",
            "\n".join(
                [
                    IP_PRIVATE,
                    "127.0.0.1",
                    "0.0.0.0",
                    "192.0.2.10",
                    "203.0.113.5",
                    "198.51.100.7",
                    "2.1.306",
                ]
            )
            + "\n",
        )
        code, out, _ = self.scan()
        self.assertEqual(code, 1)
        self.assertEqual(findings_of(out), [f"net.txt:1: ipv4: {IP_PRIVATE}"])

    def test_tokens_flagged_with_six_character_excerpts(self) -> None:
        write(self.repo, "keys.txt", "\n".join([SK_ANT, GHP, PEM]) + "\n")
        code, out, _ = self.scan()
        self.assertEqual(code, 1)
        self.assertIn("keys.txt:1: token: sk-ant...", out)
        self.assertIn("keys.txt:2: token: ghp_AA...", out)
        self.assertIn("keys.txt:3: private-key: -----B...", out)

    def test_secret_assignment_flagged_with_six_character_excerpt(self) -> None:
        write(self.repo, "config.txt", SECRET_LINE + "\n")
        code, out, _ = self.scan()
        self.assertEqual(code, 1)
        self.assertIn("config.txt:1: secret-assignment: api_ke...", out)

    def test_arabic_script_is_flagged(self) -> None:
        write(self.repo, "text.txt", ARABIC_LINE)
        code, out, _ = self.scan()
        self.assertEqual(code, 1)
        self.assertTrue(
            any(line.startswith("text.txt:1: arabic-script: ") for line in out.splitlines()),
            out,
        )

    def test_uuid_flagged_and_zero_prefixed_uuid_allowed(self) -> None:
        write(
            self.repo,
            "ids.txt",
            UUID_BAD + "\n00000000-0000-4000-8000-000000000001\n",
        )
        code, out, _ = self.scan()
        self.assertEqual(code, 1)
        self.assertEqual(len(findings_of(out)), 1, out)
        self.assertTrue(out.splitlines()[0].startswith("ids.txt:1: uuid: "), out)

    def test_windows_user_path_is_flagged_as_home_path(self) -> None:
        write(self.repo, "win.txt", WINDOWS_HOME + "\n")
        code, out, _ = self.scan()
        self.assertEqual(code, 1)
        self.assertTrue(
            any(line.startswith("win.txt:1: home-path: ") for line in out.splitlines()),
            out,
        )


class HistoryTests(RepoTestCase):
    def test_deleted_secret_is_found_only_with_history(self) -> None:
        write(self.repo, "old.txt", HOME_LINE + "\n")
        track(self.repo, "old.txt")
        commit(self.repo, "feat: add old file")
        git(self.repo, "rm", "-q", "old.txt")
        commit(self.repo, "chore: remove old file")
        code, out, _ = self.scan()
        self.assertEqual(code, 0)
        self.assertEqual(out.strip(), "no findings")
        code, out, _ = self.scan("--history")
        self.assertEqual(code, 1)
        history = [line for line in findings_of(out) if line.startswith("history ")]
        self.assertEqual(len(history), 1, out)
        self.assertIn("old.txt:1", history[0])

    def test_commit_message_home_path_is_flagged(self) -> None:
        commit(self.repo, "fix: " + HOME_LINE)
        sha = self.sha8()
        code, out, _ = self.scan("--history")
        self.assertEqual(code, 1)
        self.assertIn(f"commit {sha} message:1: home-path", out)

    def test_author_email_is_flagged(self) -> None:
        commit(
            self.repo,
            "chore: empty",
            env_extra={"GIT_AUTHOR_NAME": "x", "GIT_AUTHOR_EMAIL": EMAIL_AUTHOR},
        )
        sha = self.sha8()
        code, out, _ = self.scan("--history")
        self.assertEqual(code, 1)
        self.assertIn(f"commit {sha} author: email", out)

    def test_committer_email_is_flagged(self) -> None:
        commit(
            self.repo,
            "chore: empty",
            env_extra={"GIT_COMMITTER_NAME": "x", "GIT_COMMITTER_EMAIL": EMAIL_AUTHOR},
        )
        sha = self.sha8()
        code, out, _ = self.scan("--history")
        self.assertEqual(code, 1)
        self.assertIn(f"commit {sha} committer: email", out)

    def test_claude_coauthor_trailer_is_not_flagged(self) -> None:
        commit(self.repo, "chore: note\n\n" + TRAILER)
        code, out, _ = self.scan("--history")
        self.assertEqual(code, 0)
        self.assertEqual(out.strip(), "no findings")


class DenyFileTests(RepoTestCase):
    def setUp(self) -> None:
        super().setUp()
        deny_tmp = tempfile.TemporaryDirectory()
        self.addCleanup(deny_tmp.cleanup)
        self.deny_dir = Path(deny_tmp.name)

    def test_deny_file_matches_case_insensitively_and_skips_comments(self) -> None:
        write(self.deny_dir, "deny.txt", "# comment\n\nacme-internal\n")
        write(self.repo, "notes.txt", "# comment\nProject ACME-Internal notes\n")
        deny = str(self.deny_dir / "deny.txt")
        code, out, _ = self.scan("--deny-file", deny)
        self.assertEqual(code, 1)
        self.assertEqual(findings_of(out), ["notes.txt:2: deny: ACME-Internal"])

    def test_invalid_deny_regex_exits_two_with_line_number(self) -> None:
        write(self.deny_dir, "deny.txt", "(\n")
        write(self.repo, "notes.txt", "anything\n")
        code, _, err = self.scan("--deny-file", str(self.deny_dir / "deny.txt"))
        self.assertEqual(code, 2)
        self.assertIn("line 1", err)

    def test_missing_deny_file_exits_two(self) -> None:
        code, _, err = self.scan("--deny-file", str(self.deny_dir / "missing.txt"))
        self.assertEqual(code, 2)
        self.assertTrue(err.strip(), "a reason must be written to stderr")


class BinaryFileTests(RepoTestCase):
    def test_binary_file_with_home_path_is_flagged_at_bytes_location(self) -> None:
        data = b"\x00\x01\x02" + ("/" + "home/" + "alice/xy").encode("utf-8") + b"\x00\xff"
        write(self.repo, "file.bin", data)
        track(self.repo, "file.bin")
        code, out, _ = self.scan()
        self.assertEqual(code, 1)
        self.assertIn("file.bin:bytes: home-path: ", out)

    def test_binary_runs_shorter_than_eight_bytes_are_not_flagged(self) -> None:
        write(self.repo, "short.bin", b"\x00\x01" + ("/" + "home/" + "x").encode("utf-8") + b"\x00")
        code, out, _ = self.scan()
        self.assertEqual(code, 0)
        self.assertEqual(out.strip(), "no findings")


class DenyRepoTestCase(RepoTestCase):
    def setUp(self) -> None:
        super().setUp()
        deny_tmp = tempfile.TemporaryDirectory()
        self.addCleanup(deny_tmp.cleanup)
        write(Path(deny_tmp.name), "deny.txt", "acme-internal\n")
        self.deny = str(Path(deny_tmp.name) / "deny.txt")


class PathNameTests(DenyRepoTestCase):
    def test_untracked_path_name_is_matched_by_deny_rule(self) -> None:
        write(self.repo, "acme-" + "internal-notes.md", "neutral\n")
        code, out, _ = self.scan("--deny-file", self.deny)
        self.assertEqual(code, 1)
        self.assertIn("name acme-internal-notes.md: deny: ", out)

    def test_directory_component_is_matched_by_deny_rule(self) -> None:
        write(self.repo, "acme-" + "internal/readme.md", "neutral\n")
        code, out, _ = self.scan("--deny-file", self.deny)
        self.assertEqual(code, 1)
        self.assertIn("name acme-internal/readme.md: deny: ", out)

    def test_non_ascii_path_name_is_flagged_without_deny_file(self) -> None:
        name = "x" + chr(0x0627) + ".txt"
        write(self.repo, name, "neutral\n")
        track(self.repo, name)
        code, out, _ = self.scan()
        self.assertEqual(code, 1)
        self.assertIn(f"name {name}: arabic-script: ", out)


class PathNameHistoryTests(DenyRepoTestCase):
    def test_renamed_path_name_is_found_only_with_history(self) -> None:
        write(self.repo, "acme-" + "internal-notes.md", "neutral\n")
        track(self.repo, "acme-" + "internal-notes.md")
        commit(self.repo, "feat: add notes")
        git(self.repo, "mv", "acme-" + "internal-notes.md", "notes.md")
        commit(self.repo, "chore: rename notes")
        code, out, _ = self.scan("--deny-file", self.deny)
        self.assertEqual(code, 0)
        self.assertEqual(out.strip(), "no findings")
        code, out, _ = self.scan("--deny-file", self.deny, "--history")
        self.assertEqual(code, 1)
        self.assertIn("history name acme-internal-notes.md: deny: ", out)


class CommitParsingTests(RepoTestCase):
    def commit_message(self, data: bytes) -> str:
        with tempfile.TemporaryDirectory() as tmp:
            message = Path(tmp) / "message.txt"
            message.write_bytes(data)
            git(
                self.repo,
                "-c",
                "commit.gpgsign=false",
                "commit",
                "-q",
                "--allow-empty",
                "--cleanup=verbatim",
                "-F",
                str(message),
            )
        return self.sha8()

    def test_record_separator_inside_message_does_not_hide_text(self) -> None:
        sha = self.commit_message(("subject" + "\x1e" + "/" + "home/" + "bob/x").encode("utf-8"))
        code, out, _ = self.scan("--history")
        self.assertEqual(code, 1)
        self.assertIn(f"commit {sha} message:1: home-path", out)

    def test_unit_separator_inside_message_does_not_hide_text(self) -> None:
        sha = self.commit_message(("subject" + "\x1f" + "/" + "home/" + "bob/x").encode("utf-8"))
        code, out, _ = self.scan("--history")
        self.assertEqual(code, 1)
        self.assertIn(f"commit {sha} message:1: home-path", out)

    def test_multi_line_message_reports_its_own_line_number(self) -> None:
        data = ("subject\n\nbody line\n" + "/" + "home/" + "eve/x" + "\n").encode("utf-8")
        sha = self.commit_message(data)
        code, out, _ = self.scan("--history")
        self.assertEqual(code, 1)
        self.assertIn(f"commit {sha} message:4: home-path", out)


class TagTests(DenyRepoTestCase):
    def test_annotated_tag_message_and_tagger_are_scanned_with_history(self) -> None:
        commit(self.repo, "chore: base")
        env = {"GIT_COMMITTER_EMAIL": "x@" + "corp" + ".io"}
        git(self.repo, "tag", "-a", "v0", "-m", "release " + "/" + "home/" + "carol/x", env_extra=env)
        code, out, _ = self.scan("--history")
        self.assertEqual(code, 1)
        self.assertIn("tag v0 message:1: home-path", out)
        self.assertIn("tag v0 tagger: email", out)

    def test_annotated_tag_findings_absent_without_history(self) -> None:
        commit(self.repo, "chore: base")
        env = {"GIT_COMMITTER_EMAIL": "x@" + "corp" + ".io"}
        git(self.repo, "tag", "-a", "v0", "-m", "release " + "/" + "home/" + "carol/x", env_extra=env)
        code, out, _ = self.scan()
        self.assertEqual(code, 0)
        self.assertNotIn("tag v0", out)

    def test_lightweight_tag_name_is_matched_by_deny_rule_with_history(self) -> None:
        commit(self.repo, "chore: base")
        git(self.repo, "tag", "acme-" + "internal-v1")
        code, out, _ = self.scan("--deny-file", self.deny, "--history")
        self.assertEqual(code, 1)
        self.assertIn("ref refs/tags/acme-internal-v1: deny: ", out)
        code, out, _ = self.scan("--deny-file", self.deny)
        self.assertNotIn("ref refs/tags", out)


class ErrorTests(RepoTestCase):
    def test_unreadable_file_exits_two_with_path_and_reason(self) -> None:
        write(self.repo, "file.txt", "neutral\n")
        track(self.repo, "file.txt")
        with patch("scan_sensitive._read_file", side_effect=PermissionError(13, "Permission denied")):
            code, out, err = self.scan()
        self.assertEqual(code, 2)
        self.assertEqual(out, "")
        self.assertIn("file.txt", err)
        self.assertIn("Permission denied", err)

    def test_tracked_file_missing_from_worktree_is_noted_not_an_error(self) -> None:
        write(self.repo, "gone.txt", "neutral\n")
        track(self.repo, "gone.txt")
        commit(self.repo, "chore: add gone")
        (self.repo / "gone.txt").unlink()
        code, out, err = self.scan()
        self.assertEqual(code, 0)
        self.assertEqual(out.strip(), "no findings")
        self.assertIn("is missing from the worktree", err)

    def test_internal_error_exits_two_with_type_and_message(self) -> None:
        with patch("scan_sensitive._worktree_paths", side_effect=RuntimeError("boom")):
            code, out, err = self.scan()
        self.assertEqual(code, 2)
        self.assertEqual(out, "")
        self.assertIn("internal error: RuntimeError: boom", err)

    def test_missing_git_exits_two(self) -> None:
        with patch("scan_sensitive.subprocess.run", side_effect=FileNotFoundError("git")):
            code, _, _ = self.scan()
        self.assertEqual(code, 2)

    def test_error_after_findings_still_exits_two_with_empty_stdout(self) -> None:
        write(self.repo, "a.txt", "neutral\n")
        write(self.repo, "b.txt", "neutral\n")
        track(self.repo, "a.txt")
        track(self.repo, "b.txt")

        def fake_read(path: Path) -> bytes:
            if path.name == "b.txt":
                raise PermissionError(13, "Permission denied")
            return ("/" + "home/" + "alice/x\n").encode("utf-8")

        with patch("scan_sensitive._read_file", side_effect=fake_read):
            code, out, _ = self.scan()
        self.assertEqual(code, 2)
        self.assertEqual(out, "")


class EncodedContentTests(RepoTestCase):
    def test_utf16_worktree_files_are_decoded_and_scanned(self) -> None:
        text = "/" + "home/" + "alice/x"
        write(self.repo, "le-bom.txt", b"\xff\xfe" + text.encode("utf-16-le"))
        write(self.repo, "le.txt", text.encode("utf-16-le"))
        write(self.repo, "be-bom.txt", b"\xfe\xff" + text.encode("utf-16-be"))
        code, out, _ = self.scan()
        self.assertEqual(code, 1)
        for name in ("le-bom.txt", "le.txt", "be-bom.txt"):
            with self.subTest(name=name):
                self.assertIn(f"{name}:1: home-path: ", out)

    def test_utf8_bom_alone_is_not_flagged(self) -> None:
        write(self.repo, "bom.txt", b"\xef\xbb\xbf" + b"hello")
        code, out, _ = self.scan()
        self.assertEqual(code, 0)
        self.assertEqual(out.strip(), "no findings")


class EncodedHistoryTests(RepoTestCase):
    def test_utf16_blob_in_history_is_decoded(self) -> None:
        text = "/" + "home/" + "alice/x"
        write(self.repo, "enc.txt", b"\xff\xfe" + text.encode("utf-16-le"))
        track(self.repo, "enc.txt")
        commit(self.repo, "feat: add encoded file")
        git(self.repo, "rm", "-q", "enc.txt")
        commit(self.repo, "chore: remove encoded file")
        blob = git(self.repo, "rev-parse", "HEAD~1:enc.txt").strip()
        code, out, _ = self.scan("--history")
        self.assertEqual(code, 1)
        self.assertIn(f"history {blob[:8]} enc.txt:1: home-path", out)


class HelpTests(unittest.TestCase):
    def test_help_exits_zero_and_prints_limitations(self) -> None:
        out = io.StringIO()
        with redirect_stdout(out), self.assertRaises(SystemExit) as raised:
            scan_sensitive.main(["--help"])
        self.assertEqual(raised.exception.code, 0)
        self.assertIn("Limitations:", out.getvalue())
        self.assertIn("IPv6", out.getvalue())


class SelfScanTests(unittest.TestCase):
    def test_repository_scans_clean_with_builtin_rules(self) -> None:
        code, out, _ = run_cli(["--root", str(ROOT)])
        self.assertEqual(code, 0, out)
        self.assertEqual(out.strip(), "no findings")


class CliErrorTests(unittest.TestCase):
    def test_non_git_root_exits_two(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            code, _, err = run_cli(["--root", tmp])
        self.assertEqual(code, 2)
        self.assertTrue(err.strip(), "a reason must be written to stderr")


if __name__ == "__main__":
    unittest.main()
