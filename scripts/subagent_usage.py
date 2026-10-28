#!/usr/bin/env python3
"""Report model, effort and token usage for Claude Code subagent transcripts.

Port of ~/.claude/scripts/subagent-usage.py onto transcripts.py. Used by the
Model Routing Policy to check that a tier agent ran with the model and effort
its definition declares, and to take input/output/cache token numbers for the
routing log.

Usage:
  subagent_usage.py <session-id | session dir | session.jsonl | agent-*.jsonl> ...
      [--claude-dir DIR] [--agent-type NAME] [--json]

Usage is deduplicated by message id (streamed entries repeat a message; the
last entry carries the final output_tokens).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import routing_config as rc
import transcripts as tr

USAGE_KEYS = ("input_tokens", "output_tokens", "cache_creation_input_tokens", "cache_read_input_tokens")
REPORT_HEAD_CHARS = 160


@dataclass
class _Acc:
    """Mutable fold state for one transcript; local to a single summarize call."""

    usage_by_message: dict = field(default_factory=dict)
    first_message_id: Optional[str] = None
    resolved_models: set = field(default_factory=set)
    request_models: set = field(default_factory=set)
    request_efforts: set = field(default_factory=set)
    recorded_efforts: set = field(default_factory=set)
    request_count: int = 0
    request_tools: set = field(default_factory=set)
    tool_calls: list = field(default_factory=list)
    skill_calls: list = field(default_factory=list)
    advisor_unkeyed_calls: int = 0
    advisor_answered_ids: set = field(default_factory=set)
    advisor_results: list = field(default_factory=list)
    final_text: str = ""


def _tool_label(tool: dict) -> str:
    return tool.get("name") or tool.get("type") or "?"


def _note_request(acc: _Acc, entry: dict) -> None:
    acc.request_count += 1
    params = entry.get("params") or {}
    for tool in params.get("tools") or []:
        acc.request_tools.add(_tool_label(tool))
    if params.get("model"):
        acc.request_models.add(params["model"])
    acc.request_efforts.add((params.get("output_config") or {}).get("effort", "<not sent>"))


def _skill_md_read(block: dict) -> Optional[str]:
    """Return the SKILL.md path when a Read tool_use loads a skill file, else None."""
    path = (block.get("input") or {}).get("file_path")
    return path if isinstance(path, str) and path.endswith("/SKILL.md") else None


def _note_advisor_call(acc: _Acc, block: dict) -> None:
    """Advisor calls are counted by result, so an attempt without a result is not a call.

    A call block with no id cannot be matched to a result; it still counts as one attempt.
    """
    if not block.get("id"):
        acc.advisor_unkeyed_calls += 1


def _note_advisor_result(acc: _Acc, block: dict) -> None:
    """Record each answered advisor call once, keyed by tool_use_id; non-dict content is type "?"."""
    content = block.get("content")
    result_type = content.get("type", "?") if isinstance(content, dict) else "?"
    call_id = block.get("tool_use_id")
    if call_id is None:
        acc.advisor_results.append(result_type)
    elif call_id not in acc.advisor_answered_ids:
        acc.advisor_answered_ids.add(call_id)
        acc.advisor_results.append(result_type)


def _note_block(acc: _Acc, block: dict) -> None:
    kind = block.get("type")
    if kind == "tool_use":
        name = block.get("name", "?")
        acc.tool_calls.append(name)
        if name == "Skill":
            acc.skill_calls.append(str((block.get("input") or {}).get("skill", "?")))
        elif name == "Read" and _skill_md_read(block):
            acc.skill_calls.append(_skill_md_read(block))
    elif kind == "server_tool_use" and block.get("name") == "advisor":
        _note_advisor_call(acc, block)
    elif kind == "advisor_tool_result":
        _note_advisor_result(acc, block)
    elif kind == "text" and block.get("text", "").strip():
        acc.final_text = block["text"].strip()


def _note_assistant(acc: _Acc, entry: dict) -> None:
    message = entry.get("message") or {}
    if message.get("model"):
        acc.resolved_models.add(message["model"])
    for key in ("effort", "perTurnEffort"):
        if entry.get(key):
            acc.recorded_efforts.add(f"{key}={entry[key]}")
    for block in message.get("content") or []:
        if isinstance(block, dict):
            _note_block(acc, block)
    message_id = message.get("id")
    if message_id and message.get("usage"):
        acc.first_message_id = acc.first_message_id or message_id
        acc.usage_by_message[message_id] = message["usage"]


def _note_entry(acc: _Acc, entry: dict) -> None:
    kind = entry.get("type")
    if kind == "api-request-shape":
        for tool in (entry.get("shape") or {}).get("tools") or []:
            acc.request_tools.add(_tool_label(tool))
    elif kind == "api-request":
        _note_request(acc, entry)
    elif kind == "assistant":
        _note_assistant(acc, entry)


def _read_meta(transcript: Path) -> dict:
    meta = tr.meta_path_for(transcript)
    try:
        with open(meta, encoding="utf-8") as fh:
            value = json.load(fh)
    except (OSError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def _row(transcript: Path, acc: _Acc, meta: dict, requests: tuple) -> dict:
    totals = {key: sum(u.get(key, 0) for u in acc.usage_by_message.values()) for key in USAGE_KEYS}
    first = acc.usage_by_message.get(acc.first_message_id, {})
    head = acc.final_text.splitlines()[0][:REPORT_HEAD_CHARS] if acc.final_text else ""
    return {
        "transcript": str(transcript),
        "agent_type": meta.get("agentType") or "?",
        "model_alias": meta.get("model", "?"),
        "resolved_models": sorted(acc.resolved_models),
        "request_models": sorted(acc.request_models),
        "request_effort": sorted(acc.request_efforts) or ["<no api-request entries>"],
        "recorded_effort": sorted(acc.recorded_efforts),
        "api_requests": acc.request_count,
        "request_tools": sorted(acc.request_tools),
        "tool_calls": acc.tool_calls,
        "skill_calls": acc.skill_calls,
        "advisor_calls": acc.advisor_unkeyed_calls + len(acc.advisor_answered_ids),
        "advisor_results": acc.advisor_results,
        "report_first_line": head,
        "messages": len(acc.usage_by_message),
        "first_turn_prompt_tokens": sum(
            first.get(k, 0) for k in ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens")),
        **totals,
        "peak_prompt_tokens": max((r.prompt_tokens for r in requests), default=0),
    }


def summarize(transcript: Path) -> dict:
    """Fold one agent-*.jsonl transcript into a report row."""
    acc = _Acc()
    events = tr.read_jsonl(transcript)
    for entry in events:
        _note_entry(acc, entry)
    return _row(transcript, acc, _read_meta(transcript), tr.request_usage(events))


def _collect(targets: list, claude_dir: Path) -> list:
    rows = []
    for target in targets:
        files = tr.resolve_session(os.path.expanduser(target), claude_dir)
        rows.extend(summarize(path) for path in files.subagents)
    return rows


def _is_wanted(row: dict, want: str, config: rc.RoutingConfig) -> bool:
    """Match on bare names, so a scoped and a bare agent type compare equal."""
    if row["agent_type"] == "?":
        return False
    return rc.bare_name(row["agent_type"], config) == rc.bare_name(want, config)


def _print_row(r: dict) -> None:
    print(f"{r['agent_type']}  alias={r['model_alias']}  model={','.join(r['resolved_models']) or '?'}"
          f"  request_effort={','.join(r['request_effort'])}  recorded={','.join(r['recorded_effort']) or '-'}")
    print(f"  tokens: input={r['input_tokens']} output={r['output_tokens']}"
          f" cache_write={r['cache_creation_input_tokens']} cache_read={r['cache_read_input_tokens']}"
          f"  first_turn_prompt={r['first_turn_prompt_tokens']}  peak_prompt={r['peak_prompt_tokens']}"
          f"  messages={r['messages']}")
    print(f"  tools_offered={','.join(r['request_tools']) or '?'}  tool_calls={','.join(r['tool_calls']) or '-'}")
    print(f"  skill_calls={','.join(r['skill_calls']) or '-'}  advisor_calls={r['advisor_calls']}"
          f" advisor_results={','.join(r['advisor_results']) or '-'}")
    print(f"  report: {r['report_first_line']}")
    print(f"  {r['transcript']}")


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("targets", nargs="+", metavar="TARGET",
                    help="session id, session dir, session .jsonl, or agent-*.jsonl")
    ap.add_argument("--claude-dir", type=Path, default=None,
                    help="Claude Code config directory (default ~/.claude)")
    ap.add_argument("--agent-type", metavar="NAME",
                    help="only agents whose bare type equals NAME (plugin scope ignored)")
    ap.add_argument("--json", action="store_true", help="print the rows as JSON")
    return ap


def main(argv: Optional[list] = None) -> int:
    args = build_parser().parse_args(argv)
    claude_dir = args.claude_dir or tr.default_claude_dir()
    try:
        config = rc.load_config()
        rows = _collect(args.targets, claude_dir)
    except (tr.SessionNotFound, rc.ConfigError, OSError) as exc:
        print(f"subagent_usage: {exc}", file=sys.stderr)
        return 2
    if args.agent_type:
        rows = [r for r in rows if _is_wanted(r, args.agent_type, config)]
    if args.json:
        json.dump(rows, sys.stdout, indent=2)
        print()
        return 0
    for row in rows:
        _print_row(row)
    return 0


if __name__ == "__main__":
    sys.exit(main())
