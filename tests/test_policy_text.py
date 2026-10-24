import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import policy_text as pt  # noqa: E402
import routing_config as rc  # noqa: E402


class RenderTest(unittest.TestCase):
    def test_plain_placeholder_with_and_without_spaces(self):
        self.assertEqual(pt.render("a {{plugin_name}} b", {"plugin_name": "p"}), "a p b")
        self.assertEqual(pt.render("a {{ plugin_name }} b", {"plugin_name": "p"}), "a p b")

    def test_unknown_placeholder(self):
        with self.assertRaises(ValueError) as ctx:
            pt.render("{{nope}}", {})
        self.assertIn("nope", str(ctx.exception))

    def test_section_include(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "x.md").write_text("## X\n{{plugin_name}}\n\n", encoding="utf-8")
            out = pt.render("{{section:x}}", {"plugin_name": "p"}, Path(tmp))
        self.assertEqual(out, "## X\np")

    def test_missing_section(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                pt.render("{{section:gone}}", {}, Path(tmp))

    def test_self_including_section(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "loop.md").write_text("{{section:loop}}", encoding="utf-8")
            with self.assertRaises(ValueError):
                pt.render("{{section:loop}}", {}, Path(tmp))

    def test_non_section_name_with_arg(self):
        with self.assertRaises(ValueError):
            pt.render("{{foo:bar}}", {})


class ValuesTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config = rc.load_config()

    def test_base_values(self):
        v = pt.base_values(self.config)
        self.assertEqual(v["calibration_sample_percent"], "20")
        self.assertEqual(v["calibration_low_defect_percent"], "5")
        self.assertEqual(v["calibration_reduced_sample_percent"], "5")
        self.assertEqual(v["calibration_high_defect_percent"], "10")
        self.assertEqual(v["planner_evidence_budget"], "5")
        self.assertEqual(v["skill_cap_haiku"], "2")
        self.assertEqual(v["skill_cap_other"], "4")
        self.assertEqual(
            v["calibration_draw_command"],
            'python3 -c "import random; print(random.random() < 0.2)"',
        )

    def test_base_values_exclude_agent_only_keys(self):
        v = pt.base_values(self.config)
        for key in ("tier_name", "skill_cap", "extra_rules"):
            self.assertNotIn(key, v)

    def test_roster(self):
        lines = pt.render_roster(self.config).split("\n")
        self.assertEqual(len(lines), 4)
        self.assertTrue(
            lines[0].startswith(
                "- Scouts: `scout-haiku-low` (haiku, low), "
                "`scout-haiku-medium` (haiku, medium)"
            )
        )
        self.assertTrue(lines[3].startswith("- Verifiers:"))


class PartTest(unittest.TestCase):
    def make_config(self, tmp):
        base = rc.load_config()
        parts = (
            rc.DispatcherPart(title="First", sections=("a", "b")),
            rc.DispatcherPart(title="Second", sections=("b",)),
        )
        for name, text in (("a", "Alpha\n\n"), ("b", "Beta {{plugin_name}}\n")):
            (Path(tmp) / f"{name}.md").write_text(text, encoding="utf-8")
        import dataclasses

        return dataclasses.replace(base, dispatcher_parts=parts)

    def test_render_part(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = self.make_config(tmp)
            self.assertEqual(pt.part_count(config), 2)
            out = pt.render_part(config, 1, Path(tmp))
        self.assertTrue(
            out.startswith("# model-routing policy, part 1 of 2: First\n\n")
        )
        body = out.split("\n\n", 1)[1]
        self.assertEqual(body, "Alpha\n\nBeta model-routing")

    def test_out_of_range(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = self.make_config(tmp)
            for index in (0, 3):
                with self.assertRaises(ValueError):
                    pt.render_part(config, index, Path(tmp))


if __name__ == "__main__":
    unittest.main()
