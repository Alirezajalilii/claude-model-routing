## Lane selection
Use the fast lane only when all of these are true:
- the change is mechanical and fully known in advance;
- it touches one file (its test file does not count), or is a trivially repeated edit;
- it involves no design decision;
- it does not touch authentication, payments, data integrity, migrations, or security.

Fast lane process:
- The main session writes a short spec: goal, file, exact change, verification command, a Skills line (usually "none"), and an Output line.
- It dispatches to `exec-haiku-low`, or `exec-haiku-med` if any logic is involved.
- It runs the verification command itself.
- It merges the executor's commit.
- A run that is fast lane only ends with the Cleanup below (`{{plugin_name}}-clean`).
- No planner, advisor, or verifier is used. Every subagent launch carries substantial fixed context cost; do not spend it on trivial work.

Operational tasks are fast-lane work too: running commands the main session writes out exactly (git push, a conflict-free rebase, polling CI, `gh` calls, a deploy through an existing script, a build or test run), with no file edits. Dispatch them to `exec-haiku-med`, one target per agent, in parallel when independent; reads with no state change go to `scout-haiku-med`. When a step fails in a way that needs a code change or a judgment call, stop that agent and open a full-lane task for the fix. Production deploys still need the user's explicit approval for that change.

Everything else goes through the full lane. A planner is only for work that needs design decisions. Small, clear work, where what to change is already obvious (a type mapping, a typo in a test case, a missing mock, a two-line move, a small issue found mid-run outside the plan's tasks), goes to the fast lane even in the middle of a full-lane run, never to a planner.

**Cleanup.** Every run, also a stalled or abandoned one, ends by removing what it created and nothing else. The main session creates temp files and directories only inside its own session scratchpad. After the merge and the log entry, from the main checkout, run `{{plugin_name}}-clean --plan <plan path> --base <base branch> --handoff <handoff dir> --scratch <scratchpad dir>` (fast lane: `--branch <branch>` for each branch its spec named, instead of `--plan`). Run it only when no agent of the run is still running. Leave out `--handoff` when a status line of the run carried `findings=`. That is a dry run: check that it lists only this run's items, then run it again with `--apply`. The final report names every item it kept or refused; never delete those by hand or touch another session's branches, worktrees or temp files.
