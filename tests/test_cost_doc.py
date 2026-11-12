"""Checks for docs/cost.md and its dataset docs/cost/2026-11-11-run.json (PL5)."""
from __future__ import annotations

import io
import json
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

RUN_JSON = ROOT / "docs" / "cost" / "2026-11-11-run.json"
COST_DOC = ROOT / "docs" / "cost.md"

TOKEN_KEYS = (
    "input_tokens",
    "output_tokens",
    "cache_creation_input_tokens",
    "cache_read_input_tokens",
)
EXEC_LABELS = [
    "A-T1", "A-T2", "A-T3", "A-T4", "A-T5", "B-T1", "B-T2", "B-T3", "B-T4",
    "R1", "C1", "C2", "C3", "R2", "R3",
]
VERIFY_LABELS = ["A-T3", "A-T5", "B-T1", "B-T2", "B-T3", "B-T4", "C1", "C2", "C3"]
BANNED_WORDS = [
    "game-changing", "revolutionary", "world-class", "cutting-edge", "seamless",
    "supercharge", "effortless", "blazing", "unleash", "unlock", "leverage",
    "delve", "elevate", "empower", "next-level",
]
DASHES = ("—", "–")
UUID_RE = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}")
BANNED_RE = re.compile(
    r"\b(" + "|".join(re.escape(word) for word in BANNED_WORDS) + r")\b",
    re.IGNORECASE,
)
RESULT_HEADINGS = {
    "5m": "## Results with 5-minute cache writes",
    "1h": "## Results with 1-hour cache writes",
}


def load_rows() -> list:
    return json.loads(RUN_JSON.read_text(encoding="utf-8"))


def doc_section(heading: str) -> list:
    """Lines of the doc under heading, up to the next level-2 heading or the end."""
    lines = COST_DOC.read_text(encoding="utf-8").splitlines()
    start = lines.index(heading)
    end = next(
        (i for i in range(start + 1, len(lines)) if lines[i].startswith("## ")),
        len(lines),
    )
    return lines[start + 1:end]


def mr_cost_report(cache_ttl: str) -> str:
    """Output of cost_estimate.main for the dataset file, as mr-cost prints it."""
    from cost_estimate import main

    stdout = io.StringIO()
    code = main([str(RUN_JSON), "--cache-ttl", cache_ttl], stdout=stdout, stderr=io.StringIO())
    if code != 0:
        raise AssertionError(f"mr-cost exited with {code}")
    return stdout.getvalue()


def _is_number(text: str) -> bool:
    try:
        float(text)
    except ValueError:
        return False
    return True


def group_table_rows(report: str) -> list:
    """Markdown rows for the group and total lines of a mr-cost report."""
    rows = []
    for line in report.splitlines():
        parts = line.split()
        if len(parts) == 5 and parts[1].isdigit() and all(_is_number(p) for p in parts[2:]):
            rows.append(
                f"| {parts[0]} | {parts[1]} | ${parts[2]} | ${parts[3]} | ${parts[4]} |"
            )
    return rows


