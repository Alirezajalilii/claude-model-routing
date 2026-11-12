"""Checks for docs/case-study.md, the cross-project study (PL15), and the moved deep dive.

Every Headline value is recomputed here from the committed data in docs/case-study/
and docs/cost/2026-11-11-run.json. The tests build no sensitive string literally.
"""
from __future__ import annotations

import json
import re
import statistics
import sys
import unittest
from collections import defaultdict
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import cost_estimate  # noqa: E402

DATA = ROOT / "docs" / "case-study"
STUDY = ROOT / "docs" / "case-study.md"
DEEP_DIVE = ROOT / "docs" / "case-study-monorepo.md"
REPO_RUN = ROOT / "docs" / "cost" / "2026-11-11-run.json"

H1 = "# mr in practice: 18 projects, 1,785 agents"
DEEP_DIVE_H1 = "# Deep dive: model routing on a 530,000-line production monorepo"
HEADINGS = [
    "## Headline numbers",
    "## Where it ran",
    "## Which model did what",
    "## Cost",
    "## What the same usage limit covers",
    "## Separate agents, smaller contexts",
    "## Review and quality",
    "## What did not go well",
    "## The large production run",
    "## Method",
]
KEYS = [
    "projects", "transcript_projects", "repos_with_logs", "sessions", "tier_agents",
    "first_day", "last_day",
    "haiku_agents", "haiku_scouts", "scouts", "haiku_scout_token_share_percent",
    "haiku_executors", "executors", "opus_verifiers", "opus_planners",
    "all_routed_usd", "all_sonnet_usd", "all_opus_usd",
    "all_saving_vs_sonnet_percent", "all_saving_vs_opus_percent",
    "haiku_heavy_sessions", "haiku_heavy_agents", "haiku_heavy_routed_usd",
    "haiku_heavy_sonnet_usd", "haiku_heavy_opus_usd",
    "haiku_heavy_saving_vs_sonnet_percent", "haiku_heavy_saving_vs_opus_percent",
    "haiku_heavy_work_per_limit_vs_sonnet", "haiku_heavy_with_main_saving_vs_sonnet_percent",
    "haiku_scout_saving_vs_sonnet_percent", "haiku_exec_saving_vs_sonnet_percent",
    "repo_run_routed_usd", "repo_run_sonnet_usd", "repo_run_saving_vs_sonnet_percent",
    "agent_median_peak", "main_median_peak", "context_ratio", "compacted_sessions",
]
LANGUAGES = ("Kotlin", "TypeScript", "Rust", "Python", "Swift", "C#", "SQL")
POOLED_LIST = "Kotlin, TypeScript, Rust, Python, Swift, C#, SQL"
BANNED_WORDS = [
    "game-changing", "game-changer", "revolutionary", "world-class", "cutting-edge",
    "seamless", "supercharge", "effortless", "blazing", "unleash", "unlock",
    "leverage", "delve", "elevate", "empower", "next-level", "robust",
    "streamline", "harness", "tapestry",
]
BANNED_RE = re.compile(r"\b(" + "|".join(re.escape(w) for w in BANNED_WORDS) + r")\b", re.IGNORECASE)
LABEL_RE = re.compile(r"\b[PTL]\d\d\b")
ALLOWED_LABELS = (
    {"P%02d" % n for n in range(1, 12)} | {"T01", "T02"} | {"L%02d" % n for n in range(1, 8)}
)
UUID_RE = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}")
HEX_RE = re.compile(r"(?<![0-9A-Za-z])(?=[0-9]*[a-f])[0-9a-f]{7,40}(?![0-9A-Za-z])")
HOME = "/" + "Users" + "/"


def load(name: str):
    return json.loads((DATA / name).read_text(encoding="utf-8"))


def half_up(value) -> int:
    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def one_decimal(value) -> str:
    return str(Decimal(str(value)).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))


