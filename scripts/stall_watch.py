"""Stall watch: a PreToolUse hook that spots a stuck subagent while it runs.

Two signals mark a stall: the same call repeated within the last few calls with no
file change in between (the repeat signal), and a long run of read-only calls in a
row (the reads signal). A call is the same when its tool and its key fields are equal;
the key fields come from stall_watch.call_key_fields in the config, so a changing Bash
description does not make a repeat look new. The first signal in a run gets a nudge: the call is not run
and the agent is told to change course. When the agent stalls again beyond the
allowed nudges, the watch cuts it: every tool except the hand-back tool is denied
until the agent writes its Output file and replies BLOCKED.

The hook keeps per-agent state in $CLAUDE_PLUGIN_DATA/stall-watch/<agent_id>.json,
read and written under an exclusive lock. It fails open: any error lets the call
through with nothing on stdout, and a denial is one line on stderr with exit 2.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, Optional, TextIO, Tuple

try:
    import fcntl
except ImportError:  # no flock on this platform: the watch fails open
    fcntl = None

import routing_config as rc

BASH_TOOL = "Bash"
BASH_COMMAND_KEY = "command"
WAIT_TOOL = "Monitor"
SEGMENT_SPLIT = re.compile(r"&&|\|\||[;|\n]")
STATE_VERSION = 1
PLUGIN_DATA_ENV = "CLAUDE_PLUGIN_DATA"
STATE_DIR_NAME = "stall-watch"
SAFE_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
STATE_FILE = re.compile(r"^[A-Za-z0-9_-]{1,64}\.json$")
HOUR_SECONDS = 3600
REPEAT_SIGNAL = "same {tool} call {count} times"
READS_SIGNAL = "{count} read-only calls in a row"
REPEAT_NUDGE = (
    "{prefix} you made this exact {tool} call {count} times without a new file change "
    "in between, so this one was not run: it would give the same result. Change your "
    "approach: re-read your task, then make the next change."
)
WAIT_HINT = (
    " If you are waiting for a command to finish, run it in the background and wait "
    "with {wait}; {wait} calls are not counted."
)
READS_NUDGE = (
    "{prefix} {count} read-only calls in a row without a change, so this call was not "
    "run. Your task names the files and steps: make the next change now."
)
BLOCKED_HINT = (
    " If the task cannot be done as written, write your Output file and reply "
    "`BLOCKED <output path> reason=stalled: <what is missing>`."
)
LAST_NUDGE_HINT = " If you stall again, every tool except {handback} will be denied."
CUT_MESSAGE = (
    "{prefix} stalled ({signal}). Every tool except {handback} is now denied for this "
    "agent. Write your Output file (the path on your Output line): what you did, what "
    "you found and where you are stuck. Then reply "
    "`BLOCKED <output path> reason=stalled: {signal}`."
)


@dataclass(frozen=True)
class WatchState:
    history: tuple = ()
    streak: int = 0
    nudges: int = 0
    cut_signal: str = ""


@dataclass(frozen=True)
class Verdict:
    kind: str
    message: str


def _key_input(tool_name: str, tool_input: Any, key_fields: Optional[Mapping]) -> Any:
    """Return the part of the input that identifies the call: the listed fields, else all of it."""
    fields = dict(key_fields).get(tool_name) if key_fields else None
    if not fields or not isinstance(tool_input, dict):
        return tool_input
    kept = {field: tool_input[field] for field in fields if field in tool_input}
    return kept if kept else tool_input


def call_key(tool_name: str, tool_input: Any, key_fields: Optional[Mapping] = None) -> str:
    """Return a short key for one call: the tool and the fields that decide what it does.

    Without key_fields the key covers the whole input. The raw input is never stored;
    only the 16 hex digits of the digest are kept.
    """
    keyed = _key_input(tool_name, tool_input, key_fields)
    canonical = json.dumps(keyed, sort_keys=True, separators=(",", ":"),
                           ensure_ascii=False, default=str)
    digest = hashlib.sha256((tool_name + "\x00" + canonical).encode("utf-8", "replace"))
    return digest.hexdigest()[:16]


def _segment_is_read_only(segment: str, prefixes: tuple) -> bool:
    return any(segment == prefix or segment.startswith((prefix + " ", prefix + "\t"))
               for prefix in prefixes)


def _bash_is_read_only(tool_input: Any, settings: rc.StallWatch) -> bool:
    if not isinstance(tool_input, dict):
        return False
    command = tool_input.get(BASH_COMMAND_KEY)
    if not isinstance(command, str):
        return False
    segments = [part.strip() for part in SEGMENT_SPLIT.split(command)]
    segments = [segment for segment in segments if segment]
    return bool(segments) and all(
        _segment_is_read_only(segment, settings.read_only_bash_prefixes)
        for segment in segments)


def is_read_only(tool_name: str, tool_input: Any, settings: rc.StallWatch) -> bool:
    """Return True for a read-only tool, or a Bash call whose every segment is read-only."""
    if tool_name in settings.read_only_tools:
        return True
    if tool_name == BASH_TOOL:
        return _bash_is_read_only(tool_input, settings)
    return False


def _handback(settings: rc.StallWatch) -> str:
    return ", ".join(settings.handback_tools)


def _cut_message(signal: str, settings: rc.StallWatch, prefix: str) -> str:
    return CUT_MESSAGE.format(prefix=prefix, signal=signal, handback=_handback(settings))


def _find_signal(tool_name: str, count: int, streak: int,
                 settings: rc.StallWatch) -> Optional[Tuple[str, str]]:
    """Return (kind, signal text) for the first signal that fires, or None."""
    if count >= settings.repeat_limit:
        return "repeat", REPEAT_SIGNAL.format(tool=tool_name, count=count)
    if streak >= settings.read_only_streak_limit:
        return "reads", READS_SIGNAL.format(count=streak)
    return None


def _nudge_message(kind: str, tool_name: str, count: int, streak: int,
                   state: WatchState, settings: rc.StallWatch, prefix: str) -> str:
    if kind == "repeat":
        text = REPEAT_NUDGE.format(prefix=prefix, tool=tool_name, count=count)
        if WAIT_TOOL in settings.ignored_tools:
            text += WAIT_HINT.format(wait=WAIT_TOOL)
    else:
        text = READS_NUDGE.format(prefix=prefix, count=streak)
    text += BLOCKED_HINT
    if state.nudges + 1 == settings.max_nudges:
        text += LAST_NUDGE_HINT.format(handback=_handback(settings))
    return text


def _after_cut(state: WatchState, tool_name: str, settings: rc.StallWatch,
               prefix: str) -> Tuple[WatchState, Optional[Verdict]]:
    if tool_name in settings.handback_tools:
        return state, None
    return state, Verdict("cut", _cut_message(state.cut_signal, settings, prefix))


def observe(state: WatchState, tool_name: str, tool_input: Any, settings: rc.StallWatch,
            prefix: str) -> Tuple[WatchState, Optional[Verdict]]:
    """Fold one tool call into the watch state; return the new state and a verdict or None."""
    if tool_name in settings.ignored_tools:
        return state, None
    if state.cut_signal:
        return _after_cut(state, tool_name, settings, prefix)
    key = call_key(tool_name, tool_input, settings.call_key_fields)
    history = (state.history + (key,))[-settings.repeat_window:]
    count = history.count(key)
    if tool_name in settings.change_tools and count == 1:
        history = (key,)
    streak = state.streak + 1 if is_read_only(tool_name, tool_input, settings) else 0
    found = _find_signal(tool_name, count, streak, settings)
    if found is None:
        return WatchState(history, streak, state.nudges, ""), None
    kind, signal = found
    if state.nudges < settings.max_nudges:
        message = _nudge_message(kind, tool_name, count, streak, state, settings, prefix)
        return WatchState((), 0, state.nudges + 1, ""), Verdict("nudge", message)
    cut = Verdict("cut", _cut_message(signal, settings, prefix))
    return WatchState((), 0, state.nudges, signal), cut


def state_to_json(state: WatchState) -> str:
    data = {
        "version": STATE_VERSION,
        "history": list(state.history),
        "streak": state.streak,
        "nudges": state.nudges,
        "cut_signal": state.cut_signal,
    }
    return json.dumps(data, separators=(",", ":"))


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _valid_state(data: Any) -> bool:
    if not isinstance(data, dict):
        return False
    history = data.get("history")
    return (
        _is_int(data.get("version")) and data["version"] == STATE_VERSION
        and isinstance(history, list) and all(isinstance(key, str) for key in history)
        and _is_int(data.get("streak")) and data["streak"] >= 0
        and _is_int(data.get("nudges")) and data["nudges"] >= 0
        and isinstance(data.get("cut_signal"), str)
    )


def state_from_json(text: str) -> WatchState:
    """Parse a saved state; return an empty state for any invalid input."""
    try:
        data = json.loads(text)
    except (ValueError, TypeError, RecursionError):
        return WatchState()
    if not _valid_state(data):
        return WatchState()
    return WatchState(tuple(data["history"]), data["streak"], data["nudges"],
                      data["cut_signal"])


def state_path(data_dir: str, agent_id: Any) -> Optional[Path]:
    """Return the state file for one agent, or None when the data dir or the id is unusable."""
    if not isinstance(data_dir, str) or not data_dir.strip():
        return None
    if not isinstance(agent_id, str) or not SAFE_ID.fullmatch(agent_id):
        return None
    return Path(data_dir) / STATE_DIR_NAME / f"{agent_id}.json"


def prune_states(directory: Path, max_age_hours: int, now: float, keep: Path) -> None:
    """Delete state files older than the limit; only regular files with the state name."""
    cutoff = now - max_age_hours * HOUR_SECONDS
    for entry in directory.iterdir():
        if entry == keep or not STATE_FILE.fullmatch(entry.name):
            continue
        try:
            info = os.lstat(entry)
            if stat.S_ISREG(info.st_mode) and info.st_mtime < cutoff:
                os.unlink(entry)
        except OSError:
            continue


def update_state(path: Path, step: Callable[[WatchState], Tuple[WatchState, Optional[Verdict]]],
                 max_age_hours: int, now: float) -> Optional[Verdict]:
    """Apply one step to the agent's saved state under an exclusive lock, then save it."""
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    if not os.path.lexists(path):
        prune_states(path.parent, max_age_hours, now, path)
    fd = os.open(path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "r+", encoding="utf-8", errors="replace") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        state = state_from_json(handle.read())
        new_state, verdict = step(state)
        if new_state != state:
            handle.seek(0)
            handle.truncate()
            handle.write(state_to_json(new_state))
    return verdict


