"""Checks for the committed cross-project data in docs/case-study/ (PL14).

Four files: cross-project-usage.json, context-peaks.json, projects.json and
routing-logs.json. Every cross-project number in the study and the README is
recomputed from them here. The tests build no sensitive string literally.
"""
from __future__ import annotations

import json
import re
import statistics
import sys
import unittest
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import cost_estimate  # noqa: E402

DATA = ROOT / "docs" / "case-study"
USAGE_FILE = DATA / "cross-project-usage.json"
PEAKS_FILE = DATA / "context-peaks.json"
PROJECTS_FILE = DATA / "projects.json"
LOGS_FILE = DATA / "routing-logs.json"
ALL_FILES = [USAGE_FILE, PEAKS_FILE, PROJECTS_FILE, LOGS_FILE]

ROW_KEYS = {
    "label", "session", "agent_type", "resolved_models", "agent_count",
    "input_tokens", "output_tokens", "cache_creation_input_tokens",
    "cache_read_input_tokens", "peak_prompt_tokens",
}
LABEL_RE = re.compile(r"^(P(0[1-9]|1[01])|T0[12])$")
SESSION_RE = re.compile(r"^S(0[1-9]|[1-3][0-9]|4[0-2])$")
TIER_RE = re.compile(r"^mr:(scout|plan|exec|verify)-(haiku|sonnet|opus)-(low|med|high|xhigh)$")
UUID_RE = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")
HEX_RE = re.compile(r"(?<![0-9A-Za-z])(?=[0-9]*[a-f])[0-9a-f]{7,40}(?![0-9A-Za-z])")
HOME_MARKERS = ["/" + "Users" + "/", "/" + "home" + "/", "\\" + "Users" + "\\"]

ALL_LABELS = (
    ["P%02d" % n for n in range(1, 12)] + ["T01", "T02"] + ["L%02d" % n for n in range(1, 8)]
)

# S6 2: label -> (agents, as run, all Sonnet, all Opus)
PER_LABEL = {
    "P01": (176, 234.29, 272.89, 545.80),
    "P02": (155, 80.36, 134.87, 269.73),
    "P03": (174, 104.54, 119.16, 238.32),
    "P04": (163, 106.33, 133.98, 267.95),
    "P05": (183, 167.54, 174.15, 348.28),
    "P06": (22, 12.52, 16.25, 32.49),
    "P07": (365, 341.45, 639.26, 1278.51),
    "P08": (281, 1932.68, 1638.38, 3276.75),
    "P09": (105, 167.31, 143.16, 286.32),
    "P10": (32, 20.19, 25.73, 51.44),
    "P11": (111, 104.05, 155.99, 311.96),
    "T01": (16, 0.75, 0.89, 1.76),
    "T02": (2, 0.01, 0.24, 0.48),
}

# S6 1: label -> (mr sessions, all sessions, first day, last day)
SESSIONS = {
    "P01": (9, 15, "2026-10-27", "2026-10-31"),
    "P02": (8, 31, "2026-10-27", "2026-10-30"),
    "P03": (6, 8, "2026-10-28", "2026-11-05"),
    "P04": (5, 6, "2026-10-28", "2026-11-12"),
    "P05": (2, 2, "2026-10-27", "2026-10-28"),
    "P06": (2, 5, "2026-10-29", "2026-10-30"),
    "P07": (2, 2, "2026-11-11", "2026-11-12"),
    "P08": (1, 4, "2026-11-04", "2026-11-12"),
    "P09": (1, 1, "2026-10-30", "2026-10-30"),
    "P10": (1, 2, "2026-11-12", "2026-11-12"),
    "P11": (1, 6, "2026-10-29", "2026-10-30"),
    "T01": (2, 2, "2026-10-28", "2026-10-28"),
    "T02": (2, 2, "2026-11-11", "2026-11-11"),
}

KINDS = {"repo", "multi-repo folder", "test run", "log-only repo"}
PROJECT_KEYS = {
    "label", "kind", "sessions_mr", "sessions_all", "tier_agents",
    "first_day", "last_day", "compacted_sessions", "segment_sessions",
}

