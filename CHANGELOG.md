# Changelog

All notable changes to this project are documented here. The format follows Keep a Changelog, and the project uses Semantic Versioning.

## [Unreleased]

## [0.8.0] - 2026-11-14

### Added
- `scripts/render_charts.py` and `make charts`: four README charts generated from the committed case-study and cost data; `make lint` fails when they are stale.

### Changed
- README leads with charts and a workflow diagram instead of long prose.
- Verifiers fix the defects they find themselves: every verifier tier has the executor's tools, including `Edit`, commits its fixes on the task branch (only in files the task's Gate block allows, never in a file from commit one) and replies `FIXED <path> commits=<sha>,...`. The `FIX` verdict, the executor's fix round from a verdict and the second verifier pass are gone.
- After a `FIXED` verdict the main session gates the task again with the verdict file as `--report`; a gate failure resumes the same verifier (a verifier round), at most `max_fix_rounds_per_tier` times, and then the task goes to REPLAN.
- Batch verifiers check and fix each task in its kept task worktree instead of a detached worktree at the integration branch's head.
- Verifier bodies may be up to 14000 characters; executor bodies stay at 12000.
- The routing audit accepts `FIXED` status lines.
- The Forbidden list says an Opus verifier fixing what it finds is not an Opus executor, and forbids resuming an executor with a verifier's verdict or a second verifier pass over a `FIXED` task.

## [0.7.0] - 2026-11-12

### Added
- `mr-cost` prices `mr-usage --json` rows at Anthropic API list prices (as of 2026-11-12) and re-prices the same tokens at Sonnet 5.5 and Opus 5.5 rates; `--cache-ttl 1h` uses 1-hour cache-write prices.
- `mr-doctor` checks Python, the Claude Code version, the settings the policy relies on, `ANTHROPIC_API_KEY` and whether the project is initialized, and prints a fix for each problem.
- `docs/cost.md` and `docs/cost/2026-11-11-run.json`: one logged run priced with `mr-cost`, with the method and its limits.
- The sensitive-data scan (`scripts/scan_sensitive.py`) is back on the main branch, and `make lint` runs it on the full history.
- `docs/case-study.md`: mr across 18 projects and 1,785 agents, with anonymized, aggregated data in `docs/case-study/` that `mr-cost` and the tests recompute, and a deep dive on one large production run in `docs/case-study-monorepo.md`.
- `mr-cost` accepts an `agent_count` per row for aggregated data, reports the main session as its own group, and no longer skips agents whose recorded models include `<synthetic>`.

### Changed
- README redesigned as a landing page around the cross-project results: the agent roles, the model each step runs on, isolated contexts, a cost chart, and the full install, safety and command reference.
- The policy's cost reference states prices as of 2026-11-12 with cache-read rates and no longer cites an unlogged 2026-10-29 result.
- AGENTS.md, CONTRIBUTING.md and docs/architecture.md describe this repository on its own.

### Fixed
- `mr-usage <session-id>` resolves a session that has no subagent folder through its main transcript instead of failing with "no session".
- `mr-usage` and `mr-audit` recover a subagent's type from the parent session's dispatch when its meta file is missing, so `--agent-type` filters find it and the audit no longer reports it as unknown; `mr-usage` also leaves `<synthetic>` placeholder models out of `resolved_models` when a real model is recorded.

### Removed
- Empty workspace folders (`apps/`, `packages/`, `infra/`, `data/`, `docs/api/`, `docs/runbooks/`, `docs/specs/`, `docs/decisions/`) and the private `docs/wiki/`.

## [0.6.0] - 2026-11-12

### Added
- The `mr-gate` command (`bin/mr-gate`, `scripts/gate_cli.py`) runs red, integrity, coverage, scope, contract, green and report for one task from the plan's Gate block, writes the gate file and prints `PASS <gate file>` or `FAIL <gate file> checks=<names>` (exit 0, 1, 2).
- The Gate block (`files`, `tests`, `red`, `guard`, `green`) and `TC<n>` Test Case IDs with `(guard)` marks in the Plan Contract.
- Batch verification with the tunable `batch_verify_max_tasks` (6).
- Audit flags for agents stopped by the usage limit and for `exec-sonnet-xhigh` runs with no earlier `exec-haiku-high` or `exec-sonnet-high` run of the task.
- The usage-limit recovery rule in the handoffs policy.

