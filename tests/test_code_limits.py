import ast
import importlib.util
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

MAX_FUNCTION_LINES = 50
MAX_FILE_LINES = 800


def repo_files(pattern):
    return [p for p in ROOT.rglob(pattern) if ".git" not in p.relative_to(ROOT).parts]


def python_sources():
    files = sorted((ROOT / "scripts").glob("*.py")) + sorted((ROOT / "tests").glob("*.py"))
    bin_dir = ROOT / "bin"
    if bin_dir.is_dir():
        files += sorted(p for p in bin_dir.iterdir() if p.is_file())
    return files


def line_count(path):
    return len(path.read_text(encoding="utf-8").splitlines())


def is_stdlib(name):
    try:
        spec = importlib.util.find_spec(name)
    except (ImportError, ValueError):
        return False
    if spec is None:
        return False
    if spec.origin in (None, "built-in", "frozen"):
        return True
    return "site-packages" not in spec.origin and "dist-packages" not in spec.origin


def imported_modules(tree):
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield alias.name.split(".")[0]
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            yield node.module.split(".")[0]


class CodeLimitsTest(unittest.TestCase):
    def test_functions_under_limit(self):
        for path in python_sources():
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    size = node.end_lineno - node.lineno + 1
                    self.assertLess(size, MAX_FUNCTION_LINES, f"{path.name}:{node.name}")

    def test_files_under_limit(self):
        files = []
        for pattern in ("*.py", "*.md", "*.json"):
            files += repo_files(pattern)
        bin_dir = ROOT / "bin"
        if bin_dir.is_dir():
            files += [p for p in bin_dir.iterdir() if p.is_file()]
        for path in files:
            self.assertLess(line_count(path), MAX_FILE_LINES, str(path.relative_to(ROOT)))

    def test_imports_are_stdlib_or_local(self):
        local = {p.stem for p in (ROOT / "scripts").glob("*.py")}
        sources = sorted((ROOT / "scripts").glob("*.py"))
        bin_dir = ROOT / "bin"
        if bin_dir.is_dir():
            sources += sorted(p for p in bin_dir.iterdir() if p.is_file())
        for path in sources:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for name in imported_modules(tree):
                ok = name in local or name == "__future__" or is_stdlib(name)
                self.assertTrue(ok, f"{path.name} imports non-stdlib module {name}")


if __name__ == "__main__":
    unittest.main()
