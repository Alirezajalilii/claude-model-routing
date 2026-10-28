## Executor tier selection (made by the planner)
For each task, answer three questions:
- **B.** Does it touch more than one module or more than about two production files? Test files, fixtures and generated artifacts do not count.
- **C.** Will it need more than about ten sequential tool calls beyond the standard red/green cycle, or a run-fix-iterate loop against an environment (Docker, a deploy, an integration stack, external CI)? Running the task's own tests and verification commands is not such a loop.
- **D.** Is it tricky: concurrency, security, data integrity, performance, or heavy edge cases?

Count the yes answers:
- **0:** `exec-haiku-low` if purely mechanical; `exec-haiku-medium` otherwise.
- **1:** `exec-haiku-high` if the only yes is D; `exec-sonnet-medium` otherwise.
- **2:** `exec-sonnet-high`.
- **3:** `exec-sonnet-xhigh`.

When torn between two tiers, pick the lower one and rely on escalation. Exceptions: authentication, payments, data integrity, and migrations go one tier higher; a task that needs more than {{skill_cap_haiku}} skills cannot go to a Haiku tier. A task expected to need more than about {{haiku_max_tool_calls}} tool calls in total is never a Haiku task.

Split for the cheap tier: a mechanical change spread over many files (a rename, a class or token migration, a repeated edit) becomes folder-sized tasks with an exact mapping table in the plan, each `exec-haiku-low`, rather than one large Sonnet task.

Docs that state commands, procedures or behavior (runbooks, ADRs, READMEs, agent guides such as AGENTS.md) go to `exec-haiku-medium` at least (`exec-sonnet-medium` when they span modules), with a fact sheet in the task; wording-only docs stay on `exec-haiku-low`.

What each executor tier is for:
- **exec-haiku-low:** renames, config and environment changes, boilerplate following existing patterns, adding fields, copy and wording-only docs changes, and tests from cases given in the plan.
- **exec-haiku-medium:** single-module logic with clear tests, such as serializers, simple endpoints, utilities, and small components; and operational runbooks with exact commands (push, rebase, CI polling, scripted deploys, build and test runs).
- **exec-haiku-high:** tricky but well-specified single-module logic, such as parsing, validation, and edge-case-heavy functions.
- **exec-sonnet-medium:** standard multi-file feature work across roughly two to five files.
- **exec-sonnet-high:** cross-module changes, refactors, Celery and BullMQ work, Docker and terminal-heavy run-fix loops.
- **exec-sonnet-xhigh:** the delegation ceiling. Large refactors, concurrency, performance, security-sensitive code, and tasks that already failed at sonnet-high.
