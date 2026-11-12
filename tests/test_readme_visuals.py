"""Checks that the README tells its story in visuals first (PL19).

The four data charts and the Mermaid workflow diagram sit where each section starts, every
chart image carries alt text with its key numbers (recomputed here with the data functions of
scripts/render_charts.py), and the prose above the install section and in the selling
sections stays well below its size before this change.
"""
from __future__ import annotations

import json
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import render_charts as rc  # noqa: E402

CHARTS = ("chart-cost.svg", "chart-model-mix.svg", "chart-context.svg", "chart-projects.svg")
LEADS = (
    ("## What it costs", "chart-cost.svg"),
    ("## The right model for each step", "chart-model-mix.svg"),
    ("## A fresh context for every stage", "chart-context.svg"),
    ("## Proof across 11 projects", "chart-projects.svg"),
)
CHART_WIDTH = "640"
FLOW_WORDS = ("haiku", "sonnet", "opus", "mr-gate", "merge", "fast lane", "tests")
# Prose words above `## Install the plugin` plus in the selling sections (`## Four agents` up to
# `## What runs on your machine`) before PL19, counted by prose_words() below.
PROSE_BEFORE = 1229
PROSE_MAX_SHARE = 0.7
IMG_TAG = re.compile(r"<img\b[^>]*>")
MD_IMAGE = re.compile(r"!\[([^\]]*)\]\(([^)\s]+)[^)]*\)")
ATTR = re.compile(r'([\w-]+)="([^"]*)"')


def readme():
    return (ROOT / "README.md").read_text(encoding="utf-8")


def images(text):
    """Every image in the README as a dict with src, alt and width (width may be empty)."""
    found = []
    for tag in IMG_TAG.findall(text):
        attrs = dict(ATTR.findall(tag))
        found.append({"src": attrs.get("src", ""), "alt": attrs.get("alt", ""), "width": attrs.get("width", "")})
    for alt, src in MD_IMAGE.findall(text):
        found.append({"src": src, "alt": alt, "width": ""})
    return found


def chart_image(text, name):
    matches = [img for img in images(text) if img["src"].endswith("docs/assets/" + name)]
    return matches[0] if matches else None


def mermaid_blocks(text):
    return re.findall(r"```mermaid\n(.*?)```", text, flags=re.DOTALL)


def load_data():
    def load(parts):
        return json.loads(ROOT.joinpath(*parts).read_text(encoding="utf-8"))

    usage, peaks, repo = load(rc.USAGE_FILE), load(rc.PEAKS_FILE), load(rc.REPO_RUN_FILE)
    return {
        "cost": rc.cost_scenarios(usage, repo),
        "mix": rc.model_mix(usage),
        "context": dict(rc.context_medians(peaks)),
        "projects": rc.project_savings(usage),
    }


def section_lines(lines, heading):
    start = lines.index(heading)
    end = next((i for i in range(start + 1, len(lines)) if lines[i].startswith("## ")), len(lines))
    return lines[start + 1:end]


