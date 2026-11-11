# model-routing — agent guide

This project follows the workspace standard in ~/Work/AGENTS.md. Read that first. This file holds only what is specific to this project.

## Identity
- Purpose: Cost-aware model routing for Claude Code (tiered subagents, dispatch guard, audit)
- Created: 2026-10-27
- Status: active

## Stack
- Claude Code plugin (manifest in `.claude-plugin/plugin.json`, version 0.5.0 per CHANGELOG.md).
- Python 3.9+ standard library only; no third-party packages (CONTRIBUTING.md). Tests use `unittest`.
- Plugin parts: hooks (`hooks/hooks.json`: SessionStart runs `session_context.py --part 1` to `--part 5`, PreToolUse on `Agent|Task|Skill` runs the dispatch guard, PreToolUse on the executor tools runs the stall watch (`scripts/stall_watch.py`), SessionEnd runs the audit), generated subagents (`agents/`), skills (`skills/`), launchers (`bin/`).
- Single source of truth for tiers, roles and tunables: `config/routing.json`. Policy text: `policy/`.
- No database, no queue, no containers, no CI (CONTRIBUTING.md: "There is no CI").

## Apps
- None. `apps/` holds only `.gitkeep`. The deliverable is the plugin at the repo root (see Deviations).

## Commands
All routine work goes through the Makefile: make setup, make dev, make test, make lint, make fmt, make typecheck, make build, make clean. `migrate` and `db-reset` do not apply (no database). Run `make help` for the list.
- `make setup`: prints the Python version. Nothing to install.
- `make dev`: not applicable; prints why and exits 0. Load the plugin in Claude Code from this checkout.
- `make test`: `python3 -m unittest discover -s tests -v` with `PYTHONDONTWRITEBYTECODE=1`.
- `make lint`: `scripts/generate.py --check` (fails if generated files are stale), then `claude plugin validate --strict` on a temporary copy of what git would ship (tracked plus untracked, not ignored, so the git-ignored `CLAUDE.md` pointer and `.agent/` are left out) if the `claude` CLI is on PATH, then `scripts/scan_sensitive.py --history` if that file exists.
- `make check-install`: fails if the installed plugin cache holds any file not committed at HEAD (run after install or update).
- `make fmt`, `make typecheck`: not applicable; print why and exit 0.
- `make build`: runs `scripts/generate.py` and rewrites the generated files `agents/*.md` and `skills/routing-policy/SKILL.md`.
- `make clean`: removes `__pycache__` directories outside `.git`.

## Project-specific conventions
- `agents/` and `skills/routing-policy/SKILL.md` are generated. Never edit them by hand: change `config/routing.json` or `policy/`, then `make build`.
- Change `config/routing.json`, `policy/` or `scripts/` with tests first (`unittest`).
- Functions stay under 50 lines and files under 800 lines; `tests/test_code_limits.py` enforces both.
- Conventional Commits (`feat:`, `fix:`, `docs:`, `test:`, `refactor:`, `chore:`), one subject line, no personal data in messages.
- No personal or machine-specific data anywhere: no home paths, no e-mail addresses other than `example.com`, no IP addresses, tokens or session ids.
- Plans, routing logs and transcripts never belong in this repository (`docs/plans/` and `docs/model-routing-log.md` are gitignored).

## Deviations from the workspace standard
- `CLAUDE.md` is not committed. The project's own `.gitignore` ignores `/CLAUDE.md` (kept as the project chose). The file on disk holds only `@AGENTS.md`; the pre-standard content was merged into this file. Decide whether to track it: remove the `/CLAUDE.md` line from `.gitignore` and commit the one-line file.
- `.claude-plugin/`, `agents/`, `hooks/`, `skills/` at the repo root: the Claude Code plugin format and the marketplace entry (`source: "."` in `.claude-plugin/marketplace.json`) require them at the plugin root. Not movable to `apps/` without breaking the plugin.
- `bin/`: launchers for the plugin commands `mr-usage`, `mr-audit`, `mr-skills`, `mr-init`, `mr-plan`.
- `config/`: `routing.json`, the single source of truth for tiers, roles and tunables.
- `policy/`: policy text fragments and agent body templates rendered by `scripts/generate.py`.
- `templates/`: `model-routing-log.md` and `plans-README.md`, copied into user projects by the init-project skill.
- `tests/`: the unittest suite lives at the root, not next to the code. Reason: all Python code is in `scripts/` and `bin/`, and the suite checks cross-cutting rules (plugin manifest, code limits, generated output).
- `CHANGELOG.md`, `CONTRIBUTING.md`, `LICENSE`, `SECURITY.md`: open-source plugin repository files, not in the standard tree.
- `.claude/` (local, gitignored): Claude Code local settings; never committed.

