"""Checks for docs/case-study.md and its dataset docs/case-study/2026-11-production-run.json (PL11)."""
from __future__ import annotations

import io
import json
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

CASE_JSON = ROOT / "docs" / "case-study" / "2026-11-production-run.json"
CASE_DOC = ROOT / "docs" / "case-study-monorepo.md"
COST_JSON = ROOT / "docs" / "cost" / "2026-11-11-run.json"

ROW_KEYS = [
    "label", "agent_type", "resolved_models", "agent_count", "input_tokens",
    "output_tokens", "cache_creation_input_tokens", "cache_read_input_tokens",
]
TOKEN_KEYS = ROW_KEYS[4:]
HEADINGS = [
    "## Headline numbers",
    "## The project",
    "## How the work was routed",
    "## Cost",
    "## What the same usage limit covers",
    "## Output",
    "## Review and quality",
    "## What did not go well",
    "## Method",
]
TITLE = "# Deep dive: model routing on a 530,000-line production monorepo"
HEADLINE_KEYS = [
    "routed_usd", "all_sonnet_usd", "all_opus_usd", "saving_vs_opus_percent",
    "work_per_limit_ratio", "extra_vs_sonnet_percent", "subagents",
    "executor_token_share_percent", "haiku_exec_percent_of_sonnet",
    "lines_added", "production_lines_added", "test_lines_added", "commits",
    "active_days", "test_calls_before", "test_calls_after", "lines_at_head",
    "verdicts", "sent_back_verdicts", "first_verdict_pass_groups", "task_groups",
    "code_and_test_lines_added",
]
COPIED = {
    "lines_added": "420,377", "production_lines_added": "124,812",
    "test_lines_added": "261,108", "commits": "221", "active_days": "5",
    "test_calls_before": "811", "test_calls_after": "8,025",
    "lines_at_head": "530,977", "verdicts": "179", "sent_back_verdicts": "79",
    "first_verdict_pass_groups": "45", "task_groups": "116",
    "code_and_test_lines_added": "385,920",
}
BANNED_WORDS = [
    "game-changing", "revolutionary", "world-class", "cutting-edge", "seamless",
    "supercharge", "effortless", "blazing", "unleash", "unlock", "leverage",
    "delve", "elevate", "empower", "next-level", "game-changer", "robust",
    "streamline", "harness", "tapestry",
]
BANNED_RE = re.compile(
    r"\b(" + "|".join(re.escape(w) for w in BANNED_WORDS) + r")\b", re.IGNORECASE
)
UUID_RE = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}")
HEX_RE = re.compile(r"(?<!\w)[0-9a-f]{7,40}(?!\w)")
PHASE_RE = re.compile(r"P0\d")


def load_rows() -> list:
    return json.loads(CASE_JSON.read_text(encoding="utf-8"))


def mr_cost_lines(path: Path) -> dict:
    """Group and total lines of the mr-cost report (5m) as {name: (agents, a, s, o)}."""
    from cost_estimate import main

    out = io.StringIO()
    code = main([str(path)], stdout=out, stderr=io.StringIO())
    if code != 0:
        raise AssertionError(f"mr-cost exited with {code}")
    result = {}
    for line in out.getvalue().splitlines():
        p = line.split()
        if len(p) == 5 and p[1].isdigit():
            try:
                result[p[0]] = (int(p[1]), float(p[2]), float(p[3]), float(p[4]))
            except ValueError:
                continue
    return result


def pct(x: float) -> str:
    return str(int(x * 100 + 0.5))


def money(v: float) -> str:
    return f"{v:,.2f}"


def headline_table() -> dict:
    lines = CASE_DOC.read_text(encoding="utf-8").splitlines()
    start = lines.index("## Headline numbers")
    table = {}
    header_seen = False
    for line in lines[start + 1:]:
        if line.startswith("## "):
            break
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if cells == ["Key", "Value"]:
            header_seen = True
            continue
        if not header_seen or set(cells[0]) <= set("-: "):
            continue
        table[cells[0].strip("`")] = cells[1]
    return table


