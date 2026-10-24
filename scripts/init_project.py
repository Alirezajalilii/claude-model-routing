from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
TEMPLATES_DIR = REPO_ROOT / "templates"
POINTER = (
    "Model routing: this project follows the claude-model-routing policy "
    "(plans in docs/plans/, routing log in docs/model-routing-log.md)."
)
POLICY_MARKER = "claude-model-routing"
TEMPLATE_TARGETS = (
    ("plans-README.md", "docs/plans/README.md"),
    ("model-routing-log.md", "docs/model-routing-log.md"),
)


def resolve_project_dir(arg: str | None) -> Path:
    if arg:
        return Path(arg)
    env_dir = os.environ.get("CLAUDE_PROJECT_DIR")
    return Path(env_dir) if env_dir else Path.cwd()


def write_template(project: Path, template: str, relpath: str) -> str:
    target = project / relpath
    if target.exists() or target.is_symlink():
        return f"exists {relpath}"
    target.parent.mkdir(parents=True, exist_ok=True)
    content = (TEMPLATES_DIR / template).read_text(encoding="utf-8")
    target.write_text(content, encoding="utf-8")
    return f"created {relpath}"


def append_pointer(project: Path) -> str:
    target = project / "CLAUDE.md"
    current = target.read_text(encoding="utf-8") if target.exists() else ""
    if POLICY_MARKER in current:
        return "exists CLAUDE.md pointer"
    if current:
        if not current.endswith("\n"):
            current += "\n"
        current += "\n"
    target.write_text(current + POINTER + "\n", encoding="utf-8")
    return "appended CLAUDE.md pointer"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="model-routing-init",
        description="Bootstrap a project for the claude-model-routing policy.",
    )
    parser.add_argument(
        "--project-dir",
        default=None,
        help="project directory (default: CLAUDE_PROJECT_DIR, else the current directory)",
    )
    parser.add_argument(
        "--claude-md",
        action="store_true",
        help="append the policy pointer to CLAUDE.md",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    project = resolve_project_dir(args.project_dir)
    if not project.is_dir():
        print(f"init_project: {project} does not exist", file=sys.stderr)
        return 2
    for template, relpath in TEMPLATE_TARGETS:
        print(write_template(project, template, relpath))
    if args.claude_md:
        print(append_pointer(project))
    else:
        print(f"pointer: {POINTER}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
