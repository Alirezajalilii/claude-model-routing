"""Scan a git repository, and optionally its history, for sensitive data.

Exit codes: 0 no findings, 1 findings, 2 any error (reason on stderr).
Rules and text handling live in sensitive_rules.py; this module talks to git.
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Sequence

from sensitive_rules import (
    DenyFileError,
    Finding,
    compile_deny,
    scan_content,
    scan_text,
    scan_unit,
)

LIMITATIONS = """Limitations:
- IPv6 addresses are not matched; list known private IPv6 addresses in the deny file.
- Default mode reads worktree files, not staged content; run the gate on a clean worktree with --history.
- secret-assignment matches only key names that end with the keyword (DB_PASSWORD, API_KEY); names such as SECRET_KEY_BASE rely on the token rules or the deny file.
- Reflogs, unreachable objects and stashes outside refs are not scanned; they are never pushed.
- Encodings other than UTF-8, UTF-16 and UTF-32 are read as UTF-8 with replacement or as binary strings.
"""

TAG_PREFIX = "refs/tags/"
IDENTITY_KEYWORDS = frozenset({"author", "committer", "tagger"})
REF_FORMAT = "--format=%(objectname)%00%(objecttype)%00%(refname)"


class ScanError(Exception):
    """Any condition that ends the scan with exit code 2."""


def _git(root: Path, args: Sequence[str], input: bytes | None = None) -> bytes:
    try:
        result = subprocess.run(
            ["git", "-C", str(root), *args],
            input=input,
            capture_output=True,
            check=False,
        )
    except FileNotFoundError as exc:
        raise ScanError("git is not installed") from exc
    if result.returncode != 0:
        detail = result.stderr.decode("utf-8", "replace").strip()
        raise ScanError(f"git {' '.join(args)} failed: {detail}")
    return result.stdout


def _decode(data: bytes) -> str:
    return data.decode("utf-8", "replace")


def _split_nul(data: bytes) -> list[str]:
    return [part for part in _decode(data).split("\0") if part]


def _split_lines(data: bytes) -> list[str]:
    return [line for line in _decode(data).split("\n") if line]


def _note(message: str) -> None:
    print(message, file=sys.stderr)


def _resolve_root(root_arg: str) -> Path:
    top = _git(Path(root_arg), ["rev-parse", "--show-toplevel"])
    return Path(_decode(top).strip())


def _load_deny(path: Path | None) -> tuple[re.Pattern[str], ...]:
    if path is None:
        return ()
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError) as exc:
        raise ScanError(f"cannot read deny file {path}: {exc}") from exc
    return compile_deny(lines)


def _worktree_paths(root: Path) -> tuple[str, ...]:
    tracked = _split_nul(_git(root, ["ls-files", "-z"]))
    untracked = _split_nul(_git(root, ["ls-files", "-z", "--others", "--exclude-standard"]))
    return tuple(dict.fromkeys(tracked + untracked))


def _read_file(path: Path) -> bytes:
    if path.is_symlink():
        return os.fsencode(os.readlink(path))
    return path.read_bytes()


def _worktree_bytes(root: Path, name: str) -> bytes | None:
    path = root / name
    try:
        if path.is_dir() and not path.is_symlink():
            _note(f"note: {name} is a directory (submodule); content not scanned")
            return None
        if not path.is_symlink() and not path.exists():
            _note(
                f"note: {name} is missing from the worktree; "
                "its committed content is covered by --history"
            )
            return None
        return _read_file(path)
    except OSError as exc:
        raise ScanError(f"cannot read {name}: {exc}") from exc


def _scan_worktree(root: Path, deny: Sequence[re.Pattern[str]]) -> list[Finding]:
    paths = _worktree_paths(root)
    found: list[Finding] = []
    for name in paths:
        found.extend(scan_unit(name, f"name {name}", deny))
    for name in paths:
        data = _worktree_bytes(root, name)
        if data is not None:
            found.extend(scan_content(data, name, deny, path=name))
    return found


def _history_path_names(root: Path) -> list[str]:
    names: dict[str, None] = {}
    for commit in _split_lines(_git(root, ["rev-list", "--all"])):
        listing = _git(root, ["ls-tree", "-r", "-t", "-z", "--name-only", commit])
        names.update(dict.fromkeys(_split_nul(listing)))
    return list(names)


def _object_paths(root: Path) -> dict[str, str]:
    first_paths: dict[str, str] = {}
    for line in _split_lines(_git(root, ["rev-list", "--objects", "--all"])):
        sha, _, path = line.partition(" ")
        first_paths.setdefault(sha, path)
    return first_paths


def _ref_records(root: Path) -> list[tuple[str, str, str]]:
    records: list[tuple[str, str, str]] = []
    for line in _split_lines(_git(root, ["for-each-ref", REF_FORMAT])):
        parts = line.split("\0")
        if len(parts) != 3:
            raise ScanError(f"unparseable for-each-ref line: {line!r}")
        records.append((parts[0], parts[1], parts[2]))
    return records


def _read_objects(root: Path, ids: list[str]) -> dict[str, tuple[str, bytes]]:
    if not ids:
        return {}
    request = "".join(f"{sha}\n" for sha in ids).encode("ascii")
    output = _git(root, ["cat-file", "--batch"], input=request)
    objects: dict[str, tuple[str, bytes]] = {}
    position = 0
    for sha in ids:
        header_end = output.find(b"\n", position)
        if header_end < 0:
            raise ScanError("git cat-file: output ended before every object")
        header = output[position:header_end].split(b" ")
        if len(header) != 3:
            raise ScanError(f"git cat-file: object {sha} is missing")
        size = int(header[2].decode("ascii"))
        start = header_end + 1
        end = start + size
        if end >= len(output) or output[end:end + 1] != b"\n":
            raise ScanError(f"git cat-file: object {sha} is shorter than announced")
        objects[sha] = (header[1].decode("ascii"), output[start:end])
        position = end + 1
    return objects


def _declared_encoding(raw: bytes) -> str:
    header = raw.partition(b"\n\n")[0]
    for line in header.split(b"\n"):
        if line.startswith(b"encoding "):
            return line[len(b"encoding "):].decode("ascii", "replace").strip()
    return "utf-8"


def _decode_object(raw: bytes) -> str:
    try:
        return raw.decode(_declared_encoding(raw), "replace")
    except (LookupError, TypeError, ValueError):
        return raw.decode("utf-8", "replace")


def _header_findings(header: str, label: str, deny: Sequence[re.Pattern[str]]) -> list[Finding]:
    found: list[Finding] = []
    for number, line in enumerate(header.split("\n"), start=1):
        keyword, separator, _ = line.partition(" ")
        if separator and keyword in IDENTITY_KEYWORDS:
            location = f"{label} {keyword}"
        else:
            location = f"{label} header:{number}"
        found.extend(scan_unit(line, location, deny))
    return found


def _object_findings(label: str, raw: bytes, deny: Sequence[re.Pattern[str]]) -> list[Finding]:
    text = _decode_object(raw)
    header, _, message = text.partition("\n\n")
    found = _header_findings(header, label, deny)
    found.extend(scan_text(message, f"{label} message", deny))
    return found


def _blob_findings(sha: str, path: str, data: bytes, deny: Sequence[re.Pattern[str]]) -> list[Finding]:
    label = f"history {sha[:8]} {path}" if path else f"history {sha[:8]}"
    return list(scan_content(data, label, deny, path=path or None))


def _tag_name(refname: str) -> str:
    return refname[len(TAG_PREFIX):] if refname.startswith(TAG_PREFIX) else refname


def _scan_history_objects(
    root: Path,
    refs: list[tuple[str, str, str]],
    deny: Sequence[re.Pattern[str]],
) -> list[Finding]:
    first_paths = _object_paths(root)
    ids = list(dict.fromkeys([*first_paths, *(sha for sha, _, _ in refs)]))
    objects = _read_objects(root, ids)
    found: list[Finding] = []
    for sha in ids:
        objtype, data = objects[sha]
        if objtype == "blob":
            found.extend(_blob_findings(sha, first_paths.get(sha, ""), data, deny))
        elif objtype == "commit":
            found.extend(_object_findings(f"commit {sha[:8]}", data, deny))
    for sha, objtype, refname in refs:
        if objtype == "tag":
            label = f"tag {_tag_name(refname)}"
            found.extend(_object_findings(label, objects[sha][1], deny))
    return found


def _scan_history(root: Path, deny: Sequence[re.Pattern[str]]) -> list[Finding]:
    found: list[Finding] = []
    for name in _history_path_names(root):
        found.extend(scan_unit(name, f"history name {name}", deny))
    refs = _ref_records(root)
    found.extend(_scan_history_objects(root, refs, deny))
    for _, _, refname in refs:
        found.extend(scan_unit(refname, f"ref {refname}", deny))
    return found


def _collect(args: argparse.Namespace) -> list[Finding]:
    root = _resolve_root(args.root)
    deny = _load_deny(args.deny_file)
    findings = _scan_worktree(root, deny)
    if args.history:
        findings.extend(_scan_history(root, deny))
    return findings


def _report(findings: list[Finding]) -> int:
    unique = list(dict.fromkeys(findings))
    if not unique:
        print("no findings")
        return 0
    for finding in unique:
        print(f"{finding.location}: {finding.rule}: {finding.excerpt}")
    print(f"{len(unique)} findings")
    return 1


def _fail(message: str) -> int:
    print(message, file=sys.stderr)
    return 2


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Scan a git repository for sensitive data.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=LIMITATIONS,
    )
    parser.add_argument(
        "--root",
        default=".",
        help="directory inside the repository to scan (default: current directory)",
    )
    parser.add_argument(
        "--history",
        action="store_true",
        help="also scan committed content: path names, blobs, commits, tags and refs",
    )
    parser.add_argument(
        "--deny-file",
        type=Path,
        default=None,
        help="file of extra case-insensitive regexes, one per line; lines starting with # are comments",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        findings = _collect(args)
    except ScanError as exc:
        return _fail(f"scan_sensitive: {exc}")
    except DenyFileError as exc:
        return _fail(f"scan_sensitive: deny file: {exc}")
    except Exception as exc:  # every unexpected failure is exit 2
        return _fail(f"scan_sensitive: internal error: {type(exc).__name__}: {exc}")
    return _report(findings)


if __name__ == "__main__":
    sys.exit(main())
