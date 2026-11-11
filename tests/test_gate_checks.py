"""Unit tests for the pure gate checks in scripts/gate_checks.py (no git, no processes)."""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import contract_presence  # noqa: E402
import gate_checks as gc  # noqa: E402
import plan_contract  # noqa: E402

CheckLine = contract_presence.CheckLine
NO_NEWLINE_MARK = "\\ No newline at end of file"
TESTS = ["tests/*.py"]
SKILLS = ["/s/tdd-workflow/SKILL.md"]
REPORT_OUTSIDE = (
    "## Out-of-scope findings\n"
    "### Checks failing outside the task\n"
    "- make lint: E1\n"
    "## Next\n"
)
DIFF_TWO_FILES = "\n".join([
    "diff --git a/scripts/a.py b/scripts/a.py",
    "index 1111111..2222222 100644",
    "--- a/scripts/a.py",
    "+++ b/scripts/a.py",
    "@@ -2 +2,2 @@",
    "-old line",
    "+new line",
    "++x",
    "diff --git a/docs/old.md b/docs/old.md",
    "deleted file mode 100644",
    "index 3333333..0000000",
    "--- a/docs/old.md",
    "+++ /dev/null",
    "@@ -1,2 +0,0 @@",
    "-first",
    "-second",
    NO_NEWLINE_MARK,
]) + "\n"


def R(cmd, code, tail=""):
    return gc.CommandResult(cmd, code, tail)


class ApiConstantsTest(unittest.TestCase):
    def test_status_values_and_timeout_code(self):
        self.assertEqual((gc.PASS, gc.FAIL, gc.NA), ("pass", "fail", "n/a"))
        self.assertEqual(gc.TIMEOUT, -1)


class MatchesTest(unittest.TestCase):
    def test_tc1_glob_and_prefix_patterns(self):
        self.assertTrue(gc.matches("agents/a.md", ["agents/*.md"]))
        self.assertTrue(gc.matches("docs/x/y.md", ["docs/"]))
        self.assertFalse(gc.matches("scripts/a.py", ["scripts/b.py"]))


class ParseDiffTest(unittest.TestCase):
    def test_tc2_added_and_removed_lines_per_file(self):
        self.assertEqual(gc.parse_diff(DIFF_TWO_FILES), {
            "scripts/a.py": (["new line", "+x"], ["old line"]),
            "docs/old.md": ([], ["first", "second"]),
        })

    def test_empty_diff_has_no_files(self):
        self.assertEqual(gc.parse_diff(""), {})


class RedCheckTest(unittest.TestCase):
    def test_tc3_pass_when_red_fails_and_guard_passes(self):
        result = gc.red_check(True, [R("r", 1)], [R("g", 0)])
        self.assertEqual(result.name, "red")
        self.assertEqual(result.status, gc.PASS)
        self.assertEqual(
            result.detail, "1 red commands fail and 1 guard commands pass on commit one")

    def test_tc3_red_passing_fails(self):
        result = gc.red_check(True, [R("r", 0)], [])
        self.assertEqual(result.status, gc.FAIL)
        self.assertIn("passes on commit one: r", result.detail)

    def test_tc3_red_timeout_fails(self):
        result = gc.red_check(True, [R("r", gc.TIMEOUT)], [])
        self.assertEqual(result.status, gc.FAIL)
        self.assertIn("timed out on commit one: r", result.detail)

    def test_tc3_guard_failure_fails(self):
        result = gc.red_check(True, [], [R("g", 2)])
        self.assertEqual(result.status, gc.FAIL)
        self.assertIn("guard fails on commit one (exit 2): g", result.detail)

    def test_tc3_not_test_first_is_not_applicable(self):
        result = gc.red_check(False, [], [])
        self.assertEqual(result.status, gc.NA)
        self.assertEqual(result.detail, "no red or guard lines")


