"""Check that an installed plugin directory holds only files committed at a git revision.

Read-only. Usage: python3 -B scripts/check_install.py [--repo DIR] [--rev REV] [--plugin-dir DIR]
Exit 0: match. Exit 1: unexpected or missing files. Exit 2: bad plugin dir or git failure.
"""
import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import List, Optional, Set, Tuple

CACHE_PARTS = (".claude", "plugins", "cache", "claude-" + "model-routing", "model-routing")
MANIFEST = ".claude-plugin/plugin.json"
RUNTIME_DIR = ".in_use"  # written by Claude Code at the plugin root, one file per running session


class CheckError(Exception):
    pass


def default_plugin_dir(home: Path, version: str) -> Path:
    return Path(home).joinpath(*CACHE_PARTS, version)


def git_output(repo: str, *args: str) -> bytes:
    try:
        result = subprocess.run(
            ["git", "-C", repo, *args], capture_output=True, check=True
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise CheckError("git %s failed" % args[0]) from exc
    return result.stdout


def list_tracked(repo: str, rev: str) -> Set[str]:
    out = git_output(repo, "ls-tree", "-r", "--name-only", "-z", rev)
    return {n for n in out.decode("utf-8").split("\0") if n}


def list_installed(plugin_dir: Path) -> Set[str]:
    found = set()  # type: Set[str]
    root = str(plugin_dir)
    for current, dirs, files in os.walk(root, followlinks=False):
        rel_dir = os.path.relpath(current, root)
        if rel_dir == ".":
            dirs[:] = [d for d in dirs if d not in (".git", RUNTIME_DIR)]
            files = [f for f in files if f != ".git"]
        names = list(files) + [d for d in dirs if os.path.islink(os.path.join(current, d))]
        for name in names:
            rel = name if rel_dir == "." else os.path.join(rel_dir, name)
            found.add(Path(rel).as_posix())
    return found


def compare(installed: Set[str], tracked: Set[str]) -> Tuple[List[str], List[str]]:
    return sorted(installed - tracked), sorted(tracked - installed)


def read_version(repo: str, rev: str) -> str:
    raw = git_output(repo, "show", "%s:%s" % (rev, MANIFEST))
    try:
        return str(json.loads(raw.decode("utf-8"))["version"])
    except (ValueError, KeyError, TypeError) as exc:
        raise CheckError("cannot read version from %s" % MANIFEST) from exc


def parse_args(argv: Optional[List[str]]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Fail if the installed plugin differs from the files committed at a revision."
    )
    parser.add_argument("--repo", default=".")
    parser.add_argument("--rev", default="HEAD")
    parser.add_argument("--plugin-dir", default=None)
    return parser.parse_args(argv)


def run(args: argparse.Namespace) -> int:
    if args.plugin_dir is None:
        plugin_dir = default_plugin_dir(Path.home(), read_version(args.repo, args.rev))
    else:
        plugin_dir = Path(args.plugin_dir)
    if not plugin_dir.is_dir():
        raise CheckError("plugin directory does not exist")
    tracked = list_tracked(args.repo, args.rev)
    unexpected, missing = compare(list_installed(plugin_dir), tracked)
    for path in unexpected:
        print("unexpected: %s" % path)
    for path in missing:
        print("missing: %s" % path)
    if unexpected or missing:
        print("FAIL: %d unexpected, %d missing" % (len(unexpected), len(missing)))
        return 1
    print("OK: %d files match %s" % (len(tracked), args.rev))
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(argv)
    try:
        return run(args)
    except CheckError as exc:
        print(str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
