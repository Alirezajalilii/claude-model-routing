"""Tests for the ownership rules in scripts/clean_scope.py.

The functions under test are pure: most tests pass plain strings. The path
checks (scratch and handoff directories) use throwaway directories created in
tempfile.TemporaryDirectory(), so no test touches a real run directory. Nothing
here runs git.
"""

import ast
import os
import re
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import clean_scope as cs  # noqa: E402

LS = chr(0x2028)  # Unicode LINE SEPARATOR
FS = chr(0x1c)  # file separator control character
PERSIAN_ZERO = 0x06F0  # Unicode block of Arabic-Indic (Persian) digits
FULLWIDTH_ZERO = 0xFF10  # Unicode block of fullwidth digits


def _digits(zero: int, text: str) -> str:
    """Spell the ASCII digits of text with the digits of the block starting at zero."""
    return "".join(chr(zero + int(char)) if char.isdigit() else char for char in text)


PERSIAN_DATE = _digits(PERSIAN_ZERO, "2026-11-14")  # 2026-11-14 in Persian digits
FULLWIDTH_DATE = _digits(FULLWIDTH_ZERO, "2026-11-14")  # 2026-11-14 in fullwidth digits
UNICODE_CLASS_RE = re.compile(r"\\[dDwWsSbB]")
DIGIT_METHODS = {"isdigit", "isdecimal", "isnumeric", "isalnum", "isalpha"}
RE_FUNCS = {"compile", "match", "search", "fullmatch", "sub", "subn", "split",
            "findall", "finditer"}


def _is_re_attr(node: ast.AST, names: set) -> bool:
    return (isinstance(node, ast.Attribute) and node.attr in names
            and isinstance(node.value, ast.Name) and node.value.id == "re")


