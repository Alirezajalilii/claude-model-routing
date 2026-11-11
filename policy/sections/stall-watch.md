## Stall watch
A PreToolUse hook (`scripts/stall_watch.py`) watches executors while they run (the roles in `stall_watch.roles`, `config/routing.json`). It uses no model and never consults the advisor; its own errors never block a call (it fails open).
- Signals: the same tool call `repeat_limit` times within the last `repeat_window` calls with no new file change in between, or `read_only_streak_limit` read-only calls in a row.
- Nudge: the hook denies the call that tripped the signal and tells the executor why and what to do next; the executor keeps working. Waiting must use a background command and Monitor: Monitor calls are not counted, a repeated status poll is.
- Hand-back: after `max_nudges` nudges, the next signal makes the hook deny every tool except `handback_tools` (Write). The executor writes its Output file and replies `BLOCKED <output path> reason=stalled: <signal>`.
- On that reply, do not resume the executor (the hook keeps denying its tools) and skip its remaining FIX rounds: escalate the task now, as after its last failed FIX round; it counts under the escalation caps. Give the next executor the stalled Output file as an input file.
- A task that stalls a second time, or has no executor escalation left, goes to REPLAN with its stalled Output files, within the escalation caps. A stalled fast-lane task moves to the full lane (the stall shows it is not small and clear): give it to a planner with the stalled Output file.
- Log each stall in the routing log with the signal from `reason=`.