class CostDocTest(unittest.TestCase):
    def test_tc1_rows_have_the_required_shape(self):
        # TC1: list of rows; label, agent_type, one resolved model, four non-negative int token keys;
        # the model family equals the model segment of agent_type.
        rows = load_rows()
        self.assertIsInstance(rows, list)
        for row in rows:
            label = row["label"]
            self.assertIsInstance(label, str)
            self.assertIsInstance(row["agent_type"], str, label)
            self.assertTrue(row["agent_type"].startswith("mr:"), label)
            models = row["resolved_models"]
            self.assertIsInstance(models, list, label)
            self.assertEqual(len(models), 1, label)
            self.assertIsInstance(models[0], str, label)
            for key in TOKEN_KEYS:
                value = row[key]
                self.assertIsInstance(value, int, f"{label} {key}")
                self.assertNotIsInstance(value, bool, f"{label} {key}")
                self.assertGreaterEqual(value, 0, f"{label} {key}")
            family = models[0].split("-")[1]
            segment = row["agent_type"].split(":", 1)[1].split("-")[1]
            self.assertEqual(family, segment, label)

    def test_tc2_exactly_fifteen_executors_in_order(self):
        # TC2: 15 mr:exec- rows in the spec order; A-T1 and R3 carry the logged token counts.
        rows = load_rows()
        exec_rows = [row for row in rows if row["agent_type"].startswith("mr:exec-")]
        self.assertEqual([row["label"] for row in exec_rows], EXEC_LABELS)
        by_label = {row["label"]: row for row in exec_rows}
        self.assertEqual(
            tuple(by_label["A-T1"][key] for key in TOKEN_KEYS),
            (42, 76888, 253994, 1055477),
        )
        self.assertEqual(
            tuple(by_label["R3"][key] for key in TOKEN_KEYS),
            (10, 2228, 28610, 149442),
        )

    def test_tc3_exactly_nine_verifiers(self):
        # TC3: exactly the nine mr:verify-sonnet-med rows, in the spec order.
        rows = load_rows()
        verify_rows = [row for row in rows if row["agent_type"] == "mr:verify-sonnet-med"]
        self.assertEqual([row["label"] for row in verify_rows], VERIFY_LABELS)

    def test_tc4_no_transcript_key_and_no_private_data(self):
        # TC4: no transcript key; no home paths and no session-id-shaped strings in the file.
        for row in load_rows():
            self.assertNotIn("transcript", row, row["label"])
        text = RUN_JSON.read_text(encoding="utf-8")
        self.assertNotIn("/Users/", text)
        self.assertNotIn("/home/", text)
        self.assertIsNone(UUID_RE.search(text))

    def test_tc5_haiku_executors_carry_the_stated_peak(self):
        # TC5: Haiku executor rows have peak 91105; no row above 100000; no "over 100K" report line.
        for row in load_rows():
            if row["agent_type"].startswith("mr:exec-haiku-"):
                self.assertEqual(row.get("peak_prompt_tokens"), 91105, row["label"])
            if "peak_prompt_tokens" in row:
                self.assertLessEqual(row["peak_prompt_tokens"], 100000, row["label"])
        report = mr_cost_report("5m")
        self.assertFalse(any("over 100K" in line for line in report.splitlines()))

    def test_tc6_report_rows_appear_in_both_result_sections(self):
        # TC6: every group and total line mr-cost prints for the file appears in the matching
        # "## Results with ..." section, for 5m and for 1h.
        for cache_ttl, heading in RESULT_HEADINGS.items():
            section = doc_section(heading)
            expected = group_table_rows(mr_cost_report(cache_ttl))
            self.assertTrue(expected, cache_ttl)
            for row in expected:
                self.assertIn(row, section, cache_ttl)

    def test_tc7_no_dashes_and_no_banned_words(self):
        # TC7: no en or em dash and no banned word in docs/cost.md.
        text = COST_DOC.read_text(encoding="utf-8")
        for dash in DASHES:
            self.assertNotIn(dash, text)
        match = BANNED_RE.search(text)
        self.assertIsNone(match, f"banned word: {match.group(0) if match else ''}")

    def test_tc8_agents_included_table_has_one_row_per_dataset_row(self):
        # TC8: "## Agents included" has one table row per dataset row after its header and separator.
        section = doc_section("## Agents included")
        header = section.index("| Label | Tier | Role |")
        table_rows = [line for line in section[header + 2:] if line.startswith("| ")]
        self.assertEqual(len(table_rows), len(load_rows()))

    def test_doc_has_no_session_id_path_or_marketplace_name(self):
        # Constraint: no session id, path or transcript content, and no bare marketplace name.
        text = COST_DOC.read_text(encoding="utf-8")
        self.assertNotIn("/Users/", text)
        self.assertNotIn("/home/", text)
        self.assertIsNone(UUID_RE.search(text))
        # Split literal: the naming test rejects the bare marketplace name in any source line.
        self.assertNotIn("claude-model-" "routing", text)


if __name__ == "__main__":
    unittest.main()
