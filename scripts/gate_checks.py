"""Pure gate checks for plan task runs.

Each check takes data (file lists, diff text, command results, report text)
and returns a CheckResult or a plain value. Nothing here runs a process, calls
git or reads a file: the CLI and the git adapter gather the data.
"""

import fnmatch
import re
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Dict, List, Mapping, Optional, Sequence, Tuple

import plan_contract
from contract_presence import CheckLine

PASS, FAIL, NA = "pass", "fail", "n/a"
TIMEOUT = -1  # CommandResult.code of a command that timed out

MAX_NAMED = 5  # findings named in one detail before the rest are counted out
SKIP_MARKERS = tuple(re.compile(p) for p in (
    r"@unittest\.skip", r"\bskipTest\(", r"@unittest\.expectedFailure",
    r"\bpytest\.mark\.(?:skip|skipif|xfail)\b", r"\bpytest\.skip\(",
    r"\b(?:it|describe|test|context)\.(?:skip|only)\(", r"\b(?:xit|xdescribe|xtest|fit|fdescribe)\(",
    r"@Disabled\b", r"@Ignore\b", r"\bt\.Skip(?:Now|f)?\(",
))
ASSERT_RE = re.compile(r"\bassert\w*|\bexpect\s*\(")

ParsedDiff = Dict[str, Tuple[List[str], List[str]]]


@dataclass(frozen=True)
class CommandResult:
    command: str
    code: int  # exit code, or TIMEOUT
    tail: str  # last lines of combined stdout and stderr


@dataclass(frozen=True)
class CheckResult:
    name: str  # red, integrity, coverage, scope, contract, green, report
    status: str  # PASS, FAIL or NA
    detail: str


def _with_tail(text: str, tail: str) -> str:
    lines = [line.strip() for line in tail.splitlines() if line.strip()]
    return f"{text} | {' / '.join(lines)}" if lines else text


def matches(path: str, patterns: Sequence[str]) -> bool:
    for pattern in patterns:
        if pattern.endswith("/") and path.startswith(pattern):
            return True
        if fnmatch.fnmatchcase(path, pattern):
            return True
    return False


def _diff_path(raw: str) -> Optional[str]:
    if raw == "/dev/null":
        return None
    if raw.startswith(("a/", "b/")):
        return raw[2:]
    return raw


def _hunk_line(entry: Tuple[List[str], List[str]], line: str) -> None:
    if line.startswith("+"):
        entry[0].append(line[1:])
    elif line.startswith("-"):
        entry[1].append(line[1:])


def parse_diff(diff: str) -> ParsedDiff:
    """Read `git diff --unified=0 --no-color` output: file -> (added, removed)."""
    files: ParsedDiff = {}
    path: Optional[str] = None
    old: Optional[str] = None
    header = False
    for line in diff.splitlines():
        if line.startswith("diff --git "):
            header, path, old = True, None, None
        elif header and line.startswith("--- "):
            old = _diff_path(line[4:])
        elif header and line.startswith("+++ "):
            path = _diff_path(line[4:]) or old
        elif line.startswith("@@"):
            header = False
            if path is not None:
                files.setdefault(path, ([], []))
        elif not header and path is not None:
            _hunk_line(files[path], line)
    return files


def red_check(test_first: bool, red: Sequence[CommandResult],
              guard: Sequence[CommandResult]) -> CheckResult:
    if not test_first:
        return CheckResult("red", NA, "no red or guard lines")
    problems: List[str] = []
    for result in red:
        if result.code == TIMEOUT:
            text = f"timed out on commit one: {result.command}"
        elif result.code == 0:
            text = f"passes on commit one: {result.command}"
        else:
            continue
        problems.append(_with_tail(text, result.tail))
    for result in guard:
        if result.code != 0:
            text = f"guard fails on commit one (exit {result.code}): {result.command}"
            problems.append(_with_tail(text, result.tail))
    if problems:
        return CheckResult("red", FAIL, "; ".join(problems))
    return CheckResult("red", PASS, f"{len(red)} red commands fail and "
                       f"{len(guard)} guard commands pass on commit one")


def _commit_one_problems(c1_files: Sequence[str], later_files: Sequence[str],
                         tests: Sequence[str]) -> List[str]:
    problems = []
    non_test = [f for f in c1_files if not matches(f, tests)]
    if non_test:
        problems.append("commit one changes non-test files: " + ", ".join(non_test))
    shared = [f for f in c1_files if f in later_files]
    if shared:
        problems.append("later commits change commit-one files: " + ", ".join(shared))
    return problems


def _marker_problems(diff: Mapping[str, Tuple[List[str], List[str]]]) -> List[str]:
    found = []
    for path, (added, _removed) in diff.items():
        for line in added:
            if any(marker.search(line) for marker in SKIP_MARKERS):
                found.append(f"adds a skip or only marker: {path}: {line.strip()}")
    return found[:MAX_NAMED]


def _assertion_problems(diff: Mapping[str, Tuple[List[str], List[str]]]) -> List[str]:
    problems = []
    for path, (added, removed) in diff.items():
        removed_count = sum(1 for line in removed if ASSERT_RE.search(line))
        added_count = sum(1 for line in added if ASSERT_RE.search(line))
        if removed_count > added_count:
            problems.append(f"removes assertions: {path} "
                            f"(removed {removed_count}, added {added_count})")
    return problems


