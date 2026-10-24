import io
import json
import re
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import generate as gen  # noqa: E402
import routing_config as rc  # noqa: E402

FRONTMATTER_KEYS = ["name", "description", "model", "effort", "tools", "disallowedTools"]


def split_agent(text):
    """Return (frontmatter dict in order, body) of a generated agent file."""
    lines = text.split("\n")
    assert lines[0] == "---"
    end = lines.index("---", 1)
    pairs = [line.split(": ", 1) for line in lines[1:end]]
    return pairs, "\n".join(lines[end + 1:])


def run_main(argv):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = gen.main(argv)
    return code, out.getvalue(), err.getvalue()


class GenerateTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config = rc.load_config()

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)
        code, _, err = run_main(["--root", str(self.tmp)])
        self.assertEqual(code, 0, err)

    def agent(self, name):
        return (self.tmp / "agents" / f"{name}.md").read_text(encoding="utf-8")

    def test_writes_exactly_the_expected_files(self):
        agents = sorted(p.name for p in (self.tmp / "agents").glob("*.md"))
        self.assertEqual(len(agents), len(self.config.tiers))
        self.assertTrue((self.tmp / "skills" / "routing-policy" / "SKILL.md").is_file())
        files = [p for p in self.tmp.rglob("*") if p.is_file()]
        self.assertEqual(len(files), len(self.config.tiers) + 1)

    def test_executor_frontmatter(self):
        pairs, _ = split_agent(self.agent("exec-haiku-low"))
        self.assertEqual([k for k, _ in pairs], FRONTMATTER_KEYS)
        values = dict(pairs)
        role = self.config.roles["executor"]
        self.assertEqual(values["model"], "haiku")
        self.assertEqual(values["effort"], "low")
        self.assertEqual(values["tools"], ", ".join(role.tools))
        self.assertEqual(values["disallowedTools"], ", ".join(role.disallowed_tools))
        tier = next(t for t in self.config.tiers if t.name == "exec-haiku-low")
        self.assertEqual(json.loads(values["description"]), tier.description)

    def test_planner_disallowed_and_no_skills_key(self):
        pairs, _ = split_agent(self.agent("planner-opus-high"))
        self.assertEqual(
            dict(pairs)["disallowedTools"],
            ", ".join(self.config.roles["planner"].disallowed_tools),
        )
        for tier in self.config.tiers:
            keys = [k for k, _ in split_agent(self.agent(tier.name))[0]]
            self.assertNotIn("skills", keys)

    def test_haiku_extra_rule_only_in_haiku(self):
        marker = "- Stay inside the paths, line ranges and question you were given."
        for tier in self.config.tiers:
            text = self.agent(tier.name)
            self.assertEqual(marker in text, tier.family == "haiku", tier.name)
            self.assertNotIn("{{", text)
            self.assertNotIn("\n\n\n", text)

    def test_generated_note_follows_frontmatter(self):
        for tier in self.config.tiers:
            _, body = split_agent(self.agent(tier.name))
            self.assertTrue(body.startswith("\n" + gen.GENERATED_NOTE + "\n\n"), tier.name)

    def test_reference_skill(self):
        text = (self.tmp / "skills" / "routing-policy" / "SKILL.md").read_text(encoding="utf-8")
        pairs, body = split_agent(text)
        self.assertEqual(dict(pairs)["name"], "routing-policy")
        self.assertTrue(body.lstrip("\n").startswith(gen.GENERATED_NOTE))
        position = 0
        for section in self.config.policy_sections:
            first = (ROOT / "policy" / "sections" / f"{section}.md").read_text(
                encoding="utf-8").split("\n", 1)[0]
            found = body.find(first, position)
            self.assertGreaterEqual(found, 0, section)
            position = found
        self.assertTrue(text.endswith("\n"))


class CheckTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)
        self.assertEqual(run_main(["--root", str(self.tmp)])[0], 0)

    def check(self):
        return run_main(["--check", "--root", str(self.tmp)])

    def test_clean(self):
        self.assertEqual(self.check()[0], 0)

    def test_edited_agent(self):
        target = self.tmp / "agents" / "exec-haiku-low.md"
        target.write_text(target.read_text(encoding="utf-8") + "x\n", encoding="utf-8")
        code, out, _ = self.check()
        self.assertEqual(code, 1)
        self.assertIn("exec-haiku-low.md", out)

    def test_extra_agent(self):
        (self.tmp / "agents" / "foo.md").write_text("x\n", encoding="utf-8")
        code, out, _ = self.check()
        self.assertEqual(code, 1)
        self.assertIn("foo.md", out)

    def test_missing_skill(self):
        (self.tmp / "skills" / "routing-policy" / "SKILL.md").unlink()
        self.assertEqual(self.check()[0], 1)

    def test_config_error_returns_2(self):
        original = gen.CONFIG_PATH
        with tempfile.TemporaryDirectory() as bad:
            path = Path(bad) / "routing.json"
            path.write_text("{not json", encoding="utf-8")
            gen.CONFIG_PATH = path
            try:
                code, _, err = run_main(["--root", str(self.tmp)])
            finally:
                gen.CONFIG_PATH = original
        self.assertEqual(code, 2)
        self.assertTrue(err.strip())


if __name__ == "__main__":
    unittest.main()