# S6 6: label -> (parsed rows, FIX, REPLAN, escalation, verifier tier rows); None where S6 has "-"
LOG_ROWS = {
    "P01": (5, 1, 2, 0, 2),
    "P02": None,
    "P03": None,
    "P04": (64, 2, 5, 1, 42),
    "P05": (64, 12, 4, 0, 45),
    "P06": (75, 15, 15, 0, 35),
    "P07": (79, 17, 4, 2, 44),
    "P08": (0, None, None, None, None),
    "P09": (10, 6, 1, 2, 5),
    "P10": (20, 2, 1, 0, 13),
    "P11": (81, 25, 8, 11, 49),
    "T01": None,
    "T02": None,
    "L01": (35, 8, 0, 1, 19),
    "L02": (45, 7, 4, 2, 29),
    "L03": (2, 0, 0, 0, 0),
    "L04": (6, 3, 1, 0, 4),
    "L05": (1, 0, 0, 0, 0),
    "L06": (1, 0, 0, 0, 0),
    "L07": (11, 3, 0, 0, 6),
}
LOG_KEYS = {"label", "parsed_rows", "fix_rows", "replan_rows", "escalation_rows", "verifier_rows"}


def load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def strings_in(value):
    """Every string in a JSON value, keys included."""
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for key, item in value.items():
            yield key
            yield from strings_in(item)
    elif isinstance(value, list):
        for item in value:
            yield from strings_in(item)


def tier_rows(rows):
    return [r for r in rows if r["agent_type"].startswith("mr:")]


def main_rows(rows):
    return [r for r in rows if r["agent_type"] == "main"]


def totals(rows):
    est = cost_estimate.estimate(rows)
    return est["total"]


def role_of(row):
    return cost_estimate.group_of(row["agent_type"])


def family_of(row):
    return row["resolved_models"][0].split("-")[1]


def is_long_haiku(row):
    price = cost_estimate.price_for(row["resolved_models"][0], row["peak_prompt_tokens"])
    return price is cost_estimate.HAIKU_55_LONG


def session_segments(rows):
    """Segment letter per session by the S6 4 rule; sessions come from the main rows."""
    by_session = defaultdict(list)
    for row in tier_rows(rows):
        by_session[row["session"]].append(row)
    out = {}
    for session in {r["session"] for r in main_rows(rows)}:
        out[session] = segment_of(by_session.get(session, []))
    return out


def segment_of(rows):
    execs = [r for r in rows if role_of(r) == "exec"]
    scouts = [r for r in rows if role_of(r) == "scout"]
    if not execs:
        return "none"

    def share(group, family):
        count = sum(r["agent_count"] for r in group)
        return sum(r["agent_count"] for r in group if family_of(r) == family) / count

    if share(execs, "sonnet") > 0.5:
        return "B"
    if share(execs, "haiku") > 0.5 and (not scouts or share(scouts, "haiku") > 0.5):
        return "A"
    return "C"


class UsageFileTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rows = load(USAGE_FILE)

    def test_tc1_row_schema_and_values(self):
        """TC1: ten keys, label, session, agent type and model formats."""
        self.assertTrue(self.rows)
        for row in self.rows:
            self.assertEqual(set(row), ROW_KEYS)
            self.assertRegex(row["label"], LABEL_RE)
            self.assertRegex(row["session"], SESSION_RE)
            if row["agent_type"] not in ("main", "non-tier"):
                self.assertRegex(row["agent_type"], TIER_RE)
            self.assertEqual(len(row["resolved_models"]), 1)
            self.assertTrue(row["resolved_models"][0].startswith("claude-"))
            for key in ROW_KEYS - {"label", "session", "agent_type", "resolved_models"}:
                self.assertIsInstance(row[key], int)

    def test_tc1_main_rows_one_per_session_and_model(self):
        """TC1: main rows count one agent on the first row of a session and none on a second."""
        mains = main_rows(self.rows)
        self.assertEqual(len({r["session"] for r in mains}), 42)
        for session in {r["session"] for r in mains}:
            counts = [r["agent_count"] for r in mains if r["session"] == session]
            self.assertEqual(sorted(counts)[-1], 1)
            self.assertEqual(sum(counts), 1)

    def test_tc2_totals(self):
        """TC2: tier rows price to the published totals; main rows to the frozen snapshot."""
        tier = totals(tier_rows(self.rows))
        for key, expected in (("actual", 3272.02), ("sonnet", 3454.92), ("opus", 6909.83)):
            self.assertAlmostEqual(tier[key], expected, delta=0.50, msg=key)
        main = totals(main_rows(self.rows))
        for key, expected in (("actual", 1122.38), ("sonnet", 694.56), ("opus", 1389.12)):
            self.assertAlmostEqual(main[key], expected, delta=0.05, msg=key)

    def test_tc3_per_label(self):
        """TC3: each label's tier rows price to its S6 2 values."""
        for label, (agents, actual, sonnet, opus) in PER_LABEL.items():
            rows = [r for r in tier_rows(self.rows) if r["label"] == label]
            got = totals(rows)
            self.assertEqual(got["agents"], agents, label)
            self.assertAlmostEqual(got["actual"], actual, delta=0.10, msg=label)
            self.assertAlmostEqual(got["sonnet"], sonnet, delta=0.10, msg=label)
            self.assertAlmostEqual(got["opus"], opus, delta=0.10, msg=label)

    def test_tc4_haiku_roles(self):
        """TC4: Haiku scouts and Haiku executors price to the published figures."""
        expected = {
            "scout": (139, 13.79, 174.98, 349.95),
            "exec": (591, 62.08, 766.29, 1532.58),
        }
        for role, (agents, actual, sonnet, opus) in expected.items():
            rows = [r for r in tier_rows(self.rows) if role_of(r) == role and family_of(r) == "haiku"]
            got = totals(rows)
            self.assertEqual(got["agents"], agents, role)
            self.assertAlmostEqual(got["actual"], actual, delta=0.10, msg=role)
            self.assertAlmostEqual(got["sonnet"], sonnet, delta=0.10, msg=role)
            self.assertAlmostEqual(got["opus"], opus, delta=0.10, msg=role)

    def test_tc5_segments(self):
        """TC5: the S6 4 session segments reproduce sessions, agents and cost."""
        segments = session_segments(self.rows)
        counts = defaultdict(int)
        for letter in segments.values():
            counts[letter] += 1
        self.assertEqual(dict(counts), {"A": 24, "B": 7, "C": 3, "none": 8})
        for letter, agents, subs, with_main in (
            ("A", 1055, (835.46, 1329.18, 2658.33), (1433.52, 1660.39, 3320.79)),
            ("B", 630, (2362.73, 2034.94, 4069.88), None),
        ):
            sessions = {s for s, seg in segments.items() if seg == letter}
            tier = [r for r in tier_rows(self.rows) if r["session"] in sessions]
            got = totals(tier)
            self.assertEqual(got["agents"], agents, letter)
            for key, expected in zip(("actual", "sonnet", "opus"), subs):
                self.assertAlmostEqual(got[key], expected, delta=0.50, msg=letter + key)
            if with_main:
                mains = [r for r in main_rows(self.rows) if r["session"] in sessions]
                both = totals(tier + mains)
                for key, expected in zip(("actual", "sonnet", "opus"), with_main):
                    self.assertAlmostEqual(both[key], expected, delta=0.05, msg=letter + key)

    def test_tc6_counts(self):
        """TC6: agent counts by role, model family and tier."""
        tier = tier_rows(self.rows)

        def count(role=None, family=None):
            return sum(
                r["agent_count"] for r in tier
                if (role is None or role_of(r) == role) and (family is None or family_of(r) == family)
            )

        self.assertEqual(count(), 1785)
        self.assertEqual(
            {role: count(role) for role in ("exec", "verify", "scout", "plan")},
            {"exec": 958, "verify": 524, "scout": 237, "plan": 66},
        )
        self.assertEqual((count(family="haiku"), count("exec", "haiku"), count("scout", "haiku")), (730, 591, 139))
        by_name = defaultdict(int)
        for row in tier:
            by_name[row["agent_type"].rsplit(":", 1)[-1].rsplit("-", 1)[0]] += row["agent_count"]
        self.assertEqual((by_name["verify-opus"], by_name["plan-opus"]), (236, 57))
        non_tier = sum(r["agent_count"] for r in self.rows if r["agent_type"] == "non-tier")
        self.assertEqual(non_tier, 53)


class ContextPeaksTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.peaks = load(PEAKS_FILE)
        cls.rows = load(USAGE_FILE)

    def peaks_of(self, role=None):
        return [p for r, _f, p in self.peaks["agents"] if role is None or r == role]

    def test_tc7_shape(self):
        """TC7: 1,785 agent entries and 42 main entries, sorted, with no ids."""
        self.assertEqual(set(self.peaks), {"agents", "main"})
        self.assertEqual(len(self.peaks["agents"]), 1785)
        self.assertEqual(len(self.peaks["main"]), 42)
        self.assertEqual(self.peaks["agents"], sorted(self.peaks["agents"]))
        self.assertEqual(self.peaks["main"], sorted(self.peaks["main"]))
        for role, family, peak in self.peaks["agents"]:
            self.assertIn(role, ("scout", "plan", "exec", "verify"))
            self.assertIn(family, ("haiku", "sonnet", "opus"))
            self.assertIsInstance(peak, int)

    def test_tc7_medians(self):
        """TC7: medians by role and for the main sessions, and the main maximum."""
        for role, expected in (
            (None, 89877), ("scout", 89307), ("exec", 89394), ("verify", 105298), ("plan", 374604),
        ):
            self.assertAlmostEqual(statistics.median(self.peaks_of(role)), expected, delta=0.5, msg=str(role))
        self.assertAlmostEqual(statistics.median(self.peaks["main"]), 374470, delta=0.5)
        self.assertEqual(max(self.peaks["main"]), 1340726)

    def test_tc7_haiku_long_prompts_match_the_usage_rows(self):
        """TC7: Haiku peaks over 100K here equal the long Haiku tier rows in the usage file."""
        entries = sum(1 for _r, f, p in self.peaks["agents"] if f == "haiku" and p > 100000)
        long_tier = sum(r["agent_count"] for r in tier_rows(self.rows) if is_long_haiku(r))
        self.assertEqual(entries, long_tier)
        self.assertEqual(entries, 70)

    def test_tc7_long_haiku_rows_include_non_tier_subagents(self):
        """TC7: the 103 long Haiku rows of mr-cost are the 70 tier agents plus non-tier subagents."""
        long_all = sum(r["agent_count"] for r in self.rows if r["agent_type"] != "main" and is_long_haiku(r))
        self.assertEqual(long_all, 103)


class ProjectsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.projects = load(PROJECTS_FILE)
        cls.rows = load(USAGE_FILE)

    def test_tc8_labels_and_kinds(self):
        """TC8: 20 labels, 18 that are not test runs, valid kinds and keys."""
        self.assertEqual([p["label"] for p in self.projects], ALL_LABELS)
        for project in self.projects:
            self.assertEqual(set(project), PROJECT_KEYS)
            self.assertIn(project["kind"], KINDS)
        self.assertEqual(sum(1 for p in self.projects if p["kind"] != "test run"), 18)
        log_only = {p["label"] for p in self.projects if p["kind"] == "log-only repo"}
        self.assertEqual(log_only, {"L%02d" % n for n in range(1, 8)})
        for project in self.projects:
            self.assertNotIn("stack", project, project["label"])

    def test_tc8_compaction_and_segments(self):
        """TC8: 11 compacted sessions; segment counts per label add up to 24, 7, 3 and 8."""
        self.assertEqual(sum(p["compacted_sessions"] for p in self.projects), 11)
        pooled = defaultdict(int)
        for project in self.projects:
            seg = project["segment_sessions"]
            self.assertEqual(set(seg), {"A", "B", "C", "none"})
            self.assertEqual(sum(seg.values()), project["sessions_mr"], project["label"])
            for key, value in seg.items():
                pooled[key] += value
        self.assertEqual(dict(pooled), {"A": 24, "B": 7, "C": 3, "none": 8})

    def test_tc8_reach_matches_s6_and_the_usage_rows(self):
        """TC8: sessions, agents and day range per label match S6 1 and the usage file."""
        by_label = {p["label"]: p for p in self.projects}
        for label, (mr, total, first, last) in SESSIONS.items():
            project = by_label[label]
            self.assertEqual((project["sessions_mr"], project["sessions_all"]), (mr, total), label)
            self.assertEqual((project["first_day"], project["last_day"]), (first, last), label)
            agents = sum(r["agent_count"] for r in tier_rows(self.rows) if r["label"] == label)
            self.assertEqual(project["tier_agents"], agents, label)
        self.assertEqual(sum(p["sessions_mr"] for p in self.projects), 42)
        self.assertEqual(sum(p["tier_agents"] for p in self.projects), 1785)
        for label in ALL_LABELS:
            if label.startswith("L"):
                self.assertEqual(by_label[label]["sessions_mr"], 0)
                self.assertEqual(by_label[label]["tier_agents"], 0)

    def test_tc8_segments_match_the_usage_rows(self):
        """TC8: per-label segment counts agree with the segments computed from the usage file."""
        segments = session_segments(self.rows)
        label_of = {r["session"]: r["label"] for r in self.rows}
        for project in self.projects:
            want = {"A": 0, "B": 0, "C": 0, "none": 0}
            for session, letter in segments.items():
                if label_of[session] == project["label"]:
                    want[letter] += 1
            self.assertEqual(project["segment_sessions"], want, project["label"])


class RoutingLogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.logs = load(LOGS_FILE)

    def test_tc9_pooled(self):
        """TC9: pooled parsed rows and rows with no FIX, REPLAN or escalation."""
        pooled = self.logs["pooled"]
        self.assertEqual(pooled["parsed_rows"], 497)
        self.assertEqual(pooled["clean_rows"], 352)
        self.assertEqual(pooled["fix_rows"], 101)
        self.assertEqual(pooled["replan_rows"], 45)
        self.assertEqual(pooled["escalation_rows"], 19)
        self.assertEqual(pooled["repos"], 14)

    def test_tc9_per_label_rows(self):
        """TC9: per-label counts equal the S6 6 tables, with null where S6 has a dash."""
        self.assertEqual(set(self.logs), {"labels", "pooled"})
        got = {entry["label"]: entry for entry in self.logs["labels"]}
        self.assertEqual(list(got), list(LOG_ROWS))
        for label, expected in LOG_ROWS.items():
            entry = got[label]
            self.assertEqual(set(entry), LOG_KEYS)
            values = [entry[k] for k in ("parsed_rows", "fix_rows", "replan_rows", "escalation_rows", "verifier_rows")]
            self.assertEqual(values, [None] * 5 if expected is None else list(expected), label)


class AnonymityTests(unittest.TestCase):
    def test_tc1_no_paths_uuids_or_hashes(self):
        """TC1: no home path, UUID-shaped value or hex run in any string of the four files."""
        for path in ALL_FILES:
            for text in strings_in(load(path)):
                for marker in HOME_MARKERS:
                    self.assertNotIn(marker, text, path.name)
                self.assertIsNone(UUID_RE.search(text), path.name)
                self.assertIsNone(HEX_RE.search(text), path.name)

    def test_tc1_files_are_compact_and_small(self):
        """TC1: one JSON value per file, each under 120 KB, all four under 400 KB."""
        sizes = []
        for path in ALL_FILES:
            raw = path.read_bytes()
            sizes.append(len(raw))
            self.assertLess(len(raw), 120 * 1024, path.name)
            self.assertEqual(raw.count(b"\n"), 1 if raw.endswith(b"\n") else 0, path.name)
        self.assertLess(sum(sizes), 400 * 1024)


if __name__ == "__main__":
    unittest.main()