### Changed
- Haiku tier agents no longer get `autoCompactWindow` and run on Haiku's full context window; `haiku_prompt_flag_tokens` is 300000 (was 100000).
- Verify marks are `task`, `batch` or `no`: risk tasks keep a per-task verifier, other triggered tasks share batch verifiers once per plan, guard tests no longer trigger a verifier.
- `exec-sonnet-xhigh` only for three yes answers or after a failure at `exec-sonnet-high`, and the one-tier-higher exception stops at `exec-sonnet-high`.
- The main session runs `mr-gate` instead of the gate checks by hand; executors tag tests with Test Case IDs.
- The verifier body's step 5 names the contract check among the gate checks it judges.
- docs/architecture.md lists the stall-watch PreToolUse hook.

### Fixed
- The SessionStart hook re-sent the whole dispatcher policy into every subagent that compacted (Claude Code gives the hook no subagent marker on compaction); after a compaction only part 1 prints a short pointer to the `mr:routing-policy` skill, and events with `agent_id` get nothing.
- Calibration and logging proposals go to the log's proposals section where CLAUDE.md is generated or not committed.

## [0.5.1] - 2026-11-11

### Fixed
- The stall watch's repeat signal never fired in a live run. Its call key hashed the whole tool input, and a model writes a different Bash `description` on every call, so five identical commands counted as five different calls. The key now covers only the fields listed for that tool in the new config key `stall_watch.call_key_fields` (shipped: Bash `command`, `timeout`, `run_in_background`); tools not listed, and inputs with none of the listed fields, are still keyed on the whole input.
- Tests replay the live failure (identical commands with changing descriptions) and guard the shipped key fields, so the bug cannot return unnoticed.

## [0.5.0] - 2026-11-11

### Added
- Task contracts in the Plan Contract. Every plan task has a heading `### Task <ID>: <title>` and a `Contract:` block: what it provides to sibling tasks (`- provides: <kind> <name> in <path> -- <shape>`, kinds `symbol`, `file`, `config`, `env`, `flag`, `endpoint`, `id`), what it requires from them (`- requires: <task-id> <name> -- <shape>`) and which tasks it runs after (`- after: <task-id>, <task-id>`), or `Contract: none`.
- The `mr-plan` command (`bin/mr-plan`, `scripts/plan_cli.py`). `mr-plan waves <plan>` validates the Contract blocks and prints the run order, one line per wave. `mr-plan check <plan> <task-id> <worktree>` reports each provides and requires line of one task as `ok:` or `missing:`. Exit 0 when the plan is valid and nothing is missing, 1 for contract errors or missing lines, 2 for usage, file or internal errors.
- A Contract gate check: the main session runs `mr-plan check` for every finished task. A missing provides line fails the gate as a check other than Green.
- Stall watch: a PreToolUse hook (`scripts/stall_watch.py`, config section `stall_watch`) watches executors while they run. When an executor repeats the same tool call `repeat_limit` times within the last `repeat_window` calls with no file change in between, or makes `read_only_streak_limit` read-only calls in a row, the hook denies that call and says why (a nudge). After `max_nudges` nudges, the next signal denies every tool except `handback_tools` (Write), and the executor replies `BLOCKED <output path> reason=stalled: <signal>`. The hook uses no model, never consults the advisor, keeps per-agent state in `$CLAUDE_PLUGIN_DATA/stall-watch/<agent_id>.json`, and fails open.

### Changed
- Tasks run in dependency order from `mr-plan waves` instead of being ordered by hand; a plan without Contract lines is still ordered by hand. Each plan gets an integration branch `agent/<plan-slug>-integration`: every task branches from its head and merges into it as soon as it passes, and the final gate runs on it.
- On a `reason=stalled` BLOCKED reply the main session does not resume the executor, skips its remaining FIX rounds and escalates the task at once. A second stall, or a stall with no executor escalation left, goes to REPLAN. A stalled fast-lane task moves to the full lane.

## [0.4.1] - 2026-11-06

### Fixed
- On Claude Code 2.1.318, a skill with `context: fork` that a subagent invoked through the Skill tool ran as a separate `general-purpose` subagent, past the agent's `disallowedTools` and `CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH=1`. The dispatch guard now checks Skill calls as well.
- The dispatch guard hook matches `Agent|Task|Skill` (was `Agent|Task`).
- For a call from a subagent (the hook event carries `agent_id`), the dispatch guard denies a Skill call whose SKILL.md sets `context: fork` or that it cannot find among the user, project and plugin skills, and denies any Agent or Task call. If the Skill check fails internally, the guard denies the call.
- Main-session Skill calls are not checked.
- A denied agent can still Read the skill's SKILL.md path and follow it inline.

