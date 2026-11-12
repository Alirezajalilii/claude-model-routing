import re
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "docs" / "assets"
SVG = "{http://www.w3.org/2000/svg}"
MAX_BYTES = 20480
MIN_FONT_PX = 14
HEADLINE = "The right Claude for every step."


def parse(name):
    if not (ASSETS / name).is_file():
        raise AssertionError("missing asset: docs/assets/" + name)
    return ET.parse(ASSETS / name).getroot()


def text_of(element):
    return " ".join(" ".join("".join(t.itertext()).split()) for t in element.iter(SVG + "text"))


class SvgAssetTest(unittest.TestCase):
    names = ("hero.svg",)

    def test_files_are_small_valid_and_titled(self):
        # TC6: hero.svg exists, is under 20480 bytes, parses as XML, and has a title and a desc.
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
        # TC6: no <script>, and no attribute value that starts with http (xmlns is not an attribute here).
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
        # TC6: each SVG paints its own background (a rect as wide as the viewBox) and all text is
        # at least 14 px.
        for name in self.names:
            root = parse(name)
            width = float(root.get("viewBox").split()[2])
            backgrounds = [r for r in root.iter(SVG + "rect") if float(r.get("width", 0)) == width]
            self.assertTrue(backgrounds, name + " has no full-width background rect")
            sizes = [float(el.get("font-size")) for el in root.iter() if el.get("font-size")]
            self.assertTrue(sizes, name)
            self.assertGreaterEqual(min(sizes), MIN_FONT_PX, name)

    def test_hero_headline(self):
        # TC6: hero.svg carries the headline text.
        root = parse("hero.svg")
        self.assertIn(HEADLINE, text_of(root))
        view = root.get("viewBox").split()
        self.assertEqual((float(view[2]), float(view[3])), (1280.0, 360.0))


if __name__ == "__main__":
    unittest.main()