def _dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def _file(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("x\n")
    return path


class PlanSlugTest(unittest.TestCase):
    """plan_slug drops the directory, the .md suffix and the date prefix."""

    # TC1
    def test_dated_plan_path(self) -> None:
        self.assertEqual(
            cs.plan_slug("docs/plans/2026-11-14-orchestrator-cleanup.md"),
            "orchestrator-cleanup")

    # TC1
    def test_plain_plan_name(self) -> None:
        self.assertEqual(cs.plan_slug("/x/my-plan.md"), "my-plan")

    # TC1
    def test_name_without_suffix(self) -> None:
        self.assertEqual(cs.plan_slug("2026-01-02-a-b"), "a-b")

    # TC71
    def test_tc71_non_ascii_digit_prefixes_are_not_date_prefixes(self) -> None:
        self.assertEqual(cs.plan_slug("docs/plans/" + PERSIAN_DATE + "-x.md"),
                         PERSIAN_DATE + "-x")
        self.assertEqual(cs.plan_slug(FULLWIDTH_DATE + "-x.md"), FULLWIDTH_DATE + "-x")
        pattern = cs.owned_pattern(cs.plan_slug(PERSIAN_DATE + "-x.md"), ["T1"])
        self.assertIsNone(pattern.fullmatch("agent/x-T1"))
        self.assertEqual(cs.plan_slug("docs/plans/2026-11-14-x.md"), "x")


class OwnedPatternTest(unittest.TestCase):
    """owned_pattern matches only the integration and task branches of a plan."""

    def setUp(self) -> None:
        self.pattern = cs.owned_pattern("orchestrator-cleanup", ["T1", "T2"])

    # TC2
    def test_owned_names_match(self) -> None:
        names = ["agent/orchestrator-cleanup-integration",
                 "agent/orchestrator-cleanup-T1",
                 "agent/orchestrator-cleanup-T2-2",
                 "agent/orchestrator-cleanup-integration-3"]
        for name in names:
            with self.subTest(name=name):
                self.assertTrue(self.pattern.fullmatch(name))

    # TC2
    def test_other_names_do_not_match(self) -> None:
        names = ["agent/orchestrator-cleanup-v2-T1",
                 "agent/orchestrator-cleanup-T3",
                 "agent/orchestrator-cleanup-T1x",
                 "agent/orchestrator-cleanup",
                 "agent/orchestrator-cleanup-T1-2a",
                 "main",
                 "agent/other-T1",
                 "xagent/orchestrator-cleanup-T1"]
        for name in names:
            with self.subTest(name=name):
                self.assertFalse(self.pattern.fullmatch(name))

    # TC3
    def test_metacharacters_are_escaped(self) -> None:
        pattern = cs.owned_pattern("a.b", ["T.1"])
        self.assertFalse(pattern.fullmatch("agent/aXb-T.1"))
        self.assertFalse(pattern.fullmatch("agent/a.b-TX1"))
        self.assertTrue(pattern.fullmatch("agent/a.b-T.1"))

    # TC72
    def test_tc72_retry_suffix_takes_ascii_digits_only(self) -> None:
        pattern = cs.owned_pattern("s", ["T1"])
        self.assertTrue(pattern.fullmatch("agent/s-T1-2"))
        self.assertIsNone(pattern.fullmatch("agent/s-T1-" + _digits(PERSIAN_ZERO, "2")))
        self.assertIsNone(pattern.fullmatch("agent/s-T1-" + _digits(FULLWIDTH_ZERO, "2")))


class SelectOwnedTest(unittest.TestCase):
    """select_owned splits names into owned local ones and missing explicit ones."""

    # TC4
    def test_local_matches_and_missing_explicit(self) -> None:
        local = ["main", "agent/s-T1", "agent/s-integration", "agent/t-T1",
                 "fix/x"]
        result = cs.select_owned(local, cs.owned_pattern("s", ["T1"]),
                                 ["fix/x", "nope", "nope"])
        self.assertEqual(result, (["agent/s-T1", "agent/s-integration",
                                   "fix/x"], ["nope"]))

    # TC4
    def test_no_pattern_and_no_explicit_names(self) -> None:
        self.assertEqual(cs.select_owned(["main", "agent/s-T1"], None, []),
                         ([], []))


class ParseWorktreesTest(unittest.TestCase):
    """parse_worktrees reads `git worktree list --porcelain` entries in order."""

    PORCELAIN = (
        "worktree /r\n"
        "HEAD aaa\n"
        "branch refs/heads/main\n"
        "\n"
        "worktree /r/w1\n"
        "HEAD bbb\n"
        "branch refs/heads/agent/s-T1\n"
        "\n"
        "worktree /r/w2\n"
        "HEAD ccc\n"
        "detached\n"
        "\n"
        "worktree /r/w3\n"
        "HEAD ddd\n"
        "branch refs/heads/agent/s-T2\n"
        "locked reason text\n"
        "\n"
        "worktree /r/w4\n"
        "HEAD eee\n"
        "branch refs/heads/agent/s-T3\n"
        "prunable gitdir file points to non-existent location\n"
    )

    # TC5
    def test_entries_in_order(self) -> None:
        self.assertEqual(cs.parse_worktrees(self.PORCELAIN), [
            cs.Worktree("/r", "main", False, False),
            cs.Worktree("/r/w1", "agent/s-T1", False, False),
            cs.Worktree("/r/w2", None, False, False),
            cs.Worktree("/r/w3", "agent/s-T2", True, False),
            cs.Worktree("/r/w4", "agent/s-T3", False, True),
        ])

    # TC5
    def test_bare_locked_line_sets_locked(self) -> None:
        text = "worktree /r/w5\nHEAD fff\nbranch refs/heads/agent/s-T4\nlocked\n"
        self.assertEqual(cs.parse_worktrees(text),
                         [cs.Worktree("/r/w5", "agent/s-T4", True, False)])

    # TC5
    def test_bare_repository_has_no_branch(self) -> None:
        self.assertEqual(cs.parse_worktrees("worktree /r/b\nbare\n"),
                         [cs.Worktree("/r/b", None, False, False)])


class ParseWorktreesSepTest(unittest.TestCase):
    """parse_worktrees with a separator splits fields on that separator only."""

    # TC16
    def test_tc16_nul_separated_entries_keep_newline_and_separator_in_paths(self) -> None:
        text = ("worktree /r/a\nb\0HEAD aaa\0branch refs/heads/main\0\0"
                "worktree /r/w" + LS + "1\0HEAD bbb\0branch refs/heads/agent/s-T1"
                "\0locked\0\0")
        self.assertEqual(cs.parse_worktrees(text, "\0"), [
            cs.Worktree("/r/a\nb", "main", False, False),
            cs.Worktree("/r/w" + LS + "1", "agent/s-T1", True, False),
        ])

    # TC17
    def test_tc17_newline_form_keeps_control_characters_in_paths(self) -> None:
        path = "/r/a" + FS + "b" + LS + "c"
        text = "worktree " + path + "\nHEAD aaa\nbranch refs/heads/agent/s-T1\n"
        self.assertEqual(cs.parse_worktrees(text),
                         [cs.Worktree(path, "agent/s-T1", False, False)])


class ScratchProblemTest(unittest.TestCase):
    """scratch_problem accepts real directories at least three levels below a temp root."""

    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name).resolve()
        self.roots = [self.root]

    # TC6
    def test_directory_three_levels_down_is_accepted(self) -> None:
        path = _dir(self.root / "a" / "b" / "c")
        self.assertIsNone(cs.scratch_problem(path, self.roots))

    # TC6
    def test_directory_two_levels_down_is_refused(self) -> None:
        path = _dir(self.root / "a" / "b")
        self.assertEqual(
            cs.scratch_problem(path, self.roots),
            f"{path} is less than 3 levels below the temp directory {self.root}")

    # TC6
    def test_temp_root_itself_is_refused(self) -> None:
        self.assertEqual(cs.scratch_problem(self.root, self.roots),
                         f"{self.root} is not inside a temp directory")

    # TC6
    def test_directory_under_another_temp_dir_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as other_tmp:
            other = Path(other_tmp).resolve()
            path = _dir(other / "a" / "b" / "c")
            self.assertEqual(cs.scratch_problem(path, self.roots),
                             f"{path} is not inside a temp directory")

    # TC6
    def test_symbolic_link_is_refused(self) -> None:
        target = _dir(self.root / "a" / "b" / "c")
        link = self.root / "a" / "b" / "link"
        os.symlink(target, link)
        self.assertEqual(cs.scratch_problem(link, self.roots),
                         f"{link} is a symbolic link")

    # TC6
    def test_regular_file_is_refused(self) -> None:
        path = _file(self.root / "a" / "b" / "f.txt")
        self.assertEqual(cs.scratch_problem(path, self.roots),
                         f"{path} is not a directory")

    # TC6
    def test_missing_path_is_refused(self) -> None:
        path = self.root / "a" / "b" / "missing"
        self.assertEqual(cs.scratch_problem(path, self.roots),
                         f"{path} does not exist")

    # TC63
    def test_tc63_directory_must_be_spelled_as_on_disk(self) -> None:
        path = _dir(self.root / "a" / "b" / "c")
        with mock.patch.object(cs.os, "listdir", return_value=[]):
            self.assertEqual(cs.scratch_problem(path, self.roots),
                             f"{path} is not spelled as on disk")
        self.assertIsNone(cs.scratch_problem(path, self.roots))

    # TC63
    def test_tc63_case_variant_of_scratch_directory(self) -> None:
        variant = self.root / "A" / "B" / "C"
        _dir(self.root / "a" / "b" / "c")
        if variant.is_dir():
            self.assertEqual(cs.scratch_problem(variant, self.roots),
                             f"{variant} is not spelled as on disk")
        else:
            self.assertEqual(cs.scratch_problem(variant, self.roots),
                             f"{variant} does not exist")


