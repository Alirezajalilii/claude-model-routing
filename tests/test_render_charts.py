"""Checks for scripts/render_charts.py and the four data charts docs/assets/chart-*.svg (PL18, PL21).

Every number in a chart is recomputed here from the committed data in docs/case-study/ and
docs/cost/, and every chart file is compared byte for byte with what render_all produces.
"""
from __future__ import annotations

import contextlib
import io
import json
import re
import shutil
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

ASSETS = ROOT / "docs" / "assets"
SVG = "{http://www.w3.org/2000/svg}"
NAMES = ("chart-cost.svg", "chart-model-mix.svg", "chart-context.svg", "chart-projects.svg")
MAX_BYTES = 20480
VIEW_W = 640
MIN_FONT_PX = 22
MIN_TITLE_PX = 28
TEXT_LEFT, TEXT_RIGHT = 16, 624
GLYPH = 0.62
LEAD = 1.3
BAR_X = 40
ZERO_X = 200
BAR_SCALE = 560
PROJECT_SCALE = 360
REPO_GROUP = "One logged run on this repository (15 tasks)"
CAPTION = (
    "Each group is drawn against its own all-Opus cost. "
    "Values are subagent spend at list prices."
)
BANNED_WORDS = (
    "game-changing", "revolutionary", "world-class", "cutting-edge", "seamless",
    "supercharge", "effortless", "blazing", "unleash", "unlock", "leverage", "delve",
    "elevate", "empower", "next-level", "game-changer", "robust", "streamline",
    "harness", "tapestry",
)
GROUP_KEYS = ("all", "haiku", "repo")
KINDS = ("routed", "sonnet", "opus")
ROLES = ("scout", "plan", "exec", "verify")


def rc():
    import render_charts

    return render_charts


def load(*parts: str):
    return json.loads(ROOT.joinpath(*parts).read_text(encoding="utf-8"))


def usage_rows():
    return load("docs", "case-study", "cross-project-usage.json")


def repo_rows():
    return load("docs", "cost", "2026-11-11-run.json")


def peaks():
    return load("docs", "case-study", "context-peaks.json")


def parse(name: str, base: Path = ASSETS) -> ET.Element:
    if not (base / name).is_file():
        raise AssertionError("missing chart: " + name)
    return ET.parse(base / name).getroot()


def text_of(root: ET.Element) -> str:
    return " ".join(" ".join("".join(t.itertext()).split()) for t in root.iter(SVG + "text"))


def desc_of(root: ET.Element) -> str:
    return " ".join("".join(root.find(SVG + "desc").itertext()).split())


def rect_by_id(root: ET.Element) -> dict:
    return {r.get("id"): r for r in root.iter(SVG + "rect") if r.get("id")}


def width_of(rects: dict, rect_id: str) -> float:
    if rect_id not in rects:
        raise AssertionError("missing rect id " + rect_id)
    return float(rects[rect_id].get("width"))


def luminance(color: str) -> float:
    channels = [int(color[i:i + 2], 16) / 255 for i in (1, 3, 5)]
    lin = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
    return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]


