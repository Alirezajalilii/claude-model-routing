## Plan Contract
Every plan file (`docs/plans/YYYY-MM-DD-short-slug.md`) contains: the goal; the evidence summary, with file references; assumptions (including any departure from the main session's framing, with the reason); the tasks; risks; Skill Gaps (skills that do not exist but would have helped); and Advisor Notes (suggestions applied and suggestions rejected, with reasons).

Each task contains:
- a task ID, in the task's heading `### Task <ID>: <title>`;
- the goal;
- exact files and functions to touch;
- ordered steps;
- constraints and project conventions to follow;
- explicitly out-of-scope items;
- acceptance criteria;
- exact verification commands;
- for a docs task that states commands, procedures or behavior: a fact sheet listing every command, path and claim the doc will contain, each with its source file and line;
- Test Cases: each behavior to test, with inputs and the expected outcome; or "Tests: existing suite only" for tasks with no behavior change. The planner writes these, so tests come from the spec, not from the executor's reading of it;
- the Contract block (Task contract format below), from which the run order follows;
- the planned executor tier, with a one-line reason, and the start tier (see Executor tier selection); the planned tier is the fallback;
- the executor Skills line (absolute SKILL.md paths from the inventory, or none), alone on its own line so it can be copied verbatim, with a one-line reason per skill on separate lines;
- the Project rules line: the project rules files the executor and verifier read (paths, or none when the task's constraints already carry every convention);
- Verify: yes or no, naming the trigger if yes;
- the verifier tier and verifier Skills line, assigned for every task, because a verifier can still run through a gate failure, a FIX round, or sampling; a task that starts below its planned tier names its start and fallback verifier tiers.

No task may leave a design decision to the executor.

### Task contract format
Every task has a `Contract:` line followed by its items, one per line, up to the first line that is not an item; a task that provides, requires and follows nothing has `Contract: none`. `{{plugin_name}}-plan` reads these lines (backticks are ignored, code fences are skipped), so keep exactly this form:
- `- provides: <kind> <name> in <path> -- <shape>`: a name this task creates that a sibling task uses. `<kind>` is symbol, file, config, env, flag, endpoint or id; `<path>` is the repository-relative file that will contain the name. A `file` provide has no `in`: its name is the path. `-- <shape>` is optional and one line, for example a function's parameters and return value.
- `- requires: <task-id> <name> -- <shape>`: a name that task's provides line declares. Copy its shape, so the executor sees it in its own task.
- `- after: <task-id>, <task-id>`: tasks that must pass first although this task uses no name from them.
List as provides every name a sibling task relies on, spelled exactly as the code will spell them (other deliverables may be listed too): the gate checks presence (a whole word for a symbol, the key path for a config key in a JSON file, the exact text otherwise). Two tasks that change the same file are never independent: link them with requires or after. The run order follows from requires and after; there is no separate dependency list.