class TempRootsTest(unittest.TestCase):
    """temp_roots lists resolved, existing temp directories without duplicates."""

    # TC7
    def test_given_tempdir_comes_first(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = cs.temp_roots(tmp)
            self.assertEqual(result[0], Path(tmp).resolve())

    # TC7
    def test_missing_tempdir_is_left_out(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            missing = str(Path(tmp) / "missing")
            self.assertNotIn(Path(missing).resolve(), cs.temp_roots(missing))

    # TC7
    def test_no_duplicates_when_tempdir_is_tmp(self) -> None:
        result = cs.temp_roots("/tmp")
        self.assertEqual(len(result), len(set(result)))


class PathWithinTest(unittest.TestCase):
    """path_within compares by name or by file identity, below the outer directory."""

    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name).resolve()

    # TC58
    def test_tc58_names_inside_and_outside(self) -> None:
        a = _dir(self.root / "a")
        b = _dir(a / "b")
        x = _dir(self.root / "x")
        self.assertTrue(cs.path_within(b, a))
        self.assertTrue(cs.path_within(b, a, strict=True))
        self.assertTrue(cs.path_within(a, a))
        self.assertTrue(cs.path_within(a / "ghost" / "g", a))
        self.assertFalse(cs.path_within(a, a, strict=True))
        self.assertFalse(cs.path_within(x, a))
        self.assertFalse(cs.path_within(a, b))

    # TC59
    def test_tc59_file_identity_on_any_file_system(self) -> None:
        p = _dir(self.root / "p" / "q")
        r = _dir(self.root / "r")

        def fake(first: str, second: str) -> bool:
            return Path(first) == p and Path(second) == r

        with mock.patch.object(cs.os.path, "samefile", side_effect=fake):
            self.assertTrue(cs.path_within(p / "f", r))
            self.assertTrue(cs.path_within(p, r))
            self.assertFalse(cs.path_within(p, r, strict=True))
        self.assertFalse(cs.path_within(p / "f", r))

    # TC60
    def test_tc60_case_variant_spelling(self) -> None:
        a = _dir(self.root / "a")
        b = _dir(a / "b")
        variant = self.root / "A"
        if variant.is_dir():
            self.assertTrue(cs.path_within(variant / "b", a))
            self.assertTrue(cs.path_within(variant / "b", a, strict=True))
            self.assertTrue(cs.path_within(variant, a))
            self.assertTrue(cs.path_within(b, variant))
            self.assertFalse(cs.path_within(variant, a, strict=True))
        else:
            self.assertFalse(cs.path_within(variant / "b", a))
            self.assertFalse(cs.path_within(b, variant))


class HandoffProblemTest(unittest.TestCase):
    """handoff_problem accepts only git-ignored directories inside the repository."""

    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.repo = Path(tmp.name).resolve()
        self.run = _dir(self.repo / "docs" / "handoffs" / "2026-01-01-run1")

    # TC8
    def test_ignored_directory_is_accepted(self) -> None:
        self.assertIsNone(cs.handoff_problem(self.run, self.repo, True, []))

    # TC8
    def test_directory_not_ignored_is_refused(self) -> None:
        self.assertEqual(cs.handoff_problem(self.run, self.repo, False, []),
                         f"{self.run} is not git-ignored")

    # TC8
    def test_repository_itself_is_refused(self) -> None:
        self.assertEqual(cs.handoff_problem(self.repo, self.repo, True, []),
                         f"{self.repo} is not inside the repository")

    # TC8
    def test_directory_in_another_temp_dir_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as other_tmp:
            other = _dir(Path(other_tmp).resolve() / "run")
            self.assertEqual(cs.handoff_problem(other, self.repo, True, []),
                             f"{other} is not inside the repository")

    # TC8
    def test_git_file_directly_inside_is_refused(self) -> None:
        _file(self.run / ".git")
        self.assertEqual(cs.handoff_problem(self.run, self.repo, True, []),
                         f"{self.run} holds a .git entry")

    # TC8
    def test_git_directory_two_levels_down_is_refused(self) -> None:
        _dir(self.run / "x" / "y" / ".git")
        self.assertEqual(cs.handoff_problem(self.run, self.repo, True, []),
                         f"{self.run} holds a .git entry")

    # TC8
    def test_symbolic_link_is_refused(self) -> None:
        link = self.repo / "docs" / "handoffs" / "link"
        os.symlink(self.run, link)
        self.assertEqual(cs.handoff_problem(link, self.repo, True, []),
                         f"{link} is a symbolic link")

    # TC8
    def test_missing_path_is_refused(self) -> None:
        missing = self.repo / "docs" / "handoffs" / "missing"
        self.assertEqual(cs.handoff_problem(missing, self.repo, True, []),
                         f"{missing} does not exist")

    # TC10
    def test_parent_of_a_held_worktree_is_refused(self) -> None:
        held = _dir(self.run / "wt")
        problem = cs.handoff_problem(self.run.parent, self.repo, True, [held])
        self.assertEqual(problem, f"{self.run.parent} holds {held}")

    # TC10
    def test_held_file_inside_directory_is_refused(self) -> None:
        held = _file(self.run / "plan.md")
        self.assertEqual(cs.handoff_problem(self.run, self.repo, True, [held]),
                         f"{self.run} holds {held}")

    # TC10
    def test_held_path_equal_to_directory_is_refused(self) -> None:
        self.assertEqual(cs.handoff_problem(self.run, self.repo, True, [self.run]),
                         f"{self.run} holds {self.run}")

    # TC10
    def test_held_path_elsewhere_is_accepted(self) -> None:
        held = _file(self.repo / "docs" / "plans" / "p.md")
        self.assertIsNone(cs.handoff_problem(self.run, self.repo, True, [held]))

    # TC27
    def test_tc27_names_that_are_not_run_directories_are_refused(self) -> None:
        names = ["docs/plans", ".agent", "docs/handoffs", "docs/handoffs/run1",
                 "docs/handoffs/2026-1-14-x", "docs/handoffs/2026-11-14-",
                 "docs/handoffs/2026-11-14-a b", "docs/handoffs/2026-11-14--x"]
        for name in names:
            with self.subTest(name=name):
                path = _dir(self.repo / name)
                self.assertEqual(
                    cs.handoff_problem(path, self.repo, True, []),
                    f"{path} is not a run directory named <YYYY-MM-DD>-<topic-slug>")

    # TC27
    def test_tc27_run_directory_names_are_accepted(self) -> None:
        for name in [".agent/runs/2026-11-14-x",
                     "docs/handoffs/2026-11-14-Topic_1.v2"]:
            with self.subTest(name=name):
                path = _dir(self.repo / name)
                self.assertIsNone(cs.handoff_problem(path, self.repo, True, []))

    # TC28
    def test_tc28_tracked_or_unignored_files_are_refused_before_the_ignore_check(self) -> None:
        listed = ["docs/handoffs/2026-01-01-run1/t.md"]
        message = (f"{self.run} holds files that are tracked or not git-ignored: "
                   "docs/handoffs/2026-01-01-run1/t.md")
        self.assertEqual(cs.handoff_problem(self.run, self.repo, True, [], listed), message)
        self.assertEqual(cs.handoff_problem(self.run, self.repo, False, [], listed), message)
        self.assertIsNone(cs.handoff_problem(self.run, self.repo, True, [], []))
        self.assertEqual(cs.handoff_problem(self.run, self.repo, False, [], []),
                         f"{self.run} is not git-ignored")

    # TC48
    def test_tc48_held_path_under_a_case_variant_of_the_directory_is_refused(self) -> None:
        held = _dir(self.run / "sub")
        variant = self.repo / "docs" / "HANDOFFS" / "2026-01-01-run1"
        problem = cs.handoff_problem(variant, self.repo, True, [held])
        if variant.is_dir():
            self.assertEqual(problem, f"{variant} holds {held}")
        else:
            self.assertEqual(problem, f"{variant} does not exist")

    # TC61
    def test_tc61_git_directory_in_any_letter_case_is_refused(self) -> None:
        _dir(self.run / "x" / ".GIT")
        self.assertEqual(cs.handoff_problem(self.run, self.repo, True, []),
                         f"{self.run} holds a .git entry")

    # TC61
    def test_tc61_git_file_in_any_letter_case_is_refused(self) -> None:
        run2 = _dir(self.repo / "docs" / "handoffs" / "2026-01-02-run2")
        _file(run2 / ".Git")
        self.assertEqual(cs.handoff_problem(run2, self.repo, True, []),
                         f"{run2} holds a .git entry")

    # TC62
    def test_tc62_directory_must_be_spelled_as_on_disk(self) -> None:
        with mock.patch.object(cs.os, "listdir", return_value=[]):
            self.assertEqual(cs.handoff_problem(self.run, self.repo, True, []),
                             f"{self.run} is not spelled as on disk")
        self.assertIsNone(cs.handoff_problem(self.run, self.repo, True, []))

    # TC62
    def test_tc62_ascii_case_variant_of_run_directory_is_refused(self) -> None:
        variant = self.repo / "docs" / "HANDOFFS" / "2026-01-01-run1"
        problem = cs.handoff_problem(variant, self.repo, True, [])
        if variant.is_dir():
            self.assertEqual(problem, f"{variant} is not spelled as on disk")
        else:
            self.assertEqual(problem, f"{variant} does not exist")

    # TC62
    def test_tc62_non_ascii_case_variant_of_run_directory_is_refused(self) -> None:
        accented = _dir(self.repo / "docs" / "hándoffs" / "2026-01-01-run2")
        self.assertIsNone(cs.handoff_problem(accented, self.repo, True, []))
        upper = self.repo / "docs" / "HÁNDOFFS" / "2026-01-01-run2"
        problem = cs.handoff_problem(upper, self.repo, True, [])
        if upper.is_dir():
            self.assertEqual(problem, f"{upper} is not spelled as on disk")
        else:
            self.assertEqual(problem, f"{upper} does not exist")

    # TC73
    def test_tc73_run_directory_dated_in_non_ascii_digits_is_refused(self) -> None:
        for date in (PERSIAN_DATE, FULLWIDTH_DATE):
            with self.subTest(date=date):
                path = _dir(self.repo / "docs" / "handoffs" / (date + "-x"))
                self.assertEqual(cs.handoff_problem(path, self.repo, True, []),
                                 f"{path} is not a run directory named <YYYY-MM-DD>-<topic-slug>")


class IsProtectedTest(unittest.TestCase):
    """is_protected covers the base branch, main, master and the current branch."""

    # TC9
    def test_protected_names(self) -> None:
        self.assertTrue(cs.is_protected("dev", "dev", None))
        self.assertTrue(cs.is_protected("main", "dev", None))
        self.assertTrue(cs.is_protected("master", "main", None))
        self.assertTrue(cs.is_protected("agent/s-T1", "main", "agent/s-T1"))

    # TC9
    def test_unprotected_names(self) -> None:
        self.assertFalse(cs.is_protected("agent/s-T1", "main", "main"))
        self.assertFalse(cs.is_protected("agent/s-T1", "main", None))


def _call_problems(name: str, node: ast.Call) -> list:
    """Return the problem strings for one call: a digit test, int(), or a regex
    with a Unicode-aware class and no re.ASCII flag."""
    func = node.func
    found = ""
    if isinstance(func, ast.Attribute) and func.attr in DIGIT_METHODS:
        found = f"{func.attr}()"
    elif isinstance(func, ast.Name) and func.id == "int":
        found = "int()"
    elif _is_re_attr(func, RE_FUNCS) and node.args and _has_unicode_class(node.args[0]):
        if not _has_ascii_flag(node):
            found = "regex with a Unicode-aware class and no re.ASCII"
    return [f"{name}:{node.lineno} {found}"] if found else []


def _has_unicode_class(node: ast.AST) -> bool:
    return any(isinstance(sub, ast.Constant) and isinstance(sub.value, str)
               and UNICODE_CLASS_RE.search(sub.value) is not None
               for sub in ast.walk(node))


def _has_ascii_flag(node: ast.Call) -> bool:
    parts = [*node.args[1:], *[keyword.value for keyword in node.keywords]]
    return any(_is_re_attr(sub, {"ASCII", "A"})
               for part in parts for sub in ast.walk(part))


class AsciiDigitSweepTest(unittest.TestCase):
    """Every regex and digit test in the three mr-clean modules is ASCII-only."""

    # TC74
    def test_tc74_no_unicode_aware_digit_or_class_matching(self) -> None:
        problems: list = []
        for name in ("clean_scope.py", "clean_git.py", "clean_cli.py"):
            text = (ROOT / "scripts" / name).read_text(encoding="utf-8")
            for node in ast.walk(ast.parse(text)):
                if isinstance(node, ast.Call):
                    problems.extend(_call_problems(name, node))
        self.assertEqual(problems, [])


if __name__ == "__main__":
    unittest.main()
