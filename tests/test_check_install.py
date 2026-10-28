import contextlib
import io
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import check_install  # noqa: E402

MARKET = "claude-" + "model-routing"
PLUGIN_JSON = '{"name":"model-routing","version":"9.9.9"}'
COMMITTED = {".claude-plugin/plugin.json": PLUGIN_JSON, "scripts/x.py": "print(1)\n"}


def git(repo, *args):
    subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@example.com", "-C", str(repo), *args],
        check=True, capture_output=True,
    )


def write(base, rel, text="x"):
    path = Path(base) / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def run_main(argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = check_install.main(argv)
    return code, out.getvalue(), err.getvalue()


class PureFunctionTests(unittest.TestCase):
    def test_compare_equal(self):
        self.assertEqual(check_install.compare({"a", "b"}, {"a", "b"}), ([], []))

    def test_compare_unexpected_sorted(self):
        installed = {"a", ".agent/x.md", ".DS_Store", "CLAUDE.md"}
        self.assertEqual(
            check_install.compare(installed, {"a"}),
            ([".DS_Store", ".agent/x.md", "CLAUDE.md"], []),
        )

    def test_compare_missing(self):
        self.assertEqual(check_install.compare({"a"}, {"a", "b"}), ([], ["b"]))

    def test_list_installed(self):
        with tempfile.TemporaryDirectory() as tmp:
            for rel in ("a.txt", "sub/b.txt", ".git/config", ".agent/n.md"):
                write(tmp, rel)
            (Path(tmp) / "empty").mkdir()
            self.assertEqual(
                check_install.list_installed(Path(tmp)), {"a.txt", "sub/b.txt", ".agent/n.md"}
            )
            write(tmp, "sub/.git/x")
            self.assertIn("sub/.git/x", check_install.list_installed(Path(tmp)))

    def test_default_plugin_dir(self):
        self.assertEqual(
            check_install.default_plugin_dir(Path("/h"), "1.2.3"),
            Path("/h") / ".claude" / "plugins" / "cache" / MARKET / "model-routing" / "1.2.3",
        )


@unittest.skipUnless(shutil.which("git"), "git not available")
class GitIntegrationTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)
        self.repo = self.tmp / "repo"
        self.repo.mkdir()
        git(self.repo, "init", "-q")
        write(self.repo, ".git/info/exclude", ".agent/\n")
        for rel, text in COMMITTED.items():
            write(self.repo, rel, text)
        write(self.repo, ".agent/n.md")
        git(self.repo, "add", *COMMITTED)
        git(self.repo, "commit", "-q", "-m", "init")

    def make_dir(self, name="d", skip=(), extra=()):
        d = self.tmp / name
        for rel, text in COMMITTED.items():
            if rel not in skip:
                write(d, rel, text)
        for rel in extra:
            write(d, rel)
        return d

    def run_cli(self, d):
        return run_main(["--repo", str(self.repo), "--rev", "HEAD", "--plugin-dir", str(d)])

    def test_list_tracked(self):
        tracked = check_install.list_tracked(str(self.repo), "HEAD")
        self.assertEqual(tracked, set(COMMITTED))
        self.assertNotIn(".agent/n.md", tracked)

    def test_match(self):
        code, out, _ = self.run_cli(self.make_dir())
        self.assertEqual(code, 0)
        self.assertEqual(out.splitlines()[-1], "OK: 2 files match HEAD")

    def test_unexpected(self):
        d = self.make_dir(extra=(".agent/n.md", ".DS_Store"))
        code, out, _ = self.run_cli(d)
        self.assertEqual(code, 1)
        self.assertIn("unexpected: .agent/n.md", out)
        self.assertIn("unexpected: .DS_Store", out)
        self.assertEqual(out.splitlines()[-1], "FAIL: 2 unexpected, 0 missing")
        self.assertNotIn(str(self.tmp), out)
        for line in out.splitlines()[:-1]:
            self.assertFalse(line.split(": ", 1)[1].startswith("/"))

    def test_missing(self):
        d = self.make_dir(skip=("scripts/x.py",))
        code, out, _ = self.run_cli(d)
        self.assertEqual(code, 1)
        self.assertIn("missing: scripts/x.py", out)
        self.assertEqual(out.splitlines()[-1], "FAIL: 0 unexpected, 1 missing")
        self.assertNotIn(str(self.tmp), out)

    def test_nonexistent_plugin_dir(self):
        code, out, err = self.run_cli(self.tmp / "nope")
        self.assertEqual(code, 2)
        self.assertEqual(out, "")
        self.assertTrue(err.strip())

    def test_default_dir_through_git(self):
        home = self.tmp / "home"
        d = home / ".claude" / "plugins" / "cache" / MARKET / "model-routing" / "9.9.9"
        for rel, text in COMMITTED.items():
            write(d, rel, text)
        with mock.patch.object(check_install.Path, "home", return_value=home):
            code, out, _ = run_main(["--repo", str(self.repo), "--rev", "HEAD"])
        self.assertEqual(code, 0, out)


if __name__ == "__main__":
    unittest.main()
