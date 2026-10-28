"""Check that an installed plugin directory holds only files committed at a git revision.

Read-only. Usage: python3 -B scripts/check_install.py [--repo DIR] [--rev REV] [--plugin-dir DIR]
Exit 0: match. Exit 1: unexpected, missing or changed files. Exit 2: bad plugin dir or git failure.
Files are compared by content: each installed file is hashed the way git hashes a blob.
"""
import argparse
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Set, Tuple

CACHE_PARTS = (".claude", "plugins", "cache", "claude-" + "model-routing")
MANIFEST = ".claude-plugin/plugin.json"
RUNTIME_DIR = ".in_use"  # written by Claude Code at the plugin root, one file per running session


class CheckError(Exception):
    pass


def default_plugin_dir(home: Path, name: str, version: str) -> Path:
    return Path(home).joinpath(*CACHE_PARTS, name, version)


def git_output(repo: str, *args: str) -> bytes:
    try:
        result = subprocess.run(
            ["git", "-C", repo, *args], capture_output=True, check=True
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise CheckError("git %s failed" % args[0]) from exc
    return result.stdout


def tracked_blobs(repo: str, rev: str) -> Dict[str, str]:
    out = git_output(repo, "ls-tree", "-r", "-z", rev)
    blobs = {}  # type: Dict[str, str]
    for record in out.decode("utf-8").split("\0"):
        if not record:
            continue
        meta, _, path = record.partition("\t")
        _mode, kind, oid = meta.split()
        if kind == "blob":
            blobs[path] = oid
    return blobs


def list_tracked(repo: str, rev: str) -> Set[str]:
    return set(tracked_blobs(repo, rev))


def blob_id(path: Path, oid_len: int = 40) -> str:
    try:
        if os.path.islink(path):
            data = os.fsencode(os.readlink(path))
        else:
            data = Path(path).read_bytes()
    except OSError as exc:
        raise CheckError("cannot read an installed file") from exc
    header = b"blob " + str(len(data)).encode("ascii") + b"\0"
    if oid_len == 64:
        return hashlib.sha256(header + data).hexdigest()
    return hashlib.sha1(header + data).hexdigest()


def changed(plugin_dir: Path, blobs: Dict[str, str], paths: Iterable[str]) -> List[str]:
    return sorted(
        p for p in paths if blob_id(Path(plugin_dir) / p, len(blobs[p])) != blobs[p]
    )


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


def read_manifest(repo: str, rev: str) -> Tuple[str, str]:
    raw = git_output(repo, "show", "%s:%s" % (rev, MANIFEST))
    try:
        data = json.loads(raw.decode("utf-8"))
        return str(data["name"]), str(data["version"])
    except (ValueError, KeyError, TypeError) as exc:
        raise CheckError("cannot read name and version from %s" % MANIFEST) from exc


def parse_args(argv: Optional[List[str]]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Fail if the installed plugin differs from the files committed at a revision."
    )
    parser.add_argument("--repo", default=".")
    parser.add_argument("--rev", default="HEAD")
    parser.add_argument("--plugin-dir", default=None)
    return parser.parse_args(argv)


def resolve_plugin_dir(args: argparse.Namespace) -> Path:
    if args.plugin_dir is not None:
        return Path(args.plugin_dir)
    name, version = read_manifest(args.repo, args.rev)
    return default_plugin_dir(Path.home(), name, version)


def report(unexpected: List[str], missing: List[str], modified: List[str]) -> None:
    for prefix, paths in (("unexpected", unexpected), ("missing", missing), ("changed", modified)):
        for path in paths:
            print("%s: %s" % (prefix, path))


def run(args: argparse.Namespace) -> int:
    plugin_dir = resolve_plugin_dir(args)
    if not plugin_dir.is_dir():
        raise CheckError("plugin directory does not exist")
    blobs = tracked_blobs(args.repo, args.rev)
    installed = list_installed(plugin_dir)
    unexpected, missing = compare(installed, set(blobs))
    modified = changed(plugin_dir, blobs, sorted(set(blobs) & installed))
    report(unexpected, missing, modified)
    if unexpected or missing or modified:
        print("FAIL: %d unexpected, %d missing, %d changed" % (
            len(unexpected), len(missing), len(modified)))
        return 1
    print("OK: %d files match %s" % (len(blobs), args.rev))
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