## Current state
- Version 0.2.0 (2026-10-28) per CHANGELOG.md: the plugin is named `mr`, tiers use the short names (`scout`, `plan`, `exec`, `verify`; efforts `low`, `med`, `high`, `xhigh`), and `make check-install` compares file content.
- Version 0.2.1 (2026-10-29): Haiku agents compact at about 90K tokens (`autoCompactWindow` 123000; Claude Code compacts 33K below the window), executors run lint, format and type checks before every commit and fix commit-one findings inside commit one, and the dispatch guard denies Output file names Claude Code refuses to subagents (`dispatch.blocked_output_names`).
- Version 0.3.0 (2026-10-29): executors start on Haiku (`exec-haiku-high` for Sonnet-planned tasks) and fall back straight to the plan's tier after the FIX rounds; every task run below its planned tier gets a verifier, and sensitive or `exec-sonnet-xhigh`-planned tasks keep `verify-opus-high`; the tunable `haiku_max_tool_calls` is gone; tier agents ignore instruction files Claude Code attaches as nested memory, and the audit flags them.
- Version 0.4.0 (2026-11-06): every tier agent has the `Skill` tool (reversing the 0.2.0 removal), roles with Bash also have `Monitor` and `TaskStop` and a "Long-running commands" policy section (no `sleep` waits), and config validation enforces these tool sets (`_tool_list_errors`); agents load listed skills in full by Read or the Skill tool, read files in chunks of at most 250 lines, and the skill listing costs roughly 15K tokens per agent; executors reply DONE for failures their change did not cause, listed under "Checks failing outside the task" and confirmed by the gate on the base commit; skill caps are 4 (Haiku) and 6 (others) with the user's must-follow general skills plus language, framework and task skills; `mr-skills` lists grouped skills (scope `<scope> group <group>`) and reads block-scalar descriptions; `mr-audit` flags `listed skills not loaded: <k> of <n>`.
- Version 0.4.1 (2026-11-06): the dispatch guard hook matches `Agent|Task|Skill`; for subagent calls (the event carries `agent_id`) it denies Skill calls for `context: fork` skills and for skills it cannot find, fails closed if that check errors, and denies any Agent or Task call; main-session Skill calls are not checked; a denied agent can Read the SKILL.md and follow it inline.
- Version 0.5.0 (2026-11-11): plan tasks carry Contract blocks (provides, requires, after); `mr-plan waves` gives the run order and `mr-plan check` is a gate check; each plan merges its tasks through an integration branch `agent/<plan-slug>-integration`; the stall watch PreToolUse hook (`scripts/stall_watch.py`, config `stall_watch`) nudges, then cuts off, an executor that repeats a call or reads without end, and the main session escalates on `BLOCKED ... reason=stalled`.
- Branch `chore/adopt-workspace-standard` holds the workspace-standard adoption.
- The repository has 14 local branches (feature and task branches such as `agent/T09`). Do not switch branches to inspect them; read with `git show <branch>:<path>`.

## Gotchas
- `scripts/scan_sensitive.py` is referenced by CONTRIBUTING.md and by `make lint`, but it is not on this branch. It exists on `agent/T09` (commit 279a273 and related). TODO(agent): decide whether to merge it into this branch or remove the reference from CONTRIBUTING.md. Until then `make lint` skips the sensitive-data scan with a message.
- Install and update the plugin from the pushed repository through a git marketplace, never from the working tree: a directory marketplace copies git-ignored private files (`.agent/`, `.claude/`) into the plugin cache. See README.md.
- Run Python with `python3 -B` (or `PYTHONDONTWRITEBYTECODE=1`); the scripts never write bytecode.
- Tier names are generated as `<role prefix>-<model>-<effort label>` from `roles.*.prefix` and `effort_labels` in `config/routing.json`; the agent `effort` value stays the real effort (`medium`, not `med`).
- `claude plugin marketplace remove` deletes the plugin data directory (audits). Back it up before removing the marketplace or uninstalling, uninstall only with `--keep-data`, and restore it with `cp -Rpn`.
- Settings the dispatch guard and session policy check (warnings, not errors): `CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH` should be `1`; `CLAUDE_CODE_EFFORT_LEVEL`, `CLAUDE_CODE_SUBAGENT_MODEL` and `CLAUDE_CODE_SUBAGENT_MODEL_FORCE` should be unset. See `.env.example`.
- `data/` and `.agent/` are gitignored. Audit output goes to `$CLAUDE_PLUGIN_DATA/audits/`, outside the repository.
- The dispatch guard denies every agent type outside the tiers and dispatch.allow_agents in config/routing.json, including general-purpose and fork, so built-in commands that spawn them (/code-review, /simplify) stop unless allowlisted.
- The stall watch (`scripts/stall_watch.py`) keeps per-agent state in `$CLAUDE_PLUGIN_DATA/stall-watch/<agent_id>.json`, removes state files older than `stall_watch.state_max_age_hours`, and fails open: its own errors never block a tool call. Its deny messages start with `mr stall watch:`.
