import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CASE_STUDY = "docs/case-study-monorepo.md"
LINK = re.compile(r"\]\(([^)]+)\)")
BANNED_WORDS = (
    "game-changing",
    "revolutionary",
    "world-class",
    "cutting-edge",
    "seamless",
    "supercharge",
    "effortless",
    "blazing",
    "unleash",
    "unlock",
    "leverage",
    "delve",
    "elevate",
    "empower",
    "next-level",
)
HOOK_SCRIPTS = ("session_context.py", "dispatch_guard.py", "stall_watch.py", "routing_audit.py")
H1 = "# mr: model routing for Claude Code"
HEADLINE = "Opus plans and reviews. Cheaper models write the code."
SUBHEAD = (
    "mr is a Claude Code plugin that sends each task to the cheapest model that can pass its "
    "tests, and sends the risky ones to Opus for review."
)
FOOTNOTE = (
    "¹ Re-priced estimate: the same tokens at Anthropic API list prices with 5-minute cache "
    "writes. Reading it as usage-limit headroom assumes your plan meters usage in proportion to "
    "list price; Anthropic does not publish how it meters."
)
OLD_USAGE_PARAGRAPH = "I have not measured how much longer a session lasts"


def read(name):
    return (ROOT / name).read_text(encoding="utf-8")


def lines_of(text):
    return text.splitlines()


def headline_numbers():
    """Key to value from the `## Headline numbers` table of docs/case-study.md."""
    lines = read(CASE_STUDY).splitlines()
    start = lines.index("## Headline numbers")
    table = {}
    for line in lines[start + 1:]:
        if line.startswith("## "):
            break
        if not line.startswith("|"):
            continue
        key, value = (cell.strip() for cell in line.strip().strip("|").split("|")[:2])
        if key not in ("Key",) and not set(key) <= set("-: "):
            table[key.strip("`")] = value
    return table


class ReadmeCopyTest(unittest.TestCase):
    def test_placeholders_filled(self):
        # TC8: no unfilled {PLACEHOLDER} remains in README.md.
        self.assertEqual(re.findall(r"\{[A-Z_]+\}", read("README.md")), [])

    def test_headline_numbers(self):
        # TC1: the README quotes the case-study numbers, read from its Headline numbers table.
        readme = read("README.md")
        n = headline_numbers()
        for text in (
            n["saving_vs_opus_percent"] + "%",
            n["work_per_limit_ratio"] + "x",
            n["extra_vs_sonnet_percent"] + "%",
            n["haiku_exec_percent_of_sonnet"] + "%",
            n["executor_token_share_percent"] + "%",
            n["code_and_test_lines_added"],
            n["sent_back_verdicts"],
        ):
            self.assertTrue(text in readme, "missing: " + text)
        # The four stat callouts: the number, then its meaning.
        stats = (
            (n["saving_vs_opus_percent"] + "%", "less than running every agent on Opus\u00b9"),
            (n["work_per_limit_ratio"] + "x", "the work from the same usage limit\u00b9"),
            (
                n["code_and_test_lines_added"],
                "lines of production code and tests added in " + n["active_days"] + " active days",
            ),
            (n["sent_back_verdicts"], "times reviewers sent work back before merge"),
        )
        for number, meaning in stats:
            self.assertTrue(">" + number + "<" in readme, "missing callout number: " + number)
            self.assertTrue(meaning in readme, "missing: " + meaning)

    def test_cost_figures_in_chart_alt(self):
        # TC1: the cost chart's alt text states the three dollar values.
        readme = read("README.md")
        n = headline_numbers()
        alt = re.search(r'<img[^>]*cost-chart\.svg[^>]*>', readme)
        self.assertIsNotNone(alt)
        for key in ("routed_usd", "all_sonnet_usd", "all_opus_usd"):
            self.assertTrue("$" + n[key] in alt.group(0), "missing in alt: $" + n[key])

    def test_footnote(self):
        # TC2: the exact footnote sentence appears exactly once.
        self.assertEqual(read("README.md").count(FOOTNOTE), 1, "footnote must appear exactly once")

    def test_headline(self):
        # TC3: the H1 line, the headline and the subhead appear verbatim.
        readme = read("README.md")
        self.assertTrue(H1 in readme.splitlines(), "missing H1")
        self.assertTrue(HEADLINE in readme, "missing headline")
        self.assertTrue(SUBHEAD in readme, "missing subhead")

    def test_first_screen_order(self):
        # TC3: the first screen runs H1, hero image, headline, subhead, stats, then the install
        # section starts within the first 45 lines.
        lines = read("README.md").splitlines()
        n = headline_numbers()

        def first(needle):
            return next((i for i, line in enumerate(lines) if needle in line), 10**6)

        order = [
            first(H1),
            first("docs/assets/hero.svg"),
            first(HEADLINE),
            first(SUBHEAD),
            first(">" + n["code_and_test_lines_added"] + "<"),
            first("## Install the plugin"),
        ]
        self.assertEqual(order, sorted(order), "first screen out of order: " + str(order))
        self.assertLess(order[-1], 45)

    def test_assets_referenced(self):
        # TC4: the README references both SVG assets, and both files exist.
        readme = read("README.md")
        for asset in ("docs/assets/hero.svg", "docs/assets/cost-chart.svg"):
            self.assertTrue(asset in readme, "missing: " + asset)
            self.assertTrue((ROOT / asset).is_file(), asset)

    def test_relative_links(self):
        # TC5: README links to docs/cost.md, docs/case-study.md, CONTRIBUTING.md and LICENSE,
        # and every relative link target exists in the repository.
        readme = read("README.md")
        for target in ("docs/cost.md", "docs/case-study.md", "CONTRIBUTING.md", "LICENSE"):
            self.assertTrue("](" + target + ")" in readme, "missing link: " + target)
        missing = []
        for target in LINK.findall(readme):
            if target.startswith(("http", "#")):
                continue
            if not (ROOT / target.split("#")[0]).exists():
                missing.append(target)
        self.assertEqual(missing, [])

    def test_no_dashes(self):
        # TC8: README.md contains no em dash (U+2014) and no en dash (U+2013).
        self.assertEqual(re.findall("[–—]", read("README.md")), [])

    def test_sections(self):
        # TC6: README.md has the required sections and mentions all four hook scripts.
        readme = read("README.md")
        lines = readme.splitlines()
        for heading in (
            "## Install the plugin",
            "## Update the plugin",
            "## Uninstall",
            "## Requirements",
            "## What runs on your machine",
        ):
            self.assertTrue(heading in lines, "missing heading: " + heading)
        for script in HOOK_SCRIPTS:
            self.assertTrue(script in readme, "missing: " + script)

    def test_old_usage_paragraph_gone(self):
        # TC1: the unmeasured "Usage limits on Pro and Max" paragraph is replaced by the ratio,
        # its footnote and the case-study link.
        readme = read("README.md")
        self.assertFalse(OLD_USAGE_PARAGRAPH in readme, "old usage paragraph still present")
        self.assertFalse("## Usage limits on Pro and Max" in lines_of(readme), "old heading still present")

    def test_no_banned_words(self):
        # TC8: README.md uses none of the banned words, case-insensitively.
        text = read("README.md").lower()
        self.assertEqual([word for word in BANNED_WORDS if word in text], [])


if __name__ == "__main__":
    unittest.main()
