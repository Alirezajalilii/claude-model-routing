## Lane selection
Use the fast lane only when all of these are true:
- the change is mechanical and fully known in advance;
- it touches one file (its test file does not count), or is a trivially repeated edit;
- it involves no design decision;
- it does not touch authentication, payments, data integrity, migrations, or security.

Fast lane process:
- The main session writes a short spec: goal, file, exact change, verification command, and a Skills line (usually "none").
- It dispatches to `exec-haiku-low`, or `exec-haiku-medium` if any logic is involved.
- It runs the verification command itself.
- It merges the executor's commit.
- No planner, advisor, or verifier is used. Every subagent launch carries substantial fixed context cost; do not spend it on trivial work.

Operational tasks are fast-lane work too: running commands the main session writes out exactly (git push, a conflict-free rebase, polling CI, `gh` calls, a deploy through an existing script, a build or test run), with no file edits. Dispatch them to `exec-haiku-medium`, one target per agent, in parallel when independent; reads with no state change go to `scout-haiku-medium`. When a step fails in a way that needs a code change or a judgment call, stop that agent and open a full-lane task for the fix. Production deploys still need the user's explicit approval for that change.

Everything else goes through the full lane. A planner is only for work that needs design decisions. Small, clear work, where what to change is already obvious (a type mapping, a typo in a test case, a missing mock, a two-line move, a small issue found mid-run outside the plan's tasks), goes to the fast lane even in the middle of a full-lane run, never to a planner.