def money(value) -> str:
    return "{:,.2f}".format(Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def count(value) -> str:
    return "{:,}".format(int(value))


def saving(routed, other) -> int:
    return half_up(100 * (1 - routed / other))


def tier_rows(rows):
    return [r for r in rows if r["agent_type"].startswith("mr:")]


def role_of(row) -> str:
    return cost_estimate.group_of(row["agent_type"])


def family_of(row) -> str:
    return row["resolved_models"][0].split("-")[1]


def tier_name(row) -> str:
    return row["agent_type"].rsplit(":", 1)[-1].rsplit("-", 1)[0]


def agents(rows) -> int:
    return sum(r["agent_count"] for r in rows)


def tokens(rows) -> int:
    keys = ("input_tokens", "output_tokens", "cache_creation_input_tokens", "cache_read_input_tokens")
    return sum(r[k] for r in rows for k in keys)


def segment_of(rows) -> str:
    """Session segment: A Haiku-heavy, B Sonnet-heavy executors, C other, none without executors."""
    execs = [r for r in rows if role_of(r) == "exec"]
    scouts = [r for r in rows if role_of(r) == "scout"]
    if not execs:
        return "none"

    def share(group, family):
        return agents([r for r in group if family_of(r) == family]) / agents(group)

    if share(execs, "sonnet") > 0.5:
        return "B"
    if share(execs, "haiku") > 0.5 and (not scouts or share(scouts, "haiku") > 0.5):
        return "A"
    return "C"


def haiku_heavy_sessions(rows) -> set:
    by_session = defaultdict(list)
    for row in tier_rows(rows):
        by_session[row["session"]].append(row)
    mains = {r["session"] for r in rows if r["agent_type"] == "main"}
    return {s for s in mains if segment_of(by_session.get(s, [])) == "A"}


def share_on_haiku(rows, role) -> int:
    group = [r for r in tier_rows(rows) if role_of(r) == role]
    return half_up(100 * tokens([r for r in group if family_of(r) == "haiku"]) / tokens(group))


def haiku_role_saving(rows, role) -> int:
    got = cost_estimate.estimate(
        [r for r in tier_rows(rows) if role_of(r) == role and family_of(r) == "haiku"]
    )["total"]
    return saving(got["actual"], got["sonnet"])


def reach_values(rows, projects, logs) -> dict:
    tier = tier_rows(rows)
    days = [p["first_day"] for p in projects if p["first_day"]]
    last = [p["last_day"] for p in projects if p["last_day"]]
    return {
        "projects": count(sum(1 for p in projects if p["kind"] != "test run")),
        "transcript_projects": count(sum(1 for p in projects if re.fullmatch(r"P\d\d", p["label"]))),
        "repos_with_logs": count(sum(1 for e in logs["labels"] if e["parsed_rows"] is not None)),
        "sessions": count(sum(p["sessions_mr"] for p in projects)),
        "tier_agents": count(agents(tier)),
        "first_day": min(days),
        "last_day": max(last),
    }


def mix_values(rows) -> dict:
    tier = tier_rows(rows)
    scouts = [r for r in tier if role_of(r) == "scout"]
    execs = [r for r in tier if role_of(r) == "exec"]
    return {
        "haiku_agents": count(agents([r for r in tier if family_of(r) == "haiku"])),
        "haiku_scouts": count(agents([r for r in scouts if family_of(r) == "haiku"])),
        "scouts": count(agents(scouts)),
        "haiku_scout_token_share_percent": str(share_on_haiku(rows, "scout")),
        "haiku_executors": count(agents([r for r in execs if family_of(r) == "haiku"])),
        "executors": count(agents(execs)),
        "opus_verifiers": count(agents([r for r in tier if tier_name(r) == "verify-opus"])),
        "opus_planners": count(agents([r for r in tier if tier_name(r) == "plan-opus"])),
    }


def cost_values(rows) -> dict:
    tier = tier_rows(rows)
    allt = cost_estimate.estimate(tier)["total"]
    sessions = haiku_heavy_sessions(rows)
    seg = tier_rows([r for r in rows if r["session"] in sessions])
    heavy = cost_estimate.estimate(seg)["total"]
    with_main = cost_estimate.estimate(seg + [r for r in rows if r["session"] in sessions and r["agent_type"] == "main"])["total"]
    run = cost_estimate.estimate(json.loads(REPO_RUN.read_text(encoding="utf-8")))["total"]
    return {
        "all_routed_usd": money(allt["actual"]),
        "all_sonnet_usd": money(allt["sonnet"]),
        "all_opus_usd": money(allt["opus"]),
        "all_saving_vs_sonnet_percent": str(saving(allt["actual"], allt["sonnet"])),
        "all_saving_vs_opus_percent": str(saving(allt["actual"], allt["opus"])),
        "haiku_heavy_sessions": count(len(sessions)),
        "haiku_heavy_agents": count(heavy["agents"]),
        "haiku_heavy_routed_usd": money(heavy["actual"]),
        "haiku_heavy_sonnet_usd": money(heavy["sonnet"]),
        "haiku_heavy_opus_usd": money(heavy["opus"]),
        "haiku_heavy_saving_vs_sonnet_percent": str(saving(heavy["actual"], heavy["sonnet"])),
        "haiku_heavy_saving_vs_opus_percent": str(saving(heavy["actual"], heavy["opus"])),
        "haiku_heavy_work_per_limit_vs_sonnet": one_decimal(heavy["sonnet"] / heavy["actual"]),
        "haiku_heavy_with_main_saving_vs_sonnet_percent": str(saving(with_main["actual"], with_main["sonnet"])),
        "repo_run_routed_usd": money(run["actual"]),
        "repo_run_sonnet_usd": money(run["sonnet"]),
        "repo_run_saving_vs_sonnet_percent": str(saving(run["actual"], run["sonnet"])),
    }


def context_values(rows, projects) -> dict:
    peaks = load("context-peaks.json")
    agent_median = statistics.median(p for _r, _f, p in peaks["agents"])
    main_median = statistics.median(peaks["main"])
    return {
        "haiku_scout_saving_vs_sonnet_percent": str(haiku_role_saving(rows, "scout")),
        "haiku_exec_saving_vs_sonnet_percent": str(haiku_role_saving(rows, "exec")),
        "agent_median_peak": count(half_up(agent_median)),
        "main_median_peak": count(half_up(main_median)),
        "context_ratio": one_decimal(main_median / agent_median),
        "compacted_sessions": count(sum(p["compacted_sessions"] for p in projects)),
    }


def expected_headline() -> dict:
    rows = load("cross-project-usage.json")
    projects = load("projects.json")
    logs = load("routing-logs.json")
    out = {}
    for part in (reach_values(rows, projects, logs), mix_values(rows), cost_values(rows),
                 context_values(rows, projects)):
        out.update(part)
    return out


def table_after(lines, heading):
    """Rows (list of cell lists) of the first table under a heading, header and rule excluded."""
    start = lines.index(heading)
    rows = []
    for line in lines[start + 1:]:
        if line.startswith("## "):
            break
        if line.startswith("|"):
            rows.append([c.strip().strip("`") for c in line.strip().strip("|").split("|")])
    return [r for r in rows[1:] if not set("".join(r)) <= set("-: ")]


def study_text() -> str:
    return STUDY.read_text(encoding="utf-8")


class StudyStructureTests(unittest.TestCase):
    def test_headings(self):
        """TC1: the H1 and the ten `##` headings of the outline, in order."""
        lines = study_text().splitlines()
        self.assertEqual(lines[0], H1)
        self.assertEqual([ln for ln in lines if ln.startswith("## ")], HEADINGS)

    def test_links(self):
        """TC3: the study links the deep dive; the deep dive has the new H1 and links back."""
        self.assertIn("(case-study-monorepo.md)", study_text())
        self.assertTrue(DEEP_DIVE.is_file(), "docs/case-study-monorepo.md is missing")
        deep = DEEP_DIVE.read_text(encoding="utf-8").splitlines()
        self.assertEqual(deep[0], DEEP_DIVE_H1)
        self.assertIn("(case-study.md)", "\n".join(deep[:4]))
        self.assertIn("Part of the cross-project study.", "\n".join(deep[:4]))


class StudyNumbersTests(unittest.TestCase):
    def test_headline_values(self):
        """TC2: exactly the listed keys, each equal to the recomputation from the data."""
        table = table_after(study_text().splitlines(), "## Headline numbers")
        self.assertEqual([r[0] for r in table], KEYS)
        expected = expected_headline()
        self.assertEqual(set(expected), set(KEYS))
        for key, value in table:
            self.assertEqual(value, expected[key], key)

    def test_cost_table(self):
        """TC2: the Cost table has three rows whose values equal the Headline values."""
        table = table_after(study_text().splitlines(), "## Cost")
        self.assertEqual(len(table), 3)
        e = expected_headline()
        run = cost_estimate.estimate(json.loads(REPO_RUN.read_text(encoding="utf-8")))["total"]
        for row, (routed, sonnet, opus, vs_s, vs_o) in zip(table, (
            (e["all_routed_usd"], e["all_sonnet_usd"], e["all_opus_usd"],
             e["all_saving_vs_sonnet_percent"], e["all_saving_vs_opus_percent"]),
            (e["haiku_heavy_routed_usd"], e["haiku_heavy_sonnet_usd"], e["haiku_heavy_opus_usd"],
             e["haiku_heavy_saving_vs_sonnet_percent"], e["haiku_heavy_saving_vs_opus_percent"]),
            (e["repo_run_routed_usd"], e["repo_run_sonnet_usd"], money(run["opus"]),
             e["repo_run_saving_vs_sonnet_percent"], str(saving(run["actual"], run["opus"]))),
        )):
            text = " | ".join(row)
            for want in ("$" + routed, "$" + sonnet, "$" + opus, vs_s + "%", vs_o + "%"):
                self.assertIn(want, text)

    def test_prose_uses_the_headline_values(self):
        """TC2: the key figures in the prose match the Headline table."""
        text = study_text()
        e = expected_headline()
        for phrase in (
            "%s%% of scout tokens" % e["haiku_scout_token_share_percent"],
            "%sx" % e["haiku_heavy_work_per_limit_vs_sonnet"],
            "%s of %s sessions" % (e["compacted_sessions"], e["sessions"]),
            e["agent_median_peak"], e["main_median_peak"],
            "%s%% below all-Sonnet" % e["haiku_heavy_with_main_saving_vs_sonnet_percent"],
        ):
            self.assertIn(phrase, text)


class StudyAnonymityTests(unittest.TestCase):
    def test_anonymity(self):
        """TC4 (guard): only the published labels, no home path, UUID or hash-shaped string."""
        text = study_text()
        self.assertFalse(set(LABEL_RE.findall(text)) - ALLOWED_LABELS)
        self.assertNotIn(HOME, text)
        self.assertIsNone(UUID_RE.search(text))
        self.assertIsNone(HEX_RE.search(text))

    def test_no_per_project_stack(self):
        """TC4: the label table has four columns, and the languages appear only as one pooled list."""
        text = study_text()
        table = table_after(text.splitlines(), "## Where it ran")
        self.assertTrue(table)
        self.assertTrue(all(len(r) == 4 for r in table))
        self.assertEqual(sum(1 for ln in text.splitlines() if POOLED_LIST in ln), 1)
        stripped = text.replace(POOLED_LIST, "")
        for language in LANGUAGES:
            self.assertNotRegex(stripped, r"\b" + re.escape(language) + r"\b")

    def test_no_dashes_or_banned_words(self):
        """TC6: no em or en dash and none of the banned words."""
        text = study_text()
        self.assertNotIn("—", text)
        self.assertNotIn("–", text)
        self.assertIsNone(BANNED_RE.search(text))


if __name__ == "__main__":
    unittest.main()
