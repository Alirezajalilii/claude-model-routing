# Changelog

All notable changes to this project are documented here. The format follows Keep a Changelog, and the project uses Semantic Versioning.

## [Unreleased]

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
