---
name: routing-report
description: "Collect the routing evidence for a session (observed model and effort per agent, tokens, skill and advisor calls, audit flags) for docs/model-routing-log.md. Use before the final report of a session that dispatched tier agents."
argument-hint: "[session-id]"
---

1. Use the session id passed as the argument. Without one, use the "Session id" line of the mr session context.
2. Run `mr-usage <session-id>` and `mr-audit <session-id>`.
3. For each task, append one row to `docs/model-routing-log.md` following its columns, with tokens, observed model and effort, and skills per agent taken from the usage report. Skills per agent come from the usage report's `skill_calls` (the SKILL.md files the agent read).
4. List every audit flag in the session report, with its cause. The audit's flags include five kinds added with the handoff rules: non-allowlisted non-tier agents (including `fork`), `model` or `effort` on Agent calls in the main transcript, Haiku requests over 100000 prompt tokens, tier replies that are not a status line, and a main session off the policy model family.