class IntegrityCheckTest(unittest.TestCase):
    def test_tc4_commit_one_must_hold_only_tests(self):
        result = gc.integrity_check(
            True, ["tests/test_a.py", "scripts/a.py"], [], TESTS, {})
        self.assertEqual(result.name, "integrity")
        self.assertEqual(result.status, gc.FAIL)
        self.assertIn("commit one changes non-test files: scripts/a.py", result.detail)

    def test_tc4_later_commits_must_not_touch_commit_one_files(self):
        result = gc.integrity_check(
            True, ["tests/test_a.py"], ["tests/test_a.py"], TESTS, {})
        self.assertEqual(result.status, gc.FAIL)
        self.assertIn("later commits change commit-one files: tests/test_a.py", result.detail)

    def test_tc4_later_commits_on_other_files_pass(self):
        result = gc.integrity_check(
            True, ["tests/test_a.py"], ["scripts/a.py"], TESTS, {})
        self.assertEqual(result.status, gc.PASS)

    def test_tc5_skip_marker_added_fails(self):
        diff = {"tests/test_a.py": (['    @unittest.skip("x")'], [])}
        result = gc.integrity_check(False, [], [], TESTS, diff)
        self.assertEqual(result.status, gc.FAIL)
        self.assertIn('adds a skip or only marker: tests/test_a.py: @unittest.skip("x")',
                      result.detail)

    def test_tc5_only_and_xfail_markers_fail(self):
        for line in ["it.only('x', () => {});", "pytest.mark.xfail(reason='x')"]:
            with self.subTest(line=line):
                diff = {"tests/test_a.py": ([line], [])}
                result = gc.integrity_check(False, [], [], TESTS, diff)
                self.assertEqual(result.status, gc.FAIL)
                self.assertIn("adds a skip or only marker", result.detail)

    def test_tc5_at_most_five_skip_markers_are_named(self):
        added = ["    @unittest.skip('x')"] * 6
        diff = {"tests/test_a.py": (added, [])}
        result = gc.integrity_check(False, [], [], TESTS, diff)
        self.assertEqual(result.detail.count("adds a skip or only marker"), 5)

    def test_tc5_clean_diff_passes(self):
        diff = {"tests/test_a.py": (["    self.assertEqual(a, 1)"], [])}
        result = gc.integrity_check(False, [], [], TESTS, diff)
        self.assertEqual(result.status, gc.PASS)
        self.assertEqual(result.detail, "no test-integrity issues")

    def test_tc6_replaced_assertion_passes(self):
        diff = {"tests/t.py": (["self.assertEqual(a, 2)"], ["self.assertEqual(a, 1)"])}
        result = gc.integrity_check(False, [], [], TESTS, diff)
        self.assertEqual(result.status, gc.PASS)

    def test_tc6_removed_assertions_fail(self):
        diff = {"tests/t.py": (
            ["self.assertEqual(a, 2)"],
            ["self.assertEqual(a, 1)", "self.assertTrue(b)"],
        )}
        result = gc.integrity_check(False, [], [], TESTS, diff)
        self.assertEqual(result.status, gc.FAIL)
        self.assertIn("removes assertions: tests/t.py (removed 2, added 1)", result.detail)


class CoverageCheckTest(unittest.TestCase):
    def test_tc7_ids_found_in_commit_one(self):
        result = gc.coverage_check(True, ["TC1", "TC3"], "def test_tc1_x\n# TC3: guard\n")
        self.assertEqual(result.name, "coverage")
        self.assertEqual(result.status, gc.PASS)
        self.assertEqual(result.detail, "2 Test Case IDs found in commit one")

    def test_tc7_missing_ids_fail(self):
        result = gc.coverage_check(True, ["TC1", "TC3"], "def test_tc13_x")
        self.assertEqual(result.status, gc.FAIL)
        self.assertEqual(result.detail, "no test names TC1, TC3")

    def test_tc7_no_ids_is_not_applicable(self):
        result = gc.coverage_check(True, [], "def test_tc1_x")
        self.assertEqual(result.status, gc.NA)
        self.assertEqual(result.detail, "no Test Case IDs")

    def test_tc7_not_test_first_is_not_applicable(self):
        result = gc.coverage_check(False, ["TC1"], "def test_tc1_x")
        self.assertEqual(result.status, gc.NA)
        self.assertEqual(result.detail, "no red or guard lines")


