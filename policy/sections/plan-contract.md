## Plan Contract
Every plan file (`docs/plans/YYYY-MM-DD-short-slug.md`) contains: the goal; the evidence summary, with file references; assumptions (including any departure from the main session's framing, with the reason); the tasks; risks; Skill Gaps (skills that do not exist but would have helped); and Advisor Notes (suggestions applied and suggestions rejected, with reasons).

Each task contains:
- a task ID;
- the goal;
- exact files and functions to touch;
- ordered steps;
- constraints and project conventions to follow;
- explicitly out-of-scope items;
- acceptance criteria;
- exact verification commands;
- for a docs task that states commands, procedures or behavior: a fact sheet listing every command, path and claim the doc will contain, each with its source file and line;
- Test Cases: each behavior to test, with inputs and the expected outcome; or "Tests: existing suite only" for tasks with no behavior change. The planner writes these, so tests come from the spec, not from the executor's reading of it;
- dependencies on other tasks;
- the assigned executor tier, with a one-line reason;
- the executor Skills line (absolute SKILL.md paths from the inventory, or none), alone on its own line so it can be copied verbatim, with a one-line reason per skill on separate lines;
- the Project rules line: the project rules files the executor and verifier read (paths, or none when the task's constraints already carry every convention);
- Verify: yes or no, naming the trigger if yes;
- the verifier tier and verifier Skills line, assigned for every task, because a verifier can still run through a gate failure, a FIX round, or sampling.

No task may leave a design decision to the executor.