def watched_settings(event: Mapping, config: rc.RoutingConfig) -> Optional[rc.StallWatch]:
    """Return the watch settings when the event comes from a watched agent type, else None."""
    settings = config.stall_watch
    if not settings.enabled:
        return None
    tier = rc.resolve_tier(event.get("agent_type"), config)
    if tier is None or tier.role not in settings.roles:
        return None
    return settings


def evaluate(event: Mapping, config: rc.RoutingConfig, data_dir: str, now: float) -> Optional[str]:
    """Return the denial message for this call, or None to let it run."""
    agent_id = event.get("agent_id")
    if not isinstance(agent_id, str) or not SAFE_ID.fullmatch(agent_id):
        return None
    settings = watched_settings(event, config)
    if settings is None:
        return None
    tool_name = event.get("tool_name")
    if not isinstance(tool_name, str) or not tool_name:
        return None
    if tool_name in settings.ignored_tools:
        return None
    path = state_path(data_dir, agent_id)
    if path is None or fcntl is None:
        return None
    prefix = f"{config.plugin_name} stall watch:"
    tool_input = event.get("tool_input")

    def step(state: WatchState) -> Tuple[WatchState, Optional[Verdict]]:
        return observe(state, tool_name, tool_input, settings, prefix)

    verdict = update_state(path, step, settings.state_max_age_hours, now)
    return None if verdict is None else verdict.message


def _read_event(stream: TextIO) -> Optional[dict]:
    """Parse the hook event from stdin; anything that is not a JSON object gives None."""
    try:
        event = json.loads(stream.read())
    except (ValueError, RecursionError):
        return None
    return event if isinstance(event, dict) else None


def main(stdin: Optional[TextIO] = None, stderr: Optional[TextIO] = None) -> int:
    """Hook entry point: exit 2 with one stderr line to deny a call, 0 to let it run."""
    event = _read_event(sys.stdin if stdin is None else stdin)
    if event is None or not event.get("agent_id"):
        return 0
    out = sys.stderr if stderr is None else stderr
    try:
        config = rc.load_config()
    except rc.ConfigError as exc:
        out.write(f"stall watch: config unavailable ({exc})\n")
        return 0
    except Exception:  # fail open: a broken watch must never block the agent
        return 0
    try:
        message = evaluate(event, config, os.environ.get(PLUGIN_DATA_ENV, ""), time.time())
    except Exception:  # fail open, silently
        return 0
    if message is None:
        return 0
    out.write(message + "\n")
    return 2


if __name__ == "__main__":
    sys.exit(main())