## [0.4.0] - 2026-11-06

### Added
- Agents that have Bash (scouts, executors and verifiers) also have the `Monitor` and `TaskStop` tools. Config validation requires `Read`, `Write` and `Skill` in every role, requires `Monitor` and `TaskStop` in roles with Bash, and rejects nesting tools in `tools` and any tool listed in both `tools` and `disallowed_tools`.
- A "Long-running commands" section in the agent policy: no `sleep` waits (Bash refuses `sleep N` followed by other commands), Monitor until-loops to wait for background commands, and TaskStop for every background shell before the status line.
- The session audit flags `listed skills not loaded: <k> of <n>` when a tier agent did not load each skill on its Skills line, by Read of the path or by a Skill-tool call.
- `mr-skills` lists skills kept one folder deeper in a group folder (such as the ECC skills) with scope `<scope> group <group>`, and reads block-scalar (`>`, `|`) descriptions.

### Changed
- Every tier agent has the `Skill` tool and keeps `Read` and `Write`. This reverses the 0.2.0 removal of the `Skill` tool.
- Agents load each listed skill in full, by Read of its SKILL.md path or by the Skill tool when the skill's name is in the session's skill listing. The "Skills loaded" line names Skill-tool loads by name. The skill listing costs roughly 15K tokens per agent with several hundred skills installed, and the policy documents this cost.
- Agents read every file they must follow in chunks of at most 250 lines (`offset` and `limit`), never with one long Read or `cat`, and re-read any range a result marks as omitted. A token-saving proxy between Claude Code and the model can cut the middle out of a long tool result.
- Executors reply DONE when only failures their change did not cause remain, and list each one under "Checks failing outside the task" in their Out-of-scope findings. The gate confirms each one fails the same way on the task's base commit, and the Report check covers the "Skills loaded" line.
- Skill caps rise to 4 for Haiku agents and 6 for other agents (`skill_cap_haiku`, `skill_cap_other`). Skill assignment follows the user's order: the must-follow general skills the user or the project rules name, plus the skills for the task's language, framework and specific work. The main session passes the user's must-follow skills to the planner.
- The three Haiku executor tier descriptions say "at most 4 skills", matching `skill_cap_haiku`; a test keeps them in step.
- The `agent-shell` section is listed in `policy.sections`, so it also appears in the `mr:routing-policy` skill.
- The policy test's non-planner agent body size limit is 12000 characters (was 10000), for the text this release adds.

## [0.3.0] - 2026-10-29

### Changed
- Executors start on Haiku: a task planned on a Sonnet executor tier starts on `exec-haiku-high`, gets its FIX rounds there, then falls back straight to its planned tier. Plans name a start tier next to the planned tier, and planners split a task that would need more than 2 skills (the Haiku skill cap).
- Every task that runs below its planned tier gets a verifier: `verify-sonnet-med`, except tasks touching authentication, payments, data integrity, migrations or security, and tasks planned on `exec-sonnet-xhigh`, which keep `verify-opus-high`. Plans name the start and fallback verifier tiers. Calibration counts these tasks separately and proposes sampling to the human once their defect rate stays low.

### Removed
- The Haiku tool-call limit: the tunable `haiku_max_tool_calls` and the rule that a task needing more than about 25 tool calls is not a Haiku task.

### Fixed
- The policy no longer claims that tier agents load no CLAUDE.md. `omitClaudeMd` skips only the start-of-session load; Claude Code still attaches CLAUDE.md files as nested memory when an agent touches files below them, and no plugin setting stops this. Tier agents now ignore attached instruction files other than their project rules files, and the policy advises launching Claude Code in the project root.

### Added
- The session audit flags tier agents that received instruction files as nested memory (`<n> instruction-file attachments despite omitClaudeMd (<k> files: ...)`).

## [0.2.1] - 2026-10-29

### Fixed
- Haiku agents compacted at about 67K tokens: Claude Code compacts 33K below `autoCompactWindow` (its 20K output reserve plus a 13K buffer), so 100000 meant 67K. Haiku agents now get `autoCompactWindow` 123000 and compact once their context passes about 90K tokens.
- Executors committed test files that failed lint, then refused every fix: their rules forbade both changing a commit-one file later and amending. Executors now run the project's lint, format and type checks before every commit, never commit or reply DONE while a check fails, and fix a lint, format or type finding in a commit-one file inside commit one (amend, or reset to commit one and commit again), keeping every test case and assertion. The core rule now forbids rewriting pushed or shared history only.
- Claude Code refuses a subagent's Write to `.md` files whose name starts with `report`, `summary`, `findings` or `analysis`, so handoff files named `report-T3.md` failed and agents pasted their reports into the reply. The handoff policy names such files out, and the dispatch guard denies a tier delegation whose Output file name matches `dispatch.blocked_output_names` in the routing config.

