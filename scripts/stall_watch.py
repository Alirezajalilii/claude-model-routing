"""Stall watch: a PreToolUse hook that spots a stuck subagent while it runs.

Two signals mark a stall: the same call repeated within the last few calls with no
file change in between (the repeat signal), and a long run of read-only calls in a
row (the reads signal). The first signal in a run gets a nudge: the call is not run
and the agent is told to change course. When the agent stalls again beyond the
allowed nudges, the watch cuts it: every tool except the hand-back tool is denied
until the agent writes its Output file and replies BLOCKED.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any, Optional, Tuple

import routing_config as rc

BASH_TOOL = "Bash"
BASH_COMMAND_KEY = "command"
WAIT_TOOL = "Monitor"
SEGMENT_SPLIT = re.compile(r"&&|\|\||[;|\n]")
STATE_VERSION = 1
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


def call_key(tool_name: str, tool_input: Any) -> str:
    """Return a short key for one call; the raw input is never stored."""
    canonical = json.dumps(tool_input, sort_keys=True, separators=(",", ":"),
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
    key = call_key(tool_name, tool_input)
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
