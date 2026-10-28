"""Session resolution and JSONL reading for Claude Code transcripts."""
from __future__ import annotations

import glob
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import NamedTuple, Optional, Tuple


class SessionNotFound(Exception):
    """Raised when a session reference matches no transcript on disk."""


@dataclass(frozen=True)
class SessionFiles:
    session_id: str
    main: Optional[Path]
    subagents: Tuple[Path, ...]


class RequestUsage(NamedTuple):
    """One model request (deduplicated by message id) and its prompt size."""

    message_id: str
    model: str
    prompt_tokens: int


PROMPT_USAGE_KEYS = ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens")


def _count(value) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


def request_usage(events) -> Tuple[RequestUsage, ...]:
    """Return one RequestUsage per assistant message id, in first-appearance order.

    The last record per id wins; the prompt is input plus both cache token counts.
    """
    latest: dict = {}
    for record in events:
        message = record.get("message")
        if record.get("type") != "assistant" or not isinstance(message, dict):
            continue
        message_id, usage = message.get("id"), message.get("usage")
        if not isinstance(message_id, str) or not message_id or not isinstance(usage, dict):
            continue
        prompt = sum(_count(usage.get(key)) for key in PROMPT_USAGE_KEYS)
        latest[message_id] = RequestUsage(message_id, message.get("model") or "", prompt)
    return tuple(latest.values())


def default_claude_dir() -> Path:
    """Return the Claude Code config directory of the current user."""
    return Path.home() / ".claude"


def _is_agent_file(path: Path) -> bool:
    return path.name.startswith("agent-") and path.name.endswith(".jsonl")


def _subagent_files(session_dir: Path) -> Tuple[Path, ...]:
    sub = session_dir / "subagents"
    if not sub.is_dir():
        return ()
    return tuple(sorted(sub.glob("agent-*.jsonl")))


def _session_from_dir(session_dir: Path) -> SessionFiles:
    main = session_dir.with_name(session_dir.name + ".jsonl")
    has_main = main.is_file()
    if not has_main and not session_dir.is_dir():
        raise SessionNotFound(f"no transcript at {session_dir}")
    return SessionFiles(
        session_id=session_dir.name,
        main=main if has_main else None,
        subagents=_subagent_files(session_dir),
    )


def _find_session_dir(ref: str, claude_dir: Path) -> Optional[Path]:
    if os.path.isdir(ref):
        return Path(os.path.abspath(ref))
    root = os.path.join(str(claude_dir), "projects")
    for hit in sorted(glob.glob(os.path.join(root, "*", ref))):
        if os.path.isdir(hit):
            return Path(os.path.abspath(hit))
    return None


def resolve_session(ref: str, claude_dir: Path) -> SessionFiles:
    """Resolve a session id, session directory, main .jsonl or agent-*.jsonl."""
    if not ref:
        raise SessionNotFound("empty session reference")
    if ref.endswith(".jsonl"):
        path = Path(ref)
        if _is_agent_file(path):
            return SessionFiles(session_id=path.stem, main=None, subagents=(path,))
        return _session_from_dir(Path(os.path.abspath(ref[: -len(".jsonl")])))
    session_dir = _find_session_dir(ref, claude_dir)
    if session_dir is None:
        root = Path(claude_dir) / "projects"
        raise SessionNotFound(f"no session for {ref} under {root}")
    return _session_from_dir(session_dir)


def read_jsonl(path: Path) -> Tuple[dict, ...]:
    """Return the dict records of a JSONL file, skipping blank and malformed lines."""
    records = []
    with open(path, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                value = json.loads(line)
            except ValueError:
                continue
            if isinstance(value, dict):
                records.append(value)
    return tuple(records)


def meta_path_for(jsonl: Path) -> Path:
    """Return the agent-*.meta.json sibling of an agent-*.jsonl file."""
    return jsonl.with_name(jsonl.name[: -len(".jsonl")] + ".meta.json")


def read_agent_type(meta: Path) -> Optional[str]:
    """Return the agentType recorded in a meta file, or None when unreadable."""
    try:
        with open(meta, encoding="utf-8") as fh:
            value = json.load(fh)
    except (OSError, ValueError):
        return None
    agent_type = value.get("agentType") if isinstance(value, dict) else None
    return agent_type if isinstance(agent_type, str) else None