### Changed
- The gate's Green check includes the project's lint and type checks.

## [0.2.0] - 2026-10-28

### Added
- `scripts/check_install.py` and `make check-install` verify the installed plugin holds only committed files; the README documents the git-marketplace install and update.
- Main-session model note and audit line are informational; the policy names no advisor model.
- Scouts and verifiers get the Write tool, and every tier agent writes its full output to a handoff file and replies with one status line (status words per role are listed in the handoff policy section). Agent bodies gain the sections Core rules, Skills, Output and status line, and Output file.
- Agent frontmatter settings from config: `omitClaudeMd` is true for every agent, and Haiku agents get `autoCompactWindow` 100000.
- Tunables `haiku_max_tool_calls` (25), `haiku_prompt_flag_tokens` (100000) and `status_line_max_chars` (400), plus `dispatch.allow_agents` (`claude-code-guide`, `statusline-setup`).
- Dispatch guard denies agent types outside the tiers and `dispatch.allow_agents` (an empty type counts as `general-purpose`), and `model` or `effort` on any agent. For tier delegations it denies a missing Skills line, Skills items that are not existing absolute SKILL.md paths, a missing absolute `Output:` path, and (non-planners) a missing "Never consult the advisor." line. It still fails open on malformed input and config errors.
- Session context adds an informational note when the session runs on a model outside the policy default family; the note survives the oversize fallback.
- Audit flags: non-allowlisted non-tier agents (including `fork`) in every session, `model` or `effort` on Agent calls in the main transcript, Haiku requests over 100000 prompt tokens, tier replies that are not a status line, and a main session off the policy model family.

### Changed
- Plugin renamed from `model-routing` to `mr`; tier agents are dispatched as `mr:<tier>`.
- Tier names shortened: role tokens `plan` (was `planner`) and `verify` (was `verifier`), effort token `med` (was `medium`); `config/routing.json` maps efforts to name tokens in `effort_labels`. Agent `effort` values are unchanged.
- Launchers renamed to `mr-usage`, `mr-audit`, `mr-skills` and `mr-init`.
- Upgrading from 0.1.0: back up the old plugin's data directory, install `mr`, uninstall the old plugin with `--keep-data`, and copy the old `audits/` into the new plugin's data directory with `cp -Rpn`.
- `scripts/check_install.py` compares installed files by content (git blob ids) instead of names only, and finds the install folder from the `name` and `version` in `.claude-plugin/plugin.json`.
- `hooks/hooks.json` runs SessionStart as `session_context.py --part 1` to `--part 5`, matching the dispatcher parts in config.
- The skills inventory table has the columns Skill, Scope, Path and Description, and `mr-skills` accepts `--out FILE`.
- `mr-usage` counts Read calls on `*/SKILL.md` in `skill_calls` and reports `peak_prompt_tokens` in its JSON.
- Planners own the solution: they plan from the user's request and the evidence, not from the dispatcher's framing, and record any departure under assumptions.
- One planner instance per topic. Small, clear work and wrap-up never go to a planner; planners can reply OUT_OF_TOPIC or NO_PLAN_NEEDED.
- One advisor consult per plan, after the complete draft is written; no second consult to check the revision.
- Planners get the Edit tool, so a REPLAN edits only the affected task instead of rewriting the plan file.

### Removed
- The `Skill` tool from every role: agents load skills by reading the SKILL.md paths on their Skills line.

## [0.1.0] - 2026-10-24

### Added
- Tier subagents (scouts, planners, executors, verifiers) generated from `config/routing.json`.
- Session-start dispatcher policy in four parts, with configuration warnings and the session id.
- Dispatch guard (PreToolUse on `Agent|Task`) for Skills lines, the advisor line and model or effort overrides, recognizing scoped and bare tier names.
- Session audit (SessionEnd), written to the plugin data directory.
- Commands `model-routing-usage`, `model-routing-audit`, `model-routing-skills` and `model-routing-init`.
- Skills `routing-policy`, `init-project` and `routing-report`.
- Templates for the routing log and the plans README.
- Repository sensitive-data scan.
