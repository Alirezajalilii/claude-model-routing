from __future__ import annotations

import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from cost_estimate import (  # noqa: E402
    HAIKU_55_LONG,
    PRICES,
    Price,
    estimate,
    format_report,
    group_of,
    main,
    price_for,
    row_cost,
)
import cost_estimate  # noqa: E402  (new symbols are read as attributes, so the module imports before they exist)

HEADER = "mr-cost: estimate at Anthropic API list prices as of 2026-11-12, USD, 5m cache writes"
EXEC_HAIKU_ROW = {
    "agent_type": "mr:exec-haiku-high",
    "resolved_models": ["claude-haiku-5-5"],
    "output_tokens": 1000000,
    "peak_prompt_tokens": 50000,
}
VERIFY_SONNET_ROW = {
    "agent_type": "mr:verify-sonnet-med",
    "resolved_models": ["claude-sonnet-5-5"],
    "output_tokens": 1000000,
}
ONE_OF_EACH = {
    "input_tokens": 1000000,
    "output_tokens": 1000000,
    "cache_creation_input_tokens": 1000000,
    "cache_read_input_tokens": 1000000,
}


def run_main(argv: list, stdin_text: str = "") -> tuple:
    out, err = io.StringIO(), io.StringIO()
    code = main(argv, stdin=io.StringIO(stdin_text), stdout=out, stderr=err)
    return code, out.getvalue(), err.getvalue()


def write_rows(directory: str, rows: object) -> str:
    path = os.path.join(directory, "rows.json")
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(rows, handle)
    return path


class PriceForTest(unittest.TestCase):
    def test_tc1_haiku_55_short_prompt_rate(self) -> None:
        expected = Price(0.10, 0.125, 0.20, 0.01, 0.50)
        self.assertEqual(price_for("claude-haiku-5-5-20261001", 50000), expected)
        self.assertEqual(price_for("claude-haiku-5-5-20261001", 100000), expected)

    def test_tc2_haiku_55_long_prompt_rate(self) -> None:
        self.assertEqual(price_for("claude-haiku-5-5", 100001), Price(0.50, 0.625, 1.00, 0.05, 2.50))
        self.assertIs(price_for("claude-haiku-5-5", 100001), HAIKU_55_LONG)

    def test_tc2_only_haiku_55_has_a_long_prompt_rate(self) -> None:
        self.assertEqual(price_for("claude-haiku-4-5", 150000), Price(1, 1.25, 2, 0.10, 5))

    def test_tc3_longest_prefix_wins(self) -> None:
        self.assertEqual(price_for("claude-opus-5-5[1m]"), Price(4, 5, 8, 0.20, 20))
        self.assertEqual(price_for("claude-opus-5-20260101"), Price(5, 6.25, 10, 0.50, 25))

    def test_tc4_dated_older_model_and_unknown_model(self) -> None:
        self.assertEqual(price_for("claude-sonnet-4-5-20250929"), Price(3, 3.75, 6, 0.30, 15))
        self.assertIsNone(price_for("gpt-5"))

    def test_price_table_has_every_listed_prefix(self) -> None:
        self.assertEqual(
            sorted(PRICES),
            sorted([
                "claude-opus-5-5", "claude-opus-5", "claude-opus-4-8", "claude-opus-4-7",
                "claude-opus-4-6", "claude-opus-4-5", "claude-sonnet-5-5", "claude-sonnet-5",
                "claude-sonnet-4-6", "claude-sonnet-4-5", "claude-haiku-5-5", "claude-haiku-4-5",
            ]),
        )


class RowCostTest(unittest.TestCase):
    def test_tc5_one_million_of_each_kind_at_5m(self) -> None:
        cost = row_cost(ONE_OF_EACH, PRICES["claude-sonnet-5-5"], "5m")
        self.assertAlmostEqual(cost, 14.60, places=6)

    def test_tc5_one_million_of_each_kind_at_1h(self) -> None:
        cost = row_cost(ONE_OF_EACH, PRICES["claude-sonnet-5-5"], "1h")
        self.assertAlmostEqual(cost, 16.10, places=6)

    def test_missing_token_keys_count_as_zero(self) -> None:
        cost = row_cost({"output_tokens": 1000000}, PRICES["claude-sonnet-5-5"], "5m")
        self.assertAlmostEqual(cost, 10.00, places=6)