def contrast(a: str, b: str) -> float:
    hi, lo = sorted((luminance(a), luminance(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def background_fill(root: ET.Element) -> str:
    view_w = float(root.get("viewBox").split()[2])
    for rect in root.iter(SVG + "rect"):
        if float(rect.get("width", "0")) == view_w and float(rect.get("x", "0")) == 0:
            return rect.get("fill")
    raise AssertionError("no full-width background rect")


def half_up(value: float) -> int:
    return int(value + 0.5)


def money(value: float) -> str:
    return f"${value:,.2f}"


class DataFunctionTests(unittest.TestCase):
    # TC5 (guard): the five data tests below are PL18's TC1 to TC5 (values, segments, mix, medians,
    # project savings). PL21 does not change them; the guard line selects them by name.
    def test_tc1_cost_scenarios(self):
        # TC1: three scenarios with routed, all-Sonnet and all-Opus spend.
        got = rc().cost_scenarios(usage_rows(), repo_rows())
        expected = (
            ("All sessions", 3272.02, 3454.92, 6909.83),
            ("Haiku-heavy sessions", 835.47, 1329.17, 2658.34),
            (REPO_GROUP, 11.27, 29.73, 59.45),
        )
        self.assertEqual(len(got), 3)
        for row, want in zip(got, expected):
            self.assertEqual(row[0], want[0])
            for value, number in zip(row[1:], want[1:]):
                self.assertAlmostEqual(value, number, delta=0.01, msg=want[0])

    def test_tc2_session_segments(self):
        # TC2: 24 Haiku-heavy (A), 7 Sonnet-heavy (B), 3 other (C) and 8 sessions without executors.
        segments = rc().session_segments(usage_rows())
        counts = {}
        for letter in segments.values():
            counts[letter] = counts.get(letter, 0) + 1
        self.assertEqual(counts, {"A": 24, "B": 7, "C": 3, "none": 8})

    def test_tc3_model_mix(self):
        # TC3: agents per role and model family, by the model named in the agent type.
        mix = rc().model_mix(usage_rows())
        expected = {
            "scout": {"haiku": 139, "sonnet": 98},
            "plan": {"sonnet": 9, "opus": 57},
            "exec": {"haiku": 591, "sonnet": 367},
            "verify": {"sonnet": 288, "opus": 236},
        }
        self.assertEqual({role: dict(families) for role, families in mix.items()}, expected)

    def test_tc4_context_medians(self):
        # TC4: median peak prompt tokens by role and for the main sessions.
        got = rc().context_medians(peaks())
        self.assertEqual(
            list(got),
            [
                ("scout", 89307), ("exec", 89394), ("verify", 105298),
                ("plan", 374604), ("main", 374470),
            ],
        )

    def test_tc5_project_savings(self):
        # TC5: 11 projects; P07 saves most; P08 costs more than all-Sonnet; all-Opus saving above 40.
        rows = rc().project_savings(usage_rows())
        self.assertEqual([r[0] for r in rows], ["P%02d" % n for n in range(1, 12)])
        by_label = {r[0]: r for r in rows}
        self.assertEqual(by_label["P07"][1:], (73.3, 46.6))
        self.assertEqual(by_label["P08"][1:], (41.0, -18.0))
        for row in rows:
            self.assertGreater(row[1], 40.0, row[0])


class FileShapeTests(unittest.TestCase):
    def test_tc6_files_are_valid_small_and_plain(self):
        # TC6: parse, title and desc, no script, no external reference, no text style, font size.
        for name in NAMES:
            path = ASSETS / name
            self.assertTrue(path.is_file(), name)
            self.assertLess(path.stat().st_size, MAX_BYTES, name)
            root = parse(name)
            self.assertEqual(root.tag, SVG + "svg", name)
            for tag in ("title", "desc"):
                found = root.find(SVG + tag)
                self.assertIsNotNone(found, name + " lacks <" + tag + ">")
                self.assertTrue("".join(found.itertext()).strip(), name + " empty " + tag)
            self.assertNotIn(SVG + "script", [el.tag for el in root.iter()], name)
            for el in root.iter():
                for attr, value in el.attrib.items():
                    self.assertFalse(value.strip().lower().startswith("http"), name + " " + attr)

    def test_tc6_text_elements_carry_numeric_font_size(self):
        # TC6: every <text> has no style attribute and a plain numeric font-size (the size limits
        # moved to PL21 TC1: the old 960 viewBox and 14 minimum assertions are gone).
        for name in NAMES:
            root = parse(name)
            texts = list(root.iter(SVG + "text"))
            self.assertTrue(texts, name)
            for text in texts:
                self.assertIsNone(text.get("style"), name)
                self.assertRegex(text.get("font-size", ""), r"^\d+(\.\d+)?$", name)

    def test_tc6_no_dashes_or_banned_words_in_text(self):
        # TC6: no em or en dash and none of the banned words in the title, desc or visible text.
        for name in NAMES:
            root = parse(name)
            body = text_of(root) + " " + desc_of(root) + " " + "".join(root.find(SVG + "title").itertext())
            self.assertNotIn("\u2014", body, name)
            self.assertNotIn("\u2013", body, name)
            lowered = body.lower()
            self.assertEqual([w for w in BANNED_WORDS if w in lowered], [], name)

    def test_tc7_text_contrast_against_the_background(self):
        # TC7: every text fill has a WCAG contrast ratio of at least 4.5 against the background rect.
        for name in NAMES:
            root = parse(name)
            background = background_fill(root)
            self.assertRegex(background, r"^#[0-9a-fA-F]{6}$", name)
            for text in root.iter(SVG + "text"):
                fill = text.get("fill")
                self.assertRegex(fill or "", r"^#[0-9a-fA-F]{6}$", name)
                self.assertGreaterEqual(contrast(fill, background), 4.5, f"{name} {fill}")

    def test_tc6_text_never_sits_over_a_shape(self):
        # TC6: an estimated text box never overlaps a bar, swatch or rule (only the background rect).
        for name in NAMES:
            root = parse(name)
            shapes = [
                (float(r.get("x", "0")), float(r.get("y", "0")), float(r.get("width")), float(r.get("height")))
                for r in root.iter(SVG + "rect")
                if float(r.get("width")) < VIEW_W
            ]
            for text in root.iter(SVG + "text"):
                box = estimated_box(text)
                for shape in shapes:
                    self.assertFalse(overlaps(box, shape), f"{name}: {''.join(text.itertext())!r} over {shape}")


def estimated_box(text: ET.Element) -> tuple:
    size = float(text.get("font-size"))
    factor = 0.62 if text.get("font-weight") in (None, "400", "500") else 0.68
    width = len("".join(text.itertext())) * size * factor
    x = float(text.get("x"))
    anchor = text.get("text-anchor", "start")
    left = x - width if anchor == "end" else (x - width / 2 if anchor == "middle" else x)
    baseline = float(text.get("y"))
    return (left, baseline - size * 0.8, width, size * 0.95)


def plan_box(text: ET.Element) -> tuple:
    """PL21 box: width len * 0.62 * font-size placed by x and anchor; height is the font size above the baseline."""
    size = float(text.get("font-size"))
    width = len(content(text)) * GLYPH * size
    x = float(text.get("x"))
    anchor = text.get("text-anchor", "start")
    left = x - width if anchor == "end" else (x - width / 2 if anchor == "middle" else x)
    return (left, float(text.get("y")) - size, width, size)


def overlaps(box: tuple, shape: tuple) -> bool:
    bx, by, bw, bh = box
    sx, sy, sw, sh = shape
    return bx < sx + sw and sx < bx + bw and by < sy + sh and sy < by + bh


class GeometryTests(unittest.TestCase):
    def test_tc8_cost_bar_widths(self):
        # TC8: width = round(value / own all-Opus * 560) for every bar of chart-cost.svg.
        rects = rect_by_id(parse("chart-cost.svg"))
        for key, (_name, *values) in zip(GROUP_KEYS, rc().cost_scenarios(usage_rows(), repo_rows())):
            opus = values[2]
            for kind, value in zip(KINDS, values):
                self.assertEqual(width_of(rects, f"cost-{key}-{kind}"), round(value / opus * BAR_SCALE))

    def test_tc8_context_bar_widths(self):
        # TC8: width = round(value / max * 560) for every bar of chart-context.svg.
        rects = rect_by_id(parse("chart-context.svg"))
        medians = rc().context_medians(peaks())
        top = max(value for _label, value in medians)
        for label, value in medians:
            self.assertEqual(width_of(rects, "ctx-" + label), round(value / top * BAR_SCALE), label)

    def test_tc8_project_bar_lengths_and_direction(self):
        # TC8: length = round(abs(pct) / 100 * 360) from a shared zero line; negatives run left.
        rects = rect_by_id(parse("chart-projects.svg"))
        rows = rc().project_savings(usage_rows())
        zero = None
        for label, opus, sonnet in rows:
            for kind, pct in (("opus", opus), ("sonnet", sonnet)):
                rect = rects["proj-%s-%s" % (label, kind)]
                self.assertEqual(float(rect.get("width")), round(abs(pct) / 100 * PROJECT_SCALE), label)
                if pct >= 0 and zero is None:
                    zero = float(rect.get("x"))
        self.assertIsNotNone(zero)
        for label, opus, sonnet in rows:
            for kind, pct in (("opus", opus), ("sonnet", sonnet)):
                rect = rects["proj-%s-%s" % (label, kind)]
                x, width = float(rect.get("x")), float(rect.get("width"))
                if pct >= 0:
                    self.assertEqual(x, zero, label)
                else:
                    self.assertEqual(x + width, zero, label)

    def test_tc8_model_mix_segments(self):
        # TC8: role width = round(total / largest * 560); segments proportional, last one absorbs rounding.
        rects = rect_by_id(parse("chart-model-mix.svg"))
        mix = rc().model_mix(usage_rows())
        largest = max(sum(f.values()) for f in mix.values())
        for role in ROLES:
            total = sum(mix[role].values())
            role_width = round(total / largest * BAR_SCALE)
            families = [f for f in ("haiku", "sonnet", "opus") if mix[role].get(f)]
            widths = [width_of(rects, f"mix-{role}-{f}") for f in families]
            self.assertEqual(sum(widths), role_width, role)
            for family, width in zip(families[:-1], widths[:-1]):
                self.assertEqual(width, round(mix[role][family] / total * role_width), role + family)
            xs = [float(rects[f"mix-{role}-{f}"].get("x")) for f in families]
            for index in range(1, len(xs)):
                self.assertEqual(xs[index], xs[index - 1] + widths[index - 1], role)


class PhoneLegibilityTests(unittest.TestCase):
    """PL21: phone-first geometry. A 640 wide viewBox, big text, labels above bars."""

    def test_phone_viewbox_and_sizes(self):
        # TC1: viewBox is 0 0 640 <height>; every <text> has a numeric font-size of at least 22; the
        # title (the first <text>) at least 28; stacked lines (same x and anchor) keep 1.3 times the font size.
        for name in NAMES:
            root = parse(name)
            self.assertRegex(root.get("viewBox"), r"^0 0 640 \d+$", name)
            texts = list(root.iter(SVG + "text"))
            self.assertTrue(texts, name)
            for text in texts:
                self.assertRegex(text.get("font-size", ""), r"^\d+(\.\d+)?$", name)
                self.assertGreaterEqual(float(text.get("font-size")), MIN_FONT_PX, name)
            self.assertGreaterEqual(float(texts[0].get("font-size")), MIN_TITLE_PX, name)
            for upper in texts:
                for lower in texts:
                    same_column = upper.get("x") == lower.get("x") and upper.get("text-anchor") == lower.get("text-anchor")
                    step = float(lower.get("y")) - float(upper.get("y"))
                    if same_column and step > 0:
                        self.assertGreaterEqual(step, LEAD * float(lower.get("font-size")), f"{name}: {content(lower)!r}")

    def test_text_fits(self):
        # TC2: len * 0.62 * font-size, placed by x and text-anchor, lies within 16..624.
        for name in NAMES:
            for text in parse(name).iter(SVG + "text"):
                left, _top, width, _height = plan_box(text)
                self.assertGreaterEqual(left, TEXT_LEFT, f"{name}: {content(text)!r}")
                self.assertLessEqual(left + width, TEXT_RIGHT, f"{name}: {content(text)!r}")

    def test_no_overlap(self):
        # TC3: no two <text> boxes intersect, and no text box intersects a <rect> other than the background.
        for name in NAMES:
            root = parse(name)
            texts = list(root.iter(SVG + "text"))
            boxes = [plan_box(text) for text in texts]
            for index, box in enumerate(boxes):
                for other in range(index + 1, len(boxes)):
                    self.assertFalse(
                        overlaps(box, boxes[other]),
                        f"{name}: {content(texts[index])!r} overlaps {content(texts[other])!r}",
                    )
            shapes = [
                (float(r.get("x", "0")), float(r.get("y", "0")), float(r.get("width")), float(r.get("height")))
                for r in root.iter(SVG + "rect")
                if r.get("id") != "bg"
            ]
            for text, box in zip(texts, boxes):
                for shape in shapes:
                    self.assertFalse(overlaps(box, shape), f"{name}: {content(text)!r} over {shape}")

    def test_phone_bar_widths(self):
        # TC4: widths follow the 560 scale (cost, mix, context, from x 40) and the 360 scale from the
        # zero line at x 200 (projects); mix segments sum to the role width; the zero line is a <line>.
        costs = rect_by_id(parse("chart-cost.svg"))
        for key, (_name, *values) in zip(GROUP_KEYS, rc().cost_scenarios(usage_rows(), repo_rows())):
            for kind, value in zip(KINDS, values):
                self.assertEqual(width_of(costs, f"cost-{key}-{kind}"), round(value / values[2] * BAR_SCALE))
                self.assertEqual(float(costs[f"cost-{key}-{kind}"].get("x")), BAR_X)
        self.check_context_and_mix()
        self.check_projects()

    def check_context_and_mix(self):
        contexts = rect_by_id(parse("chart-context.svg"))
        medians = rc().context_medians(peaks())
        top = max(value for _label, value in medians)
        for label, value in medians:
            self.assertEqual(width_of(contexts, "ctx-" + label), round(value / top * BAR_SCALE), label)
            self.assertEqual(float(contexts["ctx-" + label].get("x")), BAR_X, label)
        mixes = rect_by_id(parse("chart-model-mix.svg"))
        mix = rc().model_mix(usage_rows())
        largest = max(sum(f.values()) for f in mix.values())
        for role in ROLES:
            families = [f for f in ("haiku", "sonnet", "opus") if mix[role].get(f)]
            widths = [width_of(mixes, f"mix-{role}-{f}") for f in families]
            self.assertEqual(sum(widths), round(sum(mix[role].values()) / largest * BAR_SCALE), role)
            self.assertEqual(float(mixes[f"mix-{role}-{families[0]}"].get("x")), BAR_X, role)

    def check_projects(self):
        root = parse("chart-projects.svg")
        lines = [el for el in root.iter(SVG + "line") if float(el.get("x1")) == ZERO_X and float(el.get("x2")) == ZERO_X]
        self.assertEqual(len(lines), 1, "the zero line must be one <line> at x 200")
        rects = rect_by_id(root)
        for rect in root.iter(SVG + "rect"):
            tall_on_zero = float(rect.get("x", "0")) <= ZERO_X <= float(rect.get("x", "0")) + float(rect.get("width"))
            self.assertFalse(tall_on_zero and float(rect.get("height")) > 40 and rect.get("id") != "bg", "tall rect on the zero line")
        notes = [(t.get("x"), t.get("text-anchor", "start"), content(t)) for t in root.iter(SVG + "text")]
        for label, opus, sonnet in rc().project_savings(usage_rows()):
            for kind, pct in (("opus", opus), ("sonnet", sonnet)):
                rect = rects[f"proj-{label}-{kind}"]
                x, width = float(rect.get("x")), float(rect.get("width"))
                self.assertEqual(width, round(abs(pct) / 100 * PROJECT_SCALE), label)
                shown = f"{pct:.1f}%"
                if pct >= 0:
                    self.assertEqual(x, ZERO_X, label)
                    self.assertIn((str(int(x + width + 8)), "start", shown), notes, label)
                else:
                    self.assertEqual(x + width, ZERO_X, label)
                    self.assertIn((str(int(x - 8)), "end", shown), notes, label)


def content(text: ET.Element) -> str:
    return "".join(text.itertext())


class ReproducibilityTests(unittest.TestCase):
    def test_tc9_render_all_is_deterministic_and_matches_committed_files(self):
        # TC9: two calls agree and equal the committed files byte for byte.
        first = rc().render_all(ROOT)
        self.assertEqual(first, rc().render_all(ROOT))
        self.assertEqual(sorted(first), sorted(NAMES))
        for name in NAMES:
            self.assertEqual((ASSETS / name).read_bytes(), first[name].encode("utf-8"), name)

    def test_tc10_check_passes_on_the_repository(self):
        # TC10: --check on the repository returns 0 and prints nothing stale.
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = rc().main(["--check"])
        self.assertEqual(code, 0)
        self.assertNotIn("stale:", out.getvalue())

    def test_tc10_check_reports_an_altered_chart(self):
        # TC10: one altered chart in a temporary copy gives exit 1 and `stale: chart-cost.svg`.
        with tempfile.TemporaryDirectory() as tmp:
            copy_inputs(Path(tmp))
            altered = Path(tmp) / "docs" / "assets" / "chart-cost.svg"
            altered.write_text(altered.read_text(encoding="utf-8").replace("As routed", "As run"), encoding="utf-8")
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                code = rc().main(["--check", "--root", tmp])
            self.assertEqual(code, 1)
            self.assertIn("stale: chart-cost.svg", out.getvalue())
            self.assertNotIn("stale: chart-context.svg", out.getvalue())

    def test_tc10_default_run_rewrites_the_charts_under_root(self):
        # TC10: without --check, main writes the four charts under --root; a check then passes.
        with tempfile.TemporaryDirectory() as tmp:
            copy_inputs(Path(tmp))
            shutil.rmtree(Path(tmp) / "docs" / "assets")
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(rc().main(["--root", tmp]), 0)
            for name in NAMES:
                self.assertEqual((Path(tmp) / "docs" / "assets" / name).read_bytes(), (ASSETS / name).read_bytes())
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(rc().main(["--check", "--root", tmp]), 0)

    def test_tc10_check_reports_a_missing_chart(self):
        # TC10: a chart missing from the root counts as stale.
        with tempfile.TemporaryDirectory() as tmp:
            copy_inputs(Path(tmp))
            (Path(tmp) / "docs" / "assets" / "chart-projects.svg").unlink()
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                code = rc().main(["--check", "--root", tmp])
            self.assertEqual(code, 1)
            self.assertIn("stale: chart-projects.svg", out.getvalue())


def copy_inputs(base: Path) -> None:
    for parts in (("docs", "case-study"), ("docs", "cost"), ("docs", "assets")):
        shutil.copytree(ROOT.joinpath(*parts), base.joinpath(*parts))


class DescTests(unittest.TestCase):
    def assert_in_text_and_desc(self, name: str, expected: list) -> None:
        root = parse(name)
        visible, desc = text_of(root), desc_of(root)
        for item in expected:
            self.assertIn(item, visible, f"{name} text lacks {item}")
            self.assertIn(item, desc, f"{name} desc lacks {item}")

    def test_tc11_cost_chart_text_and_desc(self):
        # TC11 (TC7): group labels, dollar values, saving against all-Sonnet and the caption, shown and
        # in desc; the visible side is all <text> contents joined with single spaces, so wrapped lines match.
        expected = []
        for name, routed, sonnet, opus in rc().cost_scenarios(usage_rows(), repo_rows()):
            expected += [name, money(routed), money(sonnet), money(opus)]
            expected.append("%d%% below all Sonnet" % half_up((sonnet - routed) / sonnet * 100))
        expected += [REPO_GROUP, CAPTION]
        self.assert_in_text_and_desc("chart-cost.svg", expected)

    def test_wrapped_labels_match_joined_text(self):
        # TC7: the repository run label wraps as `One logged run on this repository` then `(15 tasks)`,
        # and the wrapped label and caption still match the joined text of all <text> contents.
        root = parse("chart-cost.svg")
        texts = [content(t) for t in root.iter(SVG + "text")]
        index = texts.index("One logged run on this repository")
        self.assertEqual(texts[index + 1], "(15 tasks)")
        joined = text_of(root)
        self.assertIn(REPO_GROUP, joined)
        self.assertIn(CAPTION, joined)

    def test_tc11_model_mix_text_and_desc(self):
        # TC11: every count and role name shown, and in desc.
        mix = rc().model_mix(usage_rows())
        expected = []
        for role in ROLES:
            expected += [str(count) for count in mix[role].values()]
        expected += ["Haiku", "Sonnet", "Opus"]
        self.assert_in_text_and_desc("chart-model-mix.svg", expected)
        desc = desc_of(parse("chart-model-mix.svg")).lower()
        for role in ROLES:
            self.assertIn(role, desc)

    def test_tc11_context_text_and_desc(self):
        # TC11: every label in thousands, half up, shown and in desc.
        expected = ["%dK" % half_up(value / 1000) for _label, value in rc().context_medians(peaks())]
        self.assert_in_text_and_desc("chart-context.svg", expected)

    def test_tc11_projects_text_and_desc(self):
        # TC11: every project label and saving with one decimal and a percent sign, and the caption.
        expected = []
        for label, opus, sonnet in rc().project_savings(usage_rows()):
            expected += [label, f"{opus:.1f}%", f"{sonnet:.1f}%"]
        expected.append("subagent spend at list prices")
        self.assert_in_text_and_desc("chart-projects.svg", expected)

    def test_tc11_no_project_names_or_stacks(self):
        # TC11: only the neutral labels P01 to P11 identify a project; no path or hash-like text.
        root = parse("chart-projects.svg")
        body = text_of(root) + " " + desc_of(root)
        self.assertNotIn("/", body.replace("and/or", ""))
        for token in re.findall(r"\bP\d+\b", body):
            self.assertRegex(token, r"^P(0[1-9]|1[01])$")


if __name__ == "__main__":
    unittest.main()
