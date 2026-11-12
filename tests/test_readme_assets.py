import re
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "docs" / "assets"
SVG = "{http://www.w3.org/2000/svg}"
MAX_BYTES = 20480
MIN_FONT_PX = 14
BAR_SCALE = 560
HEADLINE = "Opus plans and reviews. Cheaper models write the code."
BARS = (
    ("bar-routed", "routed_usd", "As routed"),
    ("bar-sonnet", "all_sonnet_usd", "All Sonnet 5.5"),
    ("bar-opus", "all_opus_usd", "All Opus 5.5"),
)


def headline_numbers():
    lines = (ROOT / "docs" / "case-study-monorepo.md").read_text(encoding="utf-8").splitlines()
    start = lines.index("## Headline numbers")
    table = {}
    for line in lines[start + 1:]:
        if line.startswith("## "):
            break
        if line.startswith("|"):
            key, value = (c.strip() for c in line.strip().strip("|").split("|")[:2])
            table[key.strip("`")] = value
    return table


def number(text):
    return float(text.replace(",", ""))


def parse(name):
    if not (ASSETS / name).is_file():
        raise AssertionError("missing asset: docs/assets/" + name)
    return ET.parse(ASSETS / name).getroot()


def text_of(element):
    return " ".join(" ".join("".join(t.itertext()).split()) for t in element.iter(SVG + "text"))


class SvgAssetTest(unittest.TestCase):
    names = ("hero.svg", "cost-chart.svg")

    def test_files_are_small_valid_and_titled(self):
        # TC9: both SVGs exist, are under 20480 bytes, parse as XML, and have a title and a desc.
        for name in self.names:
            path = ASSETS / name
            self.assertTrue(path.is_file(), name)
            self.assertLess(path.stat().st_size, MAX_BYTES, name)
            root = parse(name)
            self.assertEqual(root.tag, SVG + "svg", name)
            for tag in ("title", "desc"):
                found = root.find(SVG + tag)
                self.assertIsNotNone(found, name + " lacks <" + tag + ">")
                self.assertTrue((found.text or "").strip(), name + " has an empty <" + tag + ">")

    def test_no_script_and_no_external_references(self):
        # TC9: no <script>, and no attribute value that starts with http (xmlns is not an attribute here).
        for name in self.names:
            root = parse(name)
            tags = [el.tag for el in root.iter()]
            self.assertNotIn(SVG + "script", tags, name)
            for el in root.iter():
                for attr, value in el.attrib.items():
                    self.assertFalse(value.strip().lower().startswith("http"), name + " " + attr)
            raw = (ASSETS / name).read_text(encoding="utf-8").lower()
            self.assertNotIn("<script", raw, name)
            self.assertIsNone(re.search(r"""(href|src)\s*=\s*["']\s*https?:""", raw), name)

    def test_own_background_and_text_size(self):
        # TC9: each SVG paints its own background (a rect as wide as the viewBox) and all text is
        # at least 14 px.
        for name in self.names:
            root = parse(name)
            width = float(root.get("viewBox").split()[2])
            backgrounds = [r for r in root.iter(SVG + "rect") if float(r.get("width", 0)) == width]
            self.assertTrue(backgrounds, name + " has no full-width background rect")
            sizes = [float(el.get("font-size")) for el in root.iter() if el.get("font-size")]
            self.assertTrue(sizes, name)
            self.assertGreaterEqual(min(sizes), MIN_FONT_PX, name)

    def test_cost_chart_bars(self):
        # TC10: three bars in order, widths round(value / all_opus_usd * 560), each with a $ label.
        n = headline_numbers()
        root = parse("cost-chart.svg")
        rects = {r.get("id"): r for r in root.iter(SVG + "rect") if r.get("id")}
        top = number(n["all_opus_usd"])
        ys = []
        for bar_id, key, label in BARS:
            self.assertIn(bar_id, rects)
            expected = round(number(n[key]) / top * BAR_SCALE)
            self.assertEqual(float(rects[bar_id].get("width")), expected, bar_id)
            ys.append(float(rects[bar_id].get("y")))
        self.assertEqual(ys, sorted(ys))
        text = text_of(root)
        for _, key, label in BARS:
            self.assertIn("$" + n[key], text)
            self.assertIn(label, text)

    def test_hero_headline(self):
        # TC11: hero.svg carries the headline text.
        root = parse("hero.svg")
        self.assertIn(HEADLINE, text_of(root))
        view = root.get("viewBox").split()
        self.assertEqual((float(view[2]), float(view[3])), (1280.0, 360.0))


if __name__ == "__main__":
    unittest.main()
