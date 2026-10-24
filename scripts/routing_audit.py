"""Audit one Claude Code session for Model Routing Policy compliance.

Usage:
  routing_audit.py [SESSION] [--claude-dir DIR] [--agent-type REGEX] [-v] [--out FILE]
  routing_audit.py --hook [--claude-dir DIR]    (SessionEnd event JSON on stdin)

SESSION is a session id, a session directory, a main transcript .jsonl or an
agent-*.jsonl file (see transcripts.resolve_session). The default output is a
Markdown report: agents per type, the executor mix and the flags. -v adds the
per-agent detail, --out writes the report to a file.

--hook never raises, prints nothing and always exits 0. It writes a report to
$CLAUDE_PLUGIN_DATA/audits/ only when CLAUDE_PLUGIN_DATA is set and the session
dispatched at least one tier agent.
"""
from __future__ import annotations

import argparse
import collections
import datetime
import json
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional, Sequence

import routing_config as rc
import transcripts as tr

PLANNER_CALL_NAMES = frozenset({"Read", "Grep", "Glob"})
SKILLS_RE = re.compile(r"\bSkills:[ \t]*\S")
ADVISOR_RE = re.compile(r"never consult the advisor", re.IGNORECASE)
PLUGIN_DATA_ENV = "CLAUDE_PLUGIN_DATA"


@dataclass(frozen=True)
class AgentRow:
    first: str
    last: str
    agent_type: Optional[str]
    prompt: str
    calls: tuple
    short_id: str


