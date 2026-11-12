import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CASE_STUDY = "docs/case-study.md"
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
HEADLINE = "The right Claude for every step."
SUBHEAD = (
    "mr turns a Claude Code session into a team: Haiku scouts and builds, Sonnet takes the "
    "harder code, and Opus plans and reviews. Each agent starts with a fresh context, and a "
    "script checks every task before it merges."
)
FOOTNOTE = (
    "\u00b9 Re-priced estimate of subagent spend: the same tokens at Anthropic API list prices "
    "with 5-minute cache writes. Reading it as usage-limit headroom assumes your plan meters "
    "usage in proportion to list price; Anthropic does not publish how it meters."
)
OVERALL_SENTENCE = (
    "Across all {sessions} sessions, including those where executors stayed on Sonnet, "
    "subagent spend was {all_saving_vs_sonnet_percent}% below all-Sonnet and "
    "{all_saving_vs_opus_percent}% below all-Opus."
)
SINGLE_PROJECT_PHRASES = ("one project", "single project", "one production run", "a production run of")
OVERCLAIMS = ("most of the reading", "did most of the work")
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
        # TC8 (guard): no unfilled {PLACEHOLDER} remains in README.md.
        self.assertEqual(re.findall(r"\{[A-Z_]+\}", read("README.md")), [])

    def test_headline_numbers(self):
        # TC2: the README quotes the revision 3 numbers, read from the case-study table.
        readme = read("README.md")
        n = headline_numbers()
        for text in (
            n["projects"],
            n["tier_agents"],
            n["haiku_heavy_saving_vs_sonnet_percent"] + "%",
            n["haiku_scout_saving_vs_sonnet_percent"] + "%",
            n["context_ratio"] + "x",
            n["haiku_scouts"] + " of " + n["scouts"],
            n["opus_planners"],
            n["opus_verifiers"],
            n["haiku_executors"],
            n["agent_median_peak"],
            n["main_median_peak"],
            n["haiku_heavy_work_per_limit_vs_sonnet"] + "x",
            n["haiku_scout_token_share_percent"] + "%",
            n["transcript_projects"] + " projects with",
        ):
            self.assertTrue(text in readme, "missing: " + text)
        # The four stat callouts: the number, then its meaning.
        stats = (
            (
                n["projects"] + " projects, " + n["tier_agents"] + " agents",
                "Kotlin, TypeScript, Rust, Python, Swift, C#",
            ),
            (
                n["haiku_heavy_saving_vs_sonnet_percent"] + "%",
                "below all-Sonnet when Haiku scouts and builds\u00b9",
            ),
            (
                n["haiku_scout_saving_vs_sonnet_percent"] + "%",
                "cheaper evidence gathering with Haiku scouts than with Sonnet\u00b9",
            ),
            (n["context_ratio"] + "x", "smaller median context per agent than the main session"),
        )
        for number, meaning in stats:
            self.assertTrue(">" + number + "<" in readme, "missing callout number: " + number)
            self.assertTrue(meaning in readme, "missing: " + meaning)

    def test_roles_and_model_split(self):
        # TC2: the roles section names all four roles, scouting on Haiku as an agent count, and
        # the Opus planners and verifiers against the Haiku executors.
        readme = read("README.md")
        n = headline_numbers()
        for text in (
            "Scout",
            "Plan",
            "Exec",
            "Verify",
            n["haiku_scouts"] + " of " + n["scouts"] + " scouts",
            n["opus_planners"] + " Opus planners",
            n["opus_verifiers"] + " Opus verifiers",
            n["haiku_executors"] + " Haiku executors",
            n["agent_median_peak"] + " prompt tokens",
            n["main_median_peak"],
        ):
            self.assertTrue(text in readme, "missing: " + text)
        self.assertEqual(
            [phrase for phrase in OVERCLAIMS if phrase in readme.lower()], [], "overclaim"
        )

    def test_overall_sentence(self):
        # TC3: the all-sessions sentence appears once, with the study's numbers.
        sentence = OVERALL_SENTENCE.format(**headline_numbers())
        self.assertEqual(read("README.md").count(sentence), 1, sentence)

    def test_cost_table_rows(self):
        # TC3: the three-row cost table: all sessions, Haiku-heavy sessions, this repository's run.
        readme = read("README.md")
        n = headline_numbers()
        for text in (
            "$" + n["all_routed_usd"],
            "$" + n["all_sonnet_usd"],
            "$" + n["all_opus_usd"],
            "$" + n["haiku_heavy_routed_usd"],
            "$" + n["haiku_heavy_sonnet_usd"],
            "$" + n["haiku_heavy_opus_usd"],
            "$" + n["repo_run_routed_usd"],
            "$" + n["repo_run_sonnet_usd"],
            n["haiku_heavy_with_main_saving_vs_sonnet_percent"] + "%",
        ):
            self.assertTrue(text in readme, "missing: " + text)

    def test_cost_figures_in_chart_alt(self):
        # TC7: the cost chart's alt text states the three Haiku-heavy dollar values.
        readme = read("README.md")
        n = headline_numbers()
        alt = re.search(r'<img[^>]*cost-chart\.svg[^>]*>', readme)
        self.assertIsNotNone(alt)
        for key in ("haiku_heavy_routed_usd", "haiku_heavy_sonnet_usd", "haiku_heavy_opus_usd"):
            self.assertTrue("$" + n[key] in alt.group(0), "missing in alt: $" + n[key])

    def test_footnote(self):
        # TC4: the exact footnote sentence appears exactly once.
        self.assertEqual(read("README.md").count(FOOTNOTE), 1, "footnote must appear exactly once")

    def test_headline(self):
        # TC1: the H1 line, the headline and the subhead appear verbatim.
        readme = read("README.md")
        self.assertTrue(H1 in readme.splitlines(), "missing H1")
        self.assertTrue(HEADLINE in readme, "missing headline")
        self.assertTrue(SUBHEAD in readme, "missing subhead")

    def test_first_screen_order(self):
        # TC1: the first screen runs H1, hero image, headline, subhead, stats, then the install
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
            first(">" + n["haiku_heavy_saving_vs_sonnet_percent"] + "%<"),
            first("## Install the plugin"),
        ]
        self.assertEqual(order, sorted(order), "first screen out of order: " + str(order))
        self.assertLess(order[-1], 45)

    def test_no_single_project_claim(self):
        # TC5: the README never says or implies that mr was tested on one project.
        text = read("README.md").lower()
        self.assertEqual([p for p in SINGLE_PROJECT_PHRASES if p in text], [])

    def test_assets_referenced(self):
        # TC8 (guard): the README references both SVG assets, and both files exist.
        readme = read("README.md")
        for asset in ("docs/assets/hero.svg", "docs/assets/cost-chart.svg"):
            self.assertTrue(asset in readme, "missing: " + asset)
            self.assertTrue((ROOT / asset).is_file(), asset)

    def test_relative_links(self):
        # TC6: README links to docs/cost.md, docs/case-study.md, docs/case-study-monorepo.md,
        # CONTRIBUTING.md and LICENSE, and every relative link target exists in the repository.
        readme = read("README.md")
        for target in (
            "docs/cost.md",
            "docs/case-study.md",
            "docs/case-study-monorepo.md",
            "CONTRIBUTING.md",
            "LICENSE",
        ):
            self.assertTrue("](" + target + ")" in readme, "missing link: " + target)
        missing = []
        for target in LINK.findall(readme):
            if target.startswith(("http", "#")):
                continue
            if not (ROOT / target.split("#")[0]).exists():
                missing.append(target)
        self.assertEqual(missing, [])

    def test_no_dashes(self):
        # TC8 (guard): README.md contains no em dash (U+2014) and no en dash (U+2013).
        self.assertEqual(re.findall("[–—]", read("README.md")), [])

    def test_sections(self):
        # TC8 (guard): README.md has the required sections and mentions all four hook scripts.
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
        # TC8 (guard): the unmeasured "Usage limits on Pro and Max" paragraph is replaced by the ratio,
        # its footnote and the case-study link.
        readme = read("README.md")
        self.assertFalse(OLD_USAGE_PARAGRAPH in readme, "old usage paragraph still present")
        self.assertFalse("## Usage limits on Pro and Max" in lines_of(readme), "old heading still present")

    def test_no_banned_words(self):
        # TC8 (guard): README.md uses none of the banned words, case-insensitively.
        text = read("README.md").lower()
        self.assertEqual([word for word in BANNED_WORDS if word in text], [])


if __name__ == "__main__":
    unittest.main()
