"""Session resolution and JSONL reading for Claude Code transcripts."""
from __future__ import annotations

import glob
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, NamedTuple, Optional, Tuple

DISPATCH_TOOLS = ("Agent", "Task")


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


def _find_main_transcript(ref: str, claude_dir: Path) -> Optional[Path]:
    """Return <claude>/projects/*/<ref>.jsonl when it exists (no subagent folder needed)."""
    root = os.path.join(str(claude_dir), "projects")
    for hit in sorted(glob.glob(os.path.join(root, "*", ref + ".jsonl"))):
        if os.path.isfile(hit):
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
        transcript = _find_main_transcript(ref, claude_dir)
        if transcript is None:
            root = Path(claude_dir) / "projects"
            raise SessionNotFound(f"no session for {ref} under {root}")
        return _session_from_dir(Path(os.path.abspath(str(transcript)[: -len(".jsonl")])))
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


def agent_id_of(jsonl: Path) -> str:
    """Return <id> of an agent-<id>.jsonl file."""
    return jsonl.name[len("agent-"): -len(".jsonl")]


def agent_type_of(jsonl: Path, dispatched: Mapping[str, str]) -> Optional[str]:
    """Return the agent type from the agent's meta file, else from its dispatch record, else None."""
    return read_agent_type(meta_path_for(jsonl)) or dispatched.get(agent_id_of(jsonl))


def _content_blocks(record: dict) -> list:
    message = record.get("message")
    content = message.get("content") if isinstance(message, dict) else None
    return [block for block in content if isinstance(block, dict)] if isinstance(content, list) else []


def _dispatch_inputs(events) -> dict:
    """Map the id of each Agent or Task tool_use to the subagent_type it was called with."""
    types: dict = {}
    for record in events:
        for block in _content_blocks(record):
            if block.get("type") != "tool_use" or block.get("name") not in DISPATCH_TOOLS:
                continue
            tool_input = block.get("input")
            subagent_type = tool_input.get("subagent_type") if isinstance(tool_input, dict) else None
            if isinstance(block.get("id"), str) and isinstance(subagent_type, str) and subagent_type:
                types[block["id"]] = subagent_type
    return types


def dispatched_agent_types(events) -> dict:
    """Map each agent id an Agent or Task call returned to the subagent_type it was dispatched with.

    The id is the agentId of the toolUseResult on the record that holds the matching tool_result.
    """
    types = _dispatch_inputs(events)
    found: dict = {}
    for record in events:
        result = record.get("toolUseResult")
        agent_id = result.get("agentId") if isinstance(result, dict) else None
        if not isinstance(agent_id, str) or not agent_id:
            continue
        for block in _content_blocks(record):
            tool_id = block.get("tool_use_id")
            if block.get("type") == "tool_result" and isinstance(tool_id, str) and tool_id in types:
                found.setdefault(agent_id, types[tool_id])
    return found


def parent_main_transcript(agent_jsonl: Path) -> Optional[Path]:
    """Return the main transcript of the session whose subagents folder holds agent_jsonl, if it exists."""
    session_dir = agent_jsonl.parent.parent
    main = session_dir.with_name(session_dir.name + ".jsonl")
    return main if main.is_file() else None


def dispatch_types_of(files: SessionFiles) -> dict:
    """Return agentId -> subagent_type for a session, read once from its main transcript."""
    main = files.main
    if main is None and files.subagents:
        main = parent_main_transcript(files.subagents[0])
    return {} if main is None else dispatched_agent_types(read_jsonl(main))