def _text_of(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return " ".join(
            str(x.get("text") or "") for x in content
            if isinstance(x, dict) and x.get("type") == "text"
        )
    return ""


def _tool_call(block, ts) -> Optional[tuple]:
    if not isinstance(block, dict) or block.get("type") not in ("tool_use", "server_tool_use"):
        return None
    inp = block.get("input")
    if not isinstance(inp, dict):
        inp = {}
    arg = (inp.get("file_path") or inp.get("pattern") or inp.get("command")
           or inp.get("skill") or "")
    return (ts, block.get("name"), str(arg)[:90])


def _scan_events(events: Iterable[dict]) -> tuple:
    prompt = ""
    calls: list = []
    stamps: list = []
    for event in events:
        ts = event.get("timestamp")
        if ts:
            stamps.append(ts)
        msg = event.get("message")
        content = msg.get("content") if isinstance(msg, dict) else None
        if event.get("type") == "user" and not prompt:
            prompt = _text_of(content)
        if event.get("type") == "assistant" and isinstance(content, list):
            calls.extend(c for c in (_tool_call(b, ts) for b in content) if c)
    return prompt, tuple(calls), stamps


def summarize(subagents: Sequence[Path], want: Optional[str] = None) -> tuple:
    """Read every subagent transcript into rows sorted by time."""
    rows = []
    for jsonl in subagents:
        agent_type = tr.read_agent_type(tr.meta_path_for(jsonl))
        if want and not re.search(want, agent_type or ""):
            continue
        prompt, calls, stamps = _scan_events(tr.read_jsonl(jsonl))
        rows.append(AgentRow(
            first=stamps[0] if stamps else "",
            last=stamps[-1] if stamps else "",
            agent_type=agent_type,
            prompt=prompt,
            calls=calls,
            short_id=jsonl.name[6:16],
        ))
    return tuple(sorted(rows, key=lambda r: (r.first, r.last, r.agent_type or "", r.short_id)))


def _bare_type(agent_type: Optional[str], config: rc.RoutingConfig) -> str:
    return rc.bare_name(agent_type, config) if agent_type else "unknown"


def _plan_re(config: rc.RoutingConfig) -> re.Pattern:
    return re.compile(config.plan_path_pattern)


def _hhmm(ts: Optional[str]) -> str:
    return ts[11:16] if ts else "-"


def _budget_labels(row: AgentRow, config: rc.RoutingConfig) -> list:
    budget = config.tunables["planner_evidence_budget"]
    used = sum(1 for _, name, _ in row.calls if name in PLANNER_CALL_NAMES)
    if used > budget:
        return [f"over the planner evidence budget ({used} calls)"]
    return []


def row_flags(row: AgentRow, config: rc.RoutingConfig) -> list:
    """Return the policy flags of one tier agent; non-tier agents get none."""
    tier = rc.resolve_tier(row.agent_type, config)
    if tier is None:
        return []
    labels = []
    if not SKILLS_RE.search(row.prompt):
        labels.append("missing Skills line")
    if not rc.role_of(tier, config).uses_advisor and not ADVISOR_RE.search(row.prompt):
        labels.append("no 'Never consult the advisor' line")
    if tier.role == "executor" and not _plan_re(config).search(row.prompt):
        labels.append("no planner plan (fast lane or ops?)")
    if tier.role == "planner":
        labels.extend(_budget_labels(row, config))
    if tier.name in config.audit_flag_every_use:
        labels.append(f"{tier.name}: every-use tier, check the escalation reason")
    return labels


def non_tier_lines(rows: Sequence[AgentRow], config: rc.RoutingConfig) -> list:
    """Flag each distinct non-tier agent type, but only in a session with a tier."""
    if not dispatched_tier(rows, config):
        return []
    others = {r.agent_type for r in rows
              if r.agent_type and rc.resolve_tier(r.agent_type, config) is None}
    return [f"- non-tier agent `{name}` dispatched" for name in sorted(others)]


def flag_lines(rows: Sequence[AgentRow], config: rc.RoutingConfig) -> list:
    lines = [f"- {_bare_type(r.agent_type, config)} `{r.short_id}` ({_hhmm(r.first)} UTC): {label}"
             for r in rows for label in row_flags(r, config)]
    return lines + non_tier_lines(rows, config)


def dispatched_tier(rows: Sequence[AgentRow], config: rc.RoutingConfig) -> bool:
    return any(rc.resolve_tier(r.agent_type, config) is not None for r in rows)


def _executor_name(row: AgentRow, config: rc.RoutingConfig) -> Optional[str]:
    tier = rc.resolve_tier(row.agent_type, config)
    return tier.name if tier is not None and tier.role == "executor" else None


def executor_mix(rows: Sequence[AgentRow], config: rc.RoutingConfig) -> list:
    execs = [n for n in (_executor_name(r, config) for r in rows) if n]
    total = len(execs)

    def share(pred) -> str:
        k = sum(1 for name in execs if pred(name))
        return f"{100.0 * k / total:.1f}%" if total else "n/a"

    return [
        f"- exec-sonnet-high: {share(lambda t: t == 'exec-sonnet-high')}",
        f"- exec-sonnet-xhigh: {share(lambda t: t == 'exec-sonnet-xhigh')}",
        f"- Sonnet overall: {share(lambda t: t.startswith('exec-sonnet'))}",
        f"- Haiku overall: {share(lambda t: t.startswith('exec-haiku'))}",
    ]


def count_lines(rows: Sequence[AgentRow], config: rc.RoutingConfig) -> list:
    counts = collections.Counter(_bare_type(r.agent_type, config) for r in rows)
    return [f"- {name}: {n}" for name, n in sorted(counts.items())] or ["- none"]


def span(rows: Sequence[AgentRow]) -> str:
    firsts = [r.first for r in rows if r.first]
    lasts = [r.last for r in rows if r.last]
    if not firsts:
        return "no timestamps"
    return f"{min(firsts)[:16]} to {max(lasts)[:16]} UTC"


def _detail_header(row: AgentRow, config: rc.RoutingConfig, plan_re: re.Pattern) -> str:
    plan = plan_re.search(row.prompt)
    task = re.search(r"task(?: ID)?[:\s]+([A-Z][\w.-]*\d[\w.-]*)", row.prompt)
    skills = re.search(r"Skills:\s*([^\n]*)", row.prompt)
    return (f"{row.first[11:16]}-{row.last[11:16]} {_bare_type(row.agent_type, config)} "
            f"{row.short_id} prompt={len(row.prompt)}ch "
            f"plan={plan.group(0) if plan else '-'} "
            f"task={task.group(1) if task else '-'} "
            f"skills={(skills.group(1)[:60] if skills else 'MISSING')}")


def detail_lines(rows: Sequence[AgentRow], config: rc.RoutingConfig) -> list:
    out = []
    plan_re = _plan_re(config)
    for row in rows:
        counts = collections.Counter(name for _, name, _ in row.calls)
        first_write = next((ts for ts, name, _ in row.calls if name == "Write"), None)
        out.append(_detail_header(row, config, plan_re))
        out.append(f"   calls={dict(counts)} firstWrite={_hhmm(first_write)}")
        out.extend(f"     {(ts or '')[11:19]} {name} {arg}" for ts, name, arg in row.calls)
    return out


def render(label: str, rows: Sequence[AgentRow], verbose: bool, config: rc.RoutingConfig) -> str:
    lines = [f"# Routing audit: {label}", "", f"Span: {span(rows)}", "",
             f"Agents: {len(rows)}", "", "## Agents per type", *count_lines(rows, config), "",
             "## Executor mix", *executor_mix(rows, config), "",
             "## Flags", *(flag_lines(rows, config) or ["None"]), ""]
    if verbose:
        lines += ["## Agent detail", "```", *detail_lines(rows, config), "```", ""]
    return "\n".join(lines)


def run_hook(raw: str, claude_dir: Path) -> Optional[Path]:
    """Write the SessionEnd audit when plugin data is set and a tier was dispatched."""
    data_dir = os.environ.get(PLUGIN_DATA_ENV)
    if not data_dir:
        return None
    event = json.loads(raw)
    if not isinstance(event, dict):
        raise ValueError("SessionEnd event must be a JSON object")
    ref = event.get("transcript_path") or event.get("session_id")
    if not ref:
        raise ValueError("SessionEnd event has no transcript_path or session_id")
    files = tr.resolve_session(str(ref), claude_dir)
    config = rc.load_config()
    rows = summarize(files.subagents)
    if not dispatched_tier(rows, config):
        return None
    sid = str(event.get("session_id") or files.session_id)
    out_dir = Path(data_dir) / "audits"
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{datetime.date.today().isoformat()}-{sid[:8]}.md"
    path.write_text(render(files.session_id, rows, False, config), encoding="utf-8")
    return path


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="Audit a session for Model Routing Policy compliance.")
    ap.add_argument("target", nargs="?", help="session id, session dir, or transcript .jsonl")
    ap.add_argument("--claude-dir", type=Path, default=None,
                    help="Claude Code config directory (default ~/.claude)")
    ap.add_argument("--agent-type", metavar="REGEX", help="only agents whose type matches")
    ap.add_argument("-v", "--verbose", action="store_true", help="per-agent detail and tool calls")
    ap.add_argument("--out", metavar="FILE", help="write the report to FILE instead of stdout")
    ap.add_argument("--hook", action="store_true", help="SessionEnd mode: event JSON on stdin")
    return ap


def _hook_main(claude_dir: Path) -> int:
    try:
        run_hook(sys.stdin.read(), claude_dir)
    except Exception:  # hook mode must never fail a session end
        pass
    return 0


def main(argv: Optional[list] = None) -> int:
    ap = build_parser()
    args = ap.parse_args(argv)
    claude_dir = args.claude_dir or tr.default_claude_dir()
    if args.hook:
        return _hook_main(claude_dir)
    if not args.target:
        ap.error("target is required unless --hook is given")
    try:
        config = rc.load_config()
        files = tr.resolve_session(args.target, claude_dir)
    except (tr.SessionNotFound, rc.ConfigError) as exc:
        print(f"routing_audit: {exc}", file=sys.stderr)
        return 2
    rows = summarize(files.subagents, args.agent_type)
    report = render(files.session_id, rows, args.verbose, config)
    if args.out:
        Path(args.out).write_text(report, encoding="utf-8")
    else:
        sys.stdout.write(report)
    return 0


if __name__ == "__main__":
    sys.exit(main())