class ScopeCheckTest(unittest.TestCase):
    def test_tc8_file_outside_scope_fails(self):
        result = gc.scope_check(["scripts/a.py", "README.md"], ["scripts/*.py"], [])
        self.assertEqual(result.name, "scope")
        self.assertEqual(result.status, gc.FAIL)
        self.assertEqual(result.detail, "outside the files and tests lines: README.md")

    def test_tc8_files_and_tests_in_scope_pass(self):
        result = gc.scope_check(
            ["scripts/a.py", "tests/test_a.py"], ["scripts/*.py"], ["tests/*.py"])
        self.assertEqual(result.status, gc.PASS)
        self.assertEqual(result.detail, "2 changed files in scope")


class ContractCheckTest(unittest.TestCase):
    def test_tc9_no_contract_lines_is_not_applicable(self):
        result = gc.contract_check([plan_contract.NO_CONTRACT], None)
        self.assertEqual(result.name, "contract")
        self.assertEqual(result.status, gc.NA)
        self.assertEqual(result.detail, "the plan has no Contract lines")

    def test_tc9_plan_errors_fail(self):
        result = gc.contract_check(["line 3: x"], None)
        self.assertEqual(result.status, gc.FAIL)
        self.assertEqual(result.detail, "line 3: x")

    def test_tc9_at_most_five_errors_are_named(self):
        result = gc.contract_check(["e1", "e2", "e3", "e4", "e5", "e6"], None)
        self.assertEqual(result.detail, "e1; e2; e3; e4; e5")

    def test_tc9_no_lines_passes(self):
        result = gc.contract_check([], [])
        self.assertEqual(result.status, gc.PASS)
        self.assertEqual(result.detail, "no provides or requires lines")

    def test_tc9_present_lines_pass(self):
        lines = [
            CheckLine(True, "provides symbol f in a.py", "found"),
            CheckLine(True, "requires symbol g in b.py", "found"),
        ]
        result = gc.contract_check([], lines)
        self.assertEqual(result.status, gc.PASS)
        self.assertEqual(result.detail, "2 contract lines present")

    def test_tc9_missing_line_fails(self):
        lines = [CheckLine(False, "provides symbol f in a.py", "not found in a.py")]
        result = gc.contract_check([], lines)
        self.assertEqual(result.status, gc.FAIL)
        self.assertEqual(
            result.detail, "missing: provides symbol f in a.py (not found in a.py)")


class ListedOutsideTest(unittest.TestCase):
    def test_command_in_section_is_listed(self):
        self.assertTrue(gc.listed_outside("make lint", REPORT_OUTSIDE))

    def test_command_outside_section_is_not_listed(self):
        self.assertFalse(gc.listed_outside("make test", REPORT_OUTSIDE))

    def test_missing_report_or_section_is_not_listed(self):
        self.assertFalse(gc.listed_outside("make lint", None))
        self.assertFalse(gc.listed_outside("make lint", "## Next\n- make lint: E1\n"))

    def test_line_after_next_heading_is_not_listed(self):
        report = "### Checks failing outside the task\n## Next\n- make lint: E1\n"
        self.assertFalse(gc.listed_outside("make lint", report))