class CaseStudyTest(unittest.TestCase):
    def test_tc1_dataset_shape(self):
        # TC1: 11 rows, keys in order, agent_count non-negative ints, 278 mr: agents.
        rows = load_rows()
        self.assertIsInstance(rows, list)
        self.assertEqual(len(rows), 11)
        for row in rows:
            keys = list(row)
            self.assertEqual(keys[:8], ROW_KEYS, row.get("label"))
            self.assertIn(keys[8:], ([], ["peak_prompt_tokens"]), row.get("label"))
            count = row["agent_count"]
            self.assertIsInstance(count, int)
            self.assertNotIsInstance(count, bool)
            self.assertGreaterEqual(count, 0)
            for key in TOKEN_KEYS:
                self.assertIsInstance(row[key], int, key)
        mr_rows = [r for r in rows if r["agent_type"].startswith("mr:")]
        self.assertEqual(sum(r["agent_count"] for r in mr_rows), 278)

    def test_tc2_dataset_is_priced(self):
        # TC2: total line within 0.10 of the expected routed, all-Sonnet and all-Opus values.
        total = mr_cost_lines(CASE_JSON)["total"]
        for got, want in zip(total[1:], (2105.04, 1766.48, 3532.96)):
            self.assertAlmostEqual(got, want, delta=0.10)

    def test_tc3_headline_table(self):
        # TC3: exactly the headline keys; cost-derived keys and subagents recomputed.
        table = headline_table()
        self.assertEqual(sorted(table), sorted(HEADLINE_KEYS))
        total = mr_cost_lines(CASE_JSON)["total"]
        a, c, b = total[1], total[2], total[3]
        want = {
            "routed_usd": money(a),
            "all_sonnet_usd": money(c),
            "all_opus_usd": money(b),
            "saving_vs_opus_percent": pct((b - a) / b),
            "work_per_limit_ratio": f"{b / a:.1f}",
            "extra_vs_sonnet_percent": pct((a - c) / c),
            "subagents": f"{sum(r['agent_count'] for r in load_rows() if r['agent_type'].startswith('mr:')):,}",
        }
        want.update(COPIED)
        for key, value in want.items():
            self.assertEqual(table[key], value, key)

    def test_tc4_haiku_and_executor_share(self):
        # TC4: haiku_exec_percent_of_sonnet and executor_token_share_percent recomputed.
        table = headline_table()
        exec_line = mr_cost_lines(COST_JSON)["exec"]
        self.assertEqual(table["haiku_exec_percent_of_sonnet"], pct(exec_line[1] / exec_line[2]))
        rows = [r for r in load_rows() if r["agent_type"].startswith("mr:")]
        tokens = lambda r: sum(r[k] for k in TOKEN_KEYS)  # noqa: E731
        execs = sum(tokens(r) for r in rows if r["agent_type"].startswith("mr:exec-"))
        self.assertEqual(table["executor_token_share_percent"], pct(execs / sum(map(tokens, rows))))

    def test_tc5_no_identifying_strings(self):
        # TC5: no home paths, UUIDs, commit-hash-like strings; no phase codes in the doc.
        for path in (CASE_JSON, CASE_DOC):
            text = path.read_text(encoding="utf-8")
            self.assertNotIn("/Users/", text, path.name)
            self.assertNotIn("/home/", text, path.name)
            self.assertIsNone(UUID_RE.search(text), path.name)
            for m in HEX_RE.finditer(text):
                self.assertIsNone(re.search(r"[a-f]", m.group(0)), f"{path.name}: {m.group(0)}")
        self.assertIsNone(PHASE_RE.search(CASE_DOC.read_text(encoding="utf-8")))

    def test_tc6_headings_in_order(self):
        # TC6: the title and the nine level-2 headings of the outline, in order.
        lines = CASE_DOC.read_text(encoding="utf-8").splitlines()
        self.assertEqual(lines[0], TITLE)
        self.assertEqual([l for l in lines if l.startswith("#")], [TITLE] + HEADINGS)

    def test_tc7_no_dashes_or_banned_words(self):
        # TC7: no em or en dash, none of the banned words.
        text = CASE_DOC.read_text(encoding="utf-8")
        self.assertNotIn("—", text)
        self.assertNotIn("–", text)
        self.assertIsNone(BANNED_RE.search(text))


if __name__ == "__main__":
    unittest.main()