class GroupOfTest(unittest.TestCase):
    def test_tc11_group_names(self) -> None:
        self.assertEqual(group_of("mr:exec-haiku-high"), "exec")
        self.assertEqual(group_of("exec-haiku-low"), "exec")
        self.assertEqual(group_of("general-purpose"), "other")
        self.assertEqual(group_of("?"), "other")

    def test_main_group_order(self) -> None:
        # TC5: the main session is its own group, and the report orders exec, main, other.
        self.assertEqual(group_of("main"), "main")
        main_row = {"agent_type": "main", "resolved_models": ["claude-sonnet-5-5"], "output_tokens": 1000000}
        other_row = {
            "agent_type": "general-purpose",
            "resolved_models": ["claude-sonnet-5-5"],
            "output_tokens": 1000000,
        }
        result = estimate([other_row, main_row, EXEC_HAIKU_ROW])
        self.assertEqual(list(result["groups"]), ["exec", "main", "other"])
        report_lines = format_report(result, "5m").splitlines()
        self.assertEqual([line.split()[0] for line in report_lines[2:5]], ["exec", "main", "other"])


class UsableModelsTest(unittest.TestCase):
    def test_usable_models(self) -> None:
        # TC1: placeholders are left out; a row with only placeholders or no models has none usable.
        usable = cost_estimate.usable_models
        self.assertEqual(usable({"resolved_models": ["<synthetic>", "claude-sonnet-5-5"]}), ["claude-sonnet-5-5"])
        self.assertEqual(usable({"resolved_models": ["<synthetic>"]}), [])
        self.assertEqual(usable({}), [])


class AgentCountTest(unittest.TestCase):
    def test_agent_count_sums(self) -> None:
        # TC3: agent_count counts in its group and in the total; the cost is the same as without it.
        plain = estimate([EXEC_HAIKU_ROW])
        aggregated = estimate([dict(EXEC_HAIKU_ROW, agent_count=59)])
        self.assertEqual(aggregated["groups"]["exec"]["agents"], 59)
        self.assertEqual(aggregated["total"]["agents"], 59)
        for kind in ("actual", "sonnet", "opus"):
            self.assertAlmostEqual(aggregated["total"][kind], plain["total"][kind], places=6)
        zero = estimate([dict(EXEC_HAIKU_ROW, agent_count=0)])
        self.assertEqual(zero["total"]["agents"], 0)
        self.assertAlmostEqual(zero["total"]["actual"], 0.50, places=6)

    def test_agent_count_invalid(self) -> None:
        # TC4: a count that is not a non-negative integer is an input error (exit 2).
        for value in (-1, "3", 2.5, True):
            with self.subTest(value=value):
                row = dict(VERIFY_SONNET_ROW, agent_count=value)
                code, out, err = run_main(["-"], json.dumps([row]))
                self.assertEqual(code, 2)
                self.assertTrue(err.startswith("mr-cost: "), err)