def prose_words(text):
    """Words outside fenced code, table rows and HTML tag lines, with links and images reduced to their text."""
    kept, fenced = [], False
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("```"):
            fenced = not fenced
        elif not fenced and not stripped.startswith(("|", "<")):
            stripped = MD_IMAGE.sub("", stripped)
            kept.append(re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", stripped))
    return kept


def count_words(lines):
    return sum(len(re.findall(r"[A-Za-z0-9$%][^\s]*", line)) for line in lines)


class ReadmeVisualsTest(unittest.TestCase):
    def test_charts_embedded(self):
        # TC1: all four charts are embedded as images, and the old cost chart is not referenced.
        text = readme()
        for name in CHARTS:
            self.assertIsNotNone(chart_image(text, name), "chart not embedded: " + name)
        self.assertNotIn("cost-chart.svg", text)

    def test_alt_numbers(self):
        # TC2: each chart image's alt text holds the key numbers recomputed from the data functions.
        text, data = readme(), load_data()
        alts = {name: (chart_image(text, name) or {"alt": ""})["alt"] for name in CHARTS}
        haiku_heavy = data["cost"][1]
        for value in haiku_heavy[1:]:
            self.assertIn(rc.money(value), alts["chart-cost.svg"])
        mix = data["mix"]
        for number in (mix["scout"]["haiku"], mix["exec"]["haiku"], mix["plan"]["opus"], mix["verify"]["opus"]):
            self.assertRegex(alts["chart-model-mix.svg"], r"\b" + str(number) + r"\b")
        for label in ("exec", "main"):
            value = data["context"][label]
            forms = ("%dK" % rc.half_up(value / 1000), "{:,}".format(value))
            self.assertTrue(any(f in alts["chart-context.svg"] for f in forms), (label, forms))
        savings = [row[1] for row in data["projects"]]
        for value in (min(savings), max(savings)):
            self.assertIn(rc.percent(value), alts["chart-projects.svg"])

    def test_alt_text_and_width_for_phones(self):
        # TC2 (brief): the cost alt says each group has its own all-Opus baseline and every chart
        # image has alt text. The width check moved to test_chart_width_640 (PL21 TC6).
        text = readme()
        self.assertIn("own all-Opus cost", chart_image(text, "chart-cost.svg")["alt"] if chart_image(text, "chart-cost.svg") else "")
        for name in CHARTS:
            image = chart_image(text, name)
            self.assertIsNotNone(image, name)
            self.assertTrue(image["alt"].strip(), "empty alt: " + name)

    def test_chart_width_640(self):
        # TC6 (PL21): each chart image is shown at its native 640 px; GitHub's max-width: 100% shrinks
        # it to the column on a phone, so the 22 unit text stays near 14 px.
        text = readme()
        for name in CHARTS:
            image = chart_image(text, name)
            self.assertIsNotNone(image, name)
            self.assertEqual(image["width"], CHART_WIDTH, "width of " + name)

    def test_mermaid(self):
        # TC3: a Mermaid flowchart of the workflow; no digit, em dash or en dash in any Mermaid block.
        blocks = mermaid_blocks(readme())
        self.assertTrue(blocks, "no mermaid block")
        self.assertTrue(
            any(b.strip().splitlines()[0].startswith("flowchart") for b in blocks if b.strip()),
            "no flowchart block",
        )
        for block in blocks:
            self.assertIsNone(re.search("[0-9—–]", block), "digit or dash in a mermaid block")
        flow = "\n".join(blocks).lower()
        for word in FLOW_WORDS:
            self.assertIn(word, flow, "flowchart lacks: " + word)

    def test_old_chart_removed(self):
        # TC4: the old cost chart file is gone.
        self.assertFalse((ROOT / "docs" / "assets" / "cost-chart.svg").exists())

    def test_sections_lead_with_a_visual(self):
        # Each selling section opens with its visual before any prose: the chart image, or for
        # the workflow section the Mermaid block.
        lines = readme().splitlines()
        for heading, chart in LEADS:
            self.assertIn(heading, lines, "missing section: " + heading)
            body = [line for line in section_lines(lines, heading) if line.strip()]
            first = "\n".join(body[:3])
            self.assertIn("docs/assets/" + chart, first, heading)
        agents = [line for line in section_lines(lines, "## Four agents, four jobs") if line.strip()]
        self.assertEqual(agents[0].strip(), "```mermaid")

    def test_install_and_hooks_stay_expanded(self):
        # The install section and the hooks table are never inside a details block.
        lines = readme().splitlines()
        depth, outside = 0, set()
        for number, line in enumerate(lines):
            depth += line.count("<details") - line.count("</details")
            if depth == 0:
                outside.add(number)
        self.assertIn(lines.index("## Install the plugin"), outside)
        hooks = next(i for i, line in enumerate(lines) if line.startswith("| SessionStart"))
        self.assertIn(hooks, outside)
        self.assertIn(lines.index("## What runs on your machine"), outside)

    def test_prose_shrinks(self):
        # Prose above the install section and in the selling sections is at least 30% below its
        # size before this change.
        lines = prose_words(readme())
        install = lines.index("## Install the plugin")
        start = lines.index("## Four agents, four jobs")
        end = lines.index("## What runs on your machine")
        words = count_words(lines[:install]) + count_words(lines[start:end])
        self.assertLessEqual(words, int(PROSE_BEFORE * PROSE_MAX_SHARE), words)


if __name__ == "__main__":
    unittest.main()