class GreenCheckTest(unittest.TestCase):
    def test_tc10_passing_commands_pass(self):
        result = gc.green_check([R("make test", 0)], {}, None)
        self.assertEqual(result.name, "green")
        self.assertEqual(result.status, gc.PASS)

    def test_tc10_failing_command_fails_with_tail(self):
        result = gc.green_check([R("make lint", 2, "E1")], {}, None)
        self.assertEqual(result.status, gc.FAIL)
        self.assertIn("fails (exit 2): make lint", result.detail)
        self.assertIn("E1", result.detail)

    def test_tc10_listed_and_failing_on_base_is_accepted(self):
        result = gc.green_check(
            [R("make lint", 2, "E1")], {"make lint": R("make lint", 2)}, REPORT_OUTSIDE)
        self.assertEqual(result.status, gc.PASS)
        self.assertIn("make lint", result.detail)

    def test_tc10_listed_but_passing_on_base_fails(self):
        result = gc.green_check(
            [R("make lint", 2, "E1")], {"make lint": R("make lint", 0)}, REPORT_OUTSIDE)
        self.assertEqual(result.status, gc.FAIL)

    def test_listed_but_timed_out_on_base_fails(self):
        result = gc.green_check(
            [R("make lint", 2, "E1")],
            {"make lint": R("make lint", gc.TIMEOUT)},
            REPORT_OUTSIDE,
        )
        self.assertEqual(result.status, gc.FAIL)

    def test_tc10_unlisted_failure_fails(self):
        result = gc.green_check(
            [R("make lint", 2, "E1")], {"make lint": R("make lint", 2)}, "## Next\n")
        self.assertEqual(result.status, gc.FAIL)


class ReportCheckTest(unittest.TestCase):
    def _skill_check(self, report):
        return gc.report_check(report, ["abc1234"], ["abc1234aaaa"], SKILLS)

    def test_tc11_missing_report_fails(self):
        result = gc.report_check(None, ["abc1234"], ["abc1234aaaa"], [])
        self.assertEqual(result.name, "report")
        self.assertEqual(result.status, gc.FAIL)
        self.assertEqual(result.detail, "report file missing")

    def test_tc11_matching_commit_prefixes_pass(self):
        result = gc.report_check(
            "report", ["abc1234", "def5678"], ["abc1234aaaa", "def5678bbbb"], [])
        self.assertEqual(result.status, gc.PASS)
        self.assertEqual(result.detail, "commits match; 0 skills named")

    def test_tc11_commit_count_mismatch_fails(self):
        result = gc.report_check(
            "report", ["abc1234", "def5678"], ["abc1234aaaa"], [])
        self.assertEqual(result.status, gc.FAIL)
        self.assertIn("status line commits", result.detail)

    def test_tc11_claimed_sha_not_a_prefix_fails(self):
        result = gc.report_check("report", ["xyz9999"], ["abc1234aaaa"], [])
        self.assertEqual(result.status, gc.FAIL)
        self.assertIn("status line commits", result.detail)

    def test_tc11_skill_named_on_loaded_line_passes(self):
        result = self._skill_check("Skills loaded: tdd-workflow\n")
        self.assertEqual(result.status, gc.PASS)
        self.assertEqual(result.detail, "commits match; 1 skills named")

    def test_tc11_skill_path_named_in_block_lines_passes(self):
        result = self._skill_check("1. Skills loaded:\n- /s/tdd-workflow/SKILL.md\n")
        self.assertEqual(result.status, gc.PASS)

    def test_tc11_missing_skills_line_fails(self):
        result = self._skill_check("## Summary\nDone.\n")
        self.assertEqual(result.status, gc.FAIL)
        self.assertIn("no Skills loaded line", result.detail)

    def test_tc11_skills_line_naming_none_fails(self):
        result = self._skill_check("Skills loaded: none\n")
        self.assertEqual(result.status, gc.FAIL)
        self.assertIn("Skills loaded line lacks: tdd-workflow", result.detail)

    def test_tc11_skill_after_blank_line_is_outside_block(self):
        result = self._skill_check("Skills loaded: none\n\n/s/tdd-workflow/SKILL.md\n")
        self.assertEqual(result.status, gc.FAIL)


class FailedNamesTest(unittest.TestCase):
    def test_tc12_keeps_order_of_failures(self):
        results = [
            gc.CheckResult("red", gc.PASS, ""),
            gc.CheckResult("scope", gc.FAIL, ""),
            gc.CheckResult("green", gc.FAIL, ""),
        ]
        self.assertEqual(gc.failed_names(results), ["scope", "green"])


if __name__ == "__main__":
    unittest.main()