class EstimateTest(unittest.TestCase):
    def test_tc6_two_priced_rows(self) -> None:
        result = estimate([EXEC_HAIKU_ROW, VERIFY_SONNET_ROW])
        self.assertEqual(list(result["groups"]), ["exec", "verify"])
        exec_group = result["groups"]["exec"]
        self.assertEqual(exec_group["agents"], 1)
        self.assertAlmostEqual(exec_group["actual"], 0.50, places=6)
        self.assertAlmostEqual(exec_group["sonnet"], 10.00, places=6)
        self.assertAlmostEqual(exec_group["opus"], 20.00, places=6)
        verify_group = result["groups"]["verify"]
        self.assertEqual(verify_group["agents"], 1)
        self.assertAlmostEqual(verify_group["actual"], 10.00, places=6)
        total = result["total"]
        self.assertEqual(total["agents"], 2)
        self.assertAlmostEqual(total["actual"], 10.50, places=6)
        self.assertAlmostEqual(total["sonnet"], 20.00, places=6)
        self.assertAlmostEqual(total["opus"], 40.00, places=6)

    def test_tc7_unpriced_rows_are_excluded_and_listed(self) -> None:
        empty = {"agent_type": "mr:exec-haiku-low", "resolved_models": [], "output_tokens": 5}
        two_models = {
            "agent_type": "mr:plan-opus-high",
            "resolved_models": ["claude-sonnet-5-5", "claude-haiku-5-5"],
            "output_tokens": 5,
        }
        result = estimate([EXEC_HAIKU_ROW, empty, two_models])
        self.assertEqual(result["unpriced"], 2)
        self.assertEqual(result["unpriced_models"], ["claude-haiku-5-5", "claude-sonnet-5-5"])
        self.assertEqual(result["total"]["agents"], 1)
        self.assertAlmostEqual(result["total"]["actual"], 0.50, places=6)
        self.assertIn(
            "unpriced: 2 agent(s); models: claude-haiku-5-5, claude-sonnet-5-5",
            format_report(result, "5m").splitlines(),
        )

    def test_unknown_single_model_is_unpriced(self) -> None:
        row = {"agent_type": "mr:exec-haiku-high", "resolved_models": ["gpt-5"], "output_tokens": 1}
        result = estimate([row])
        self.assertEqual(result["unpriced"], 1)
        self.assertEqual(result["unpriced_models"], ["gpt-5"])
        self.assertEqual(result["groups"], {})

    def test_tc1_synthetic_placeholder_is_ignored_when_pricing(self) -> None:
        # Claude Code writes "<synthetic>" on messages it generates itself; the row ran on one model.
        row = {
            "agent_type": "mr:verify-sonnet-med",
            "resolved_models": ["<synthetic>", "claude-sonnet-5-5"],
            "output_tokens": 1000000,
        }
        result = estimate([row])
        self.assertEqual(result["unpriced"], 0)
        self.assertEqual(result["unpriced_models"], [])
        self.assertEqual(result["groups"]["verify"]["agents"], 1)
        self.assertAlmostEqual(result["groups"]["verify"]["actual"], 10.00, places=6)
        self.assertAlmostEqual(result["total"]["sonnet"], 10.00, places=6)

    def test_tc2_only_placeholder_stays_unpriced(self) -> None:
        row = {"agent_type": "mr:exec-haiku-low", "resolved_models": ["<synthetic>"], "output_tokens": 5}
        result = estimate([row])
        self.assertEqual(result["unpriced"], 1)
        self.assertEqual(result["unpriced_models"], ["<synthetic>"])
        self.assertEqual(result["groups"], {})

    def test_tc3_placeholder_is_left_out_of_unpriced_models_when_real_models_exist(self) -> None:
        row = {
            "agent_type": "mr:plan-opus-high",
            "resolved_models": ["<synthetic>", "claude-sonnet-5-5", "claude-haiku-5-5"],
            "output_tokens": 5,
        }
        result = estimate([row])
        self.assertEqual(result["unpriced"], 1)
        self.assertEqual(result["unpriced_models"], ["claude-haiku-5-5", "claude-sonnet-5-5"])

    def test_other_angle_bracket_placeholder_is_ignored_too(self) -> None:
        row = {
            "agent_type": "mr:exec-haiku-high",
            "resolved_models": ["<unknown>", "claude-haiku-5-5"],
            "output_tokens": 1000000,
        }
        result = estimate([row])
        self.assertEqual(result["unpriced"], 0)
        self.assertAlmostEqual(result["groups"]["exec"]["actual"], 0.50, places=6)

    def test_no_recorded_model_reports_none_recorded(self) -> None:
        row = {"agent_type": "mr:exec-haiku-high", "resolved_models": [], "output_tokens": 1}
        report = format_report(estimate([row]), "5m")
        self.assertIn("unpriced: 1 agent(s); models: none recorded", report.splitlines())

    def test_tc12_haiku_long_rate_is_counted(self) -> None:
        row = dict(EXEC_HAIKU_ROW, peak_prompt_tokens=150000)
        result = estimate([row])
        self.assertEqual(result["haiku_long"], 1)
        self.assertAlmostEqual(result["groups"]["exec"]["actual"], 2.50, places=6)
        report = format_report(result, "5m")
        self.assertIn(
            "haiku agents over 100K prompt tokens, priced at the higher rate: 1",
            report.splitlines(),
        )

    def test_long_rate_haiku_row_counts_its_agent_count(self) -> None:
        # Aggregated row: 59 agents at the long rate add 59, not 1, to the long-rate count.
        row = dict(EXEC_HAIKU_ROW, peak_prompt_tokens=150000, agent_count=59)
        result = estimate([row])
        self.assertEqual(result["haiku_long"], 59)
        self.assertEqual(result["groups"]["exec"]["agents"], 59)
        self.assertIn(
            "haiku agents over 100K prompt tokens, priced at the higher rate: 59",
            format_report(result, "5m").splitlines(),
        )

    def test_long_rate_haiku_row_without_agent_count_adds_one(self) -> None:
        row = dict(EXEC_HAIKU_ROW, peak_prompt_tokens=150000)
        self.assertEqual(estimate([row])["haiku_long"], 1)

    def test_long_rate_count_sums_agent_counts_of_several_rows(self) -> None:
        long_rows = [
            dict(EXEC_HAIKU_ROW, peak_prompt_tokens=150000, agent_count=59),
            dict(EXEC_HAIKU_ROW, peak_prompt_tokens=120000, agent_count=4),
            dict(EXEC_HAIKU_ROW, peak_prompt_tokens=50000, agent_count=10),
        ]
        self.assertEqual(estimate(long_rows)["haiku_long"], 63)

    def test_report_without_long_rows_has_no_long_rate_line(self) -> None:
        report = format_report(estimate([EXEC_HAIKU_ROW]), "5m")
        self.assertNotIn("priced at the higher rate", report)


