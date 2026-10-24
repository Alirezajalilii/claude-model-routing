---
name: routing-report
description: "Collect the routing evidence for a session (observed model and effort per agent, tokens, skill and advisor calls, audit flags) for docs/model-routing-log.md. Use before the final report of a session that dispatched tier agents."
argument-hint: "[session-id]"
---

1. Use the session id passed as the argument. Without one, use the "Session id" line of the model-routing session context.
2. Run `model-routing-usage <session-id>` and `model-routing-audit <session-id>`.
3. For each task, append one row to `docs/model-routing-log.md` following its columns, with tokens, observed model and effort, and skills per agent taken from the usage report.
4. List every audit flag in the session report, with its cause.