def integrity_check(test_first: bool, c1_files: Sequence[str], later_files: Sequence[str],
                    tests: Sequence[str],
                    diff: Mapping[str, Tuple[List[str], List[str]]]) -> CheckResult:
    problems: List[str] = []
    if test_first:
        problems += _commit_one_problems(c1_files, later_files, tests)
    problems += _marker_problems(diff)
    problems += _assertion_problems(diff)
    if problems:
        return CheckResult("integrity", FAIL, "; ".join(problems))
    return CheckResult("integrity", PASS, "no test-integrity issues")


def _has_case(case_id: str, text: str) -> bool:
    pattern = r"(?i)(?<![A-Za-z0-9])" + re.escape(case_id) + r"(?![0-9])"
    return re.search(pattern, text) is not None


def coverage_check(test_first: bool, case_ids: Sequence[str], c1_added: str) -> CheckResult:
    if not test_first:
        return CheckResult("coverage", NA, "no red or guard lines")
    if not case_ids:
        return CheckResult("coverage", NA, "no Test Case IDs")
    missing = [cid for cid in case_ids if not _has_case(cid, c1_added)]
    if missing:
        return CheckResult("coverage", FAIL, "no test names " + ", ".join(missing))
    return CheckResult("coverage", PASS, f"{len(case_ids)} Test Case IDs found in commit one")


def scope_check(changed: Sequence[str], files: Sequence[str],
                tests: Sequence[str]) -> CheckResult:
    allowed = list(files) + list(tests)
    outside = [path for path in changed if not matches(path, allowed)]
    if outside:
        return CheckResult("scope", FAIL, "outside the files and tests lines: "
                           + ", ".join(outside))
    return CheckResult("scope", PASS, f"{len(changed)} changed files in scope")


def contract_check(errors: Sequence[str], lines: Optional[Sequence[CheckLine]]) -> CheckResult:
    if list(errors) == [plan_contract.NO_CONTRACT]:
        return CheckResult("contract", NA, "the plan has no Contract lines")
    if errors:
        return CheckResult("contract", FAIL, "; ".join(list(errors)[:MAX_NAMED]))
    present = list(lines or [])
    missing = [line for line in present if not line.ok]
    if missing:
        return CheckResult("contract", FAIL, "; ".join(
            f"missing: {line.text} ({line.detail})" for line in missing))
    if not present:
        return CheckResult("contract", PASS, "no provides or requires lines")
    return CheckResult("contract", PASS, f"{len(present)} contract lines present")


def listed_outside(command: str, report: Optional[str]) -> bool:
    if report is None:
        return False
    section: List[str] = []
    inside = False
    for line in report.splitlines():
        if not inside:
            inside = "Checks failing outside the task" in line
            continue
        if line.startswith("#"):
            break
        section.append(line)
    return any(command in line for line in section)


def _base_fails(command: str, base: Mapping[str, CommandResult]) -> bool:
    result = base.get(command)
    return result is not None and result.code not in (0, TIMEOUT)


def green_check(results: Sequence[CommandResult], base: Mapping[str, CommandResult],
                report: Optional[str]) -> CheckResult:
    problems: List[str] = []
    accepted: List[str] = []
    for result in results:
        if result.code == 0:
            continue
        if _base_fails(result.command, base) and listed_outside(result.command, report):
            accepted.append(result.command)
            continue
        problems.append(_with_tail(f"fails (exit {result.code}): {result.command}",
                                   result.tail))
    if problems:
        return CheckResult("green", FAIL, "; ".join(problems))
    detail = f"{len(results) - len(accepted)} commands pass"
    if accepted:
        detail += ("; listed outside the task and also fails on the base commit: "
                   + ", ".join(accepted))
    return CheckResult("green", PASS, detail)


def _commits_match(claimed: Sequence[str], actual: Sequence[str]) -> bool:
    if len(claimed) != len(actual):
        return False
    return all(a.startswith(c) for c, a in zip(claimed, actual))


def _skills_block(report: str) -> Optional[str]:
    lines = report.splitlines()
    for index, line in enumerate(lines):
        if "skills loaded" not in line.lower():
            continue
        start = index + 1
        if re.search(r"skills loaded\W*$", line, re.IGNORECASE):
            # A bare heading may have its list after blank lines.
            while start < len(lines) and not lines[start].strip():
                start += 1
        block = [line]
        for following in lines[start:]:
            if not following.strip() or following.lstrip().startswith("#"):
                break
            block.append(following)
        return "\n".join(block)
    return None


def _skill_problems(report: str, skills: Sequence[str]) -> List[str]:
    block = _skills_block(report)
    if block is None:
        return ["no Skills loaded line"]
    lacking = []
    for skill in skills:
        name = PurePosixPath(skill).parent.name
        named = re.search(r"(?<![\w-])" + re.escape(name) + r"(?![\w-])", block)
        if skill not in block and not named:
            lacking.append(name)
    return [f"Skills loaded line lacks: {', '.join(lacking)}"] if lacking else []


def report_check(report: Optional[str], claimed: Sequence[str], actual: Sequence[str],
                 skills: Sequence[str]) -> CheckResult:
    if report is None:
        return CheckResult("report", FAIL, "report file missing")
    problems: List[str] = []
    if not _commits_match(claimed, actual):
        problems.append(
            f"status line commits {', '.join(claimed)} differ from the branch commits "
            + ", ".join(sha[:12] for sha in actual))
    if skills:
        problems += _skill_problems(report, skills)
    if problems:
        return CheckResult("report", FAIL, "; ".join(problems))
    return CheckResult("report", PASS, f"commits match; {len(skills)} skills named")


def failed_names(results: Sequence[CheckResult]) -> List[str]:
    return [result.name for result in results if result.status == FAIL]