class FormatReportTest(unittest.TestCase):
    def test_header_group_total_and_footer_lines(self) -> None:
        report = format_report(estimate([EXEC_HAIKU_ROW, VERIFY_SONNET_ROW]), "5m")
        lines = report.splitlines()
        self.assertEqual(lines[0], HEADER)
        self.assertEqual(lines[1], "group  agents  actual  at-sonnet-5.5  at-opus-5.5")
        self.assertEqual(lines[2], "exec  1  0.50  10.00  20.00")
        self.assertEqual(lines[3], "verify  1  10.00  10.00  20.00")
        self.assertEqual(lines[4], "total  2  10.50  20.00  40.00")
        self.assertEqual(
            lines[-1],
            "Same-token re-pricing: a run on another model would use a different number of tokens.",
        )
        self.assertEqual(len(lines), 6)


class MainTest(unittest.TestCase):
    def test_tc8_file_argument_prints_total(self) -> None:
        rows = [EXEC_HAIKU_ROW, VERIFY_SONNET_ROW]
        with tempfile.TemporaryDirectory() as directory:
            path = write_rows(directory, rows)
            code, out, err = run_main([path])
        self.assertEqual(code, 0, err)
        self.assertEqual(err, "")
        self.assertEqual(out.splitlines()[0], HEADER)
        self.assertIn(["total", "2", "10.50", "20.00", "40.00"], [line.split() for line in out.splitlines()])

    def test_tc8_stdin_gives_the_same_output(self) -> None:
        rows = [EXEC_HAIKU_ROW, VERIFY_SONNET_ROW]
        with tempfile.TemporaryDirectory() as directory:
            path = write_rows(directory, rows)
            _, from_file, _ = run_main([path])
        code, from_stdin, err = run_main(["-"], json.dumps(rows))
        self.assertEqual(code, 0, err)
        self.assertEqual(from_stdin, from_file)

    def test_tc9_json_object_is_rejected(self) -> None:
        code, out, err = run_main(["-"], json.dumps({"agent_type": "x"}))
        self.assertEqual(code, 2)
        self.assertTrue(err.startswith("mr-cost: "), err)

    def test_tc9_missing_file_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            missing = os.path.join(directory, "missing.json")
            code, out, err = run_main([missing])
        self.assertEqual(code, 2)
        self.assertTrue(err.startswith("mr-cost: "), err)

    def test_tc9_string_token_value_is_rejected(self) -> None:
        row = dict(VERIFY_SONNET_ROW, output_tokens="12")
        code, out, err = run_main(["-"], json.dumps([row]))
        self.assertEqual(code, 2)
        self.assertTrue(err.startswith("mr-cost: "), err)

    def test_row_that_is_not_an_object_is_rejected(self) -> None:
        code, out, err = run_main(["-"], json.dumps([1]))
        self.assertEqual(code, 2)
        self.assertTrue(err.startswith("mr-cost: "), err)

    def test_invalid_json_is_rejected(self) -> None:
        code, out, err = run_main(["-"], "[{")
        self.assertEqual(code, 2)
        self.assertTrue(err.startswith("mr-cost: "), err)

    def test_tc13_one_hour_cache_writes(self) -> None:
        row = {
            "agent_type": "mr:verify-sonnet-med",
            "resolved_models": ["claude-sonnet-5-5"],
            "cache_creation_input_tokens": 1000000,
        }
        code, out, err = run_main(["--cache-ttl", "1h", "-"], json.dumps([row]))
        self.assertEqual(code, 0, err)
        lines = out.splitlines()
        self.assertTrue(lines[0].endswith("1h cache writes"), lines[0])
        self.assertIn(["total", "1", "4.00", "4.00", "8.00"], [line.split() for line in lines])


if __name__ == "__main__":
    unittest.main()
