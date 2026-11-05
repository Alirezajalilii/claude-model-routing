#!/usr/bin/env python3
"""Build the skills inventory that the Model Routing Policy hands to planners.

Lists every model-invocable skill a Claude Code session in the project can load:
user skills (CLAUDE_DIR/skills), project skills (PROJECT_DIR/.claude/skills),
plugin skills from CLAUDE_CODE_PLUGIN_DIRS (settings env), enabled user-scope
plugins, and local-scope plugins installed for the project. Directory marketplace
plugins fall back to their source directory when the cache has no skills.
Skills that set `disable-model-invocation: true` are excluded, because agents
cannot load them. Skills without frontmatter are skipped. Skills kept one group
folder down (`<skills dir>/<group>/<name>/SKILL.md`, for example the ECC skills)
are listed with scope `<scope> group <group>`; deeper nesting is not listed, and
a folder that holds its own SKILL.md is a skill, not a group. Bundled skills that
ship inside the Claude Code binary are not on disk and are not listed.

Usage: skills_inventory.py [--claude-dir DIR] [--project-dir DIR] [--out FILE]
Output: a Markdown table (name, scope, SKILL.md path, one-line description).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import NamedTuple

DESCRIPTION_LIMIT = 220


class SkillRow(NamedTuple):
    name: str
    scope: str
    description: str
    path: str


def default_claude_dir() -> Path:
    return Path.home() / ".claude"


def load_json(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


BLOCK_SCALARS = (">", "|", ">-", "|-", ">+", "|+")


def read_frontmatter(skill_md: Path) -> dict:
    text = skill_md.read_text(encoding="utf-8", errors="replace")
    if not text.startswith("---"):
        return {}
    end = text.find("\n---", 3)
    if end == -1:
        return {}
    fields: dict = {}
    block: tuple[str, list[str]] | None = None
    for line in text[3:end].splitlines():
        if not line.strip():
            continue
        if line.startswith((" ", "\t")):
            if block is not None:
                block[1].append(line.strip())
            continue
        if block is not None:
            fields[block[0]] = " ".join(block[1])
            block = None
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        if value.strip() in BLOCK_SCALARS:
            block = (key.strip(), [])
        else:
            fields[key.strip()] = value.strip().strip("\"'")
    if block is not None:
        fields[block[0]] = " ".join(block[1])
    return fields


def _skill_files(skills_dir: Path) -> list[tuple[Path, str | None]]:
    """Top-level skills first, then skills one group folder down (group name, else None)."""
    top = [(path, None) for path in sorted(skills_dir.glob("*/SKILL.md"))]
    grouped = [
        (path, path.parent.parent.name)
        for path in sorted(skills_dir.glob("*/*/SKILL.md"))
        if not (path.parent.parent / "SKILL.md").is_file()
    ]
    return top + grouped


def skill_rows(skills_dir: Path, prefix: str, scope: str) -> list[SkillRow]:
    if not skills_dir.is_dir():
        return []
    rows = []
    for skill_md, group in _skill_files(skills_dir):
        fields = read_frontmatter(skill_md)
        if not fields:
            continue
        if fields.get("disable-model-invocation", "").lower() == "true":
            continue
        name = fields.get("name") or skill_md.parent.name
        desc = " ".join(fields.get("description", "").split())
        path = str(skill_md.resolve())
        skill_scope = scope if group is None else f"{scope} group {group}"
        rows.append(SkillRow(f"{prefix}{name}", skill_scope, desc[:DESCRIPTION_LIMIT], path))
    return rows


def plugin_name(plugin_dir: Path) -> str:
    manifest = load_json(plugin_dir / ".claude-plugin" / "plugin.json")
    return manifest.get("name") or plugin_dir.name


def is_active(inst: dict, enabled: bool, project_dir: Path) -> bool:
    if enabled:
        return True
    if inst.get("scope") != "local" or not inst.get("projectPath"):
        return False
    return Path(inst["projectPath"]).resolve() == Path(project_dir).resolve()


def directory_source(key: str, markets: dict):
    """A plugin from a local directory marketplace keeps its skills at the source, not in the cache."""
    plugin, _, market = key.partition("@")
    source = (markets.get(market) or {}).get("source") or {}
    if source.get("source") != "directory" or not source.get("path"):
        return None
    root = Path(source["path"])
    manifest = load_json(root / ".claude-plugin" / "marketplace.json")
    for entry in manifest.get("plugins", []):
        if isinstance(entry, dict) and entry.get("name") == plugin and isinstance(entry.get("source"), str):
            return (root / entry["source"]).resolve()
    return None


def installed_dirs(installed: dict, enabled: set, markets: dict, project_dir: Path) -> list[Path]:
    dirs = []
    for key, installs in installed.items():
        for inst in installs:
            if not is_active(inst, key in enabled, project_dir) or not inst.get("installPath"):
                continue
            path = Path(inst["installPath"])
            if not any(path.glob("skills/*/SKILL.md")):
                path = directory_source(key, markets) or path
            dirs.append(path)
    return dirs


def plugin_dirs(claude_dir: Path, project_dir: Path) -> list[Path]:
    settings = load_json(claude_dir / "settings.json")
    env = settings.get("env") or {}
    raw = str(env.get("CLAUDE_CODE_PLUGIN_DIRS", ""))
    dirs = [Path(p) for p in raw.split(os.pathsep) if p]
    enabled = {k for k, v in (settings.get("enabledPlugins") or {}).items() if v}
    markets = settings.get("extraKnownMarketplaces") or {}
    installed = load_json(claude_dir / "plugins" / "installed_plugins.json").get("plugins") or {}
    return dirs + installed_dirs(installed, enabled, markets, project_dir)


def build_rows(claude_dir: Path, project_dir: Path) -> list[SkillRow]:
    project_dir = project_dir.resolve()
    rows = skill_rows(claude_dir / "skills", "", "user")
    rows += skill_rows(project_dir / ".claude" / "skills", "", "project")
    seen: set[str] = set()
    for pdir in plugin_dirs(claude_dir, project_dir):
        name = plugin_name(pdir)
        if name in seen:
            continue
        seen.add(name)
        rows += skill_rows(pdir / "skills", f"{name}:", f"plugin {name}")
    return rows


def render_table(project_dir: Path, rows: list[SkillRow]) -> str:
    lines = [
        f"# Skills inventory ({project_dir})",
        "",
        "| Skill | Scope | Path | Description |",
        "| --- | --- | --- | --- |",
    ]
    lines += [f"| {r.name} | {r.scope} | {r.path} | {r.description.replace('|', '/')} |" for r in rows]
    return "\n".join(lines) + "\n"


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--claude-dir", type=Path, default=None,
                        help="Claude config directory (default: ~/.claude)")
    parser.add_argument("--project-dir", type=Path, default=None,
                        help="project directory (default: CLAUDE_PROJECT_DIR, else the current directory)")
    parser.add_argument("--out", type=Path, default=None, help="write the table to FILE instead of stdout")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    claude_dir = args.claude_dir or default_claude_dir()
    project_dir = (args.project_dir or Path(os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd())).resolve()
    rows = build_rows(claude_dir, project_dir)
    text = render_table(project_dir, rows)
    if args.out:
        args.out.write_text(text, encoding="utf-8")
        print(f"{len(rows)} skills -> {args.out}")
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
