# Plans

This directory holds the plan files that planner agents write under the Model Routing Policy, one file per plan: `YYYY-MM-DD-short-slug.md`.

Each plan follows the Plan Contract: goal, evidence summary with file references, assumptions, tasks, risks, Skill Gaps and Advisor Notes. Each task names its files, steps, test cases, executor and verifier tiers, Skills lines and its Verify mark.
Each task also has a Contract block (provides, requires, after): `mr-plan waves <plan>` turns it into run order and `mr-plan check <plan> <task-id> <worktree>` checks it at the gate.

The main session dispatches executors with the plan path and a task ID, never a paraphrase. The routing log is `docs/model-routing-log.md`.
