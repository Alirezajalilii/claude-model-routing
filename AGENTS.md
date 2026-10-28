# model-routing — agent guide

This project follows the workspace standard in ~/Work/AGENTS.md. Read that first. This file holds only what is specific to this project.

## Identity
- Purpose: Cost-aware model routing for Claude Code (tiered subagents, dispatch guard, audit)
- Created: 2026-10-27
- Status: active

## Stack
- Claude Code plugin (manifest in `.claude-plugin/plugin.json`, version 0.1.0 per CHANGELOG.md).
- Python 3.9+ standard library only; no third-party packages (CONTRIBUTING.md). Tests use `unittest`.
- Plugin parts: hooks (`hooks/hooks.json`: SessionStart runs `session_context.py --part 1` to `--part 5`, PreToolUse on `Agent|Task` runs the dispatch guard, SessionEnd runs the audit), generated subagents (`agents/`), skills (`skills/`), launchers (`bin/`).
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
- `bin/`: launchers for the plugin commands `model-routing-usage`, `model-routing-audit`, `model-routing-skills`, `model-routing-init`.
- `config/`: `routing.json`, the single source of truth for tiers, roles and tunables.
- `policy/`: policy text fragments and agent body templates rendered by `scripts/generate.py`.
- `templates/`: `model-routing-log.md` and `plans-README.md`, copied into user projects by the init-project skill.
- `tests/`: the unittest suite lives at the root, not next to the code. Reason: all Python code is in `scripts/` and `bin/`, and the suite checks cross-cutting rules (plugin manifest, code limits, generated output).
- `CHANGELOG.md`, `CONTRIBUTING.md`, `LICENSE`, `SECURITY.md`: open-source plugin repository files, not in the standard tree.
- `.claude/` (local, gitignored): Claude Code local settings; never committed.

## Current state
- Version 0.1.0 (2026-10-24) per CHANGELOG.md. The `[Unreleased]` section records the planner changes (one planner per topic, one advisor consult per plan, planners get the Edit tool) and the file-handoff, strict dispatch guard, skills-by-path, Haiku limit and audit changes.
- Branch `chore/adopt-workspace-standard` holds the workspace-standard adoption.
- The repository has 14 local branches (feature and task branches such as `agent/T09`). Do not switch branches to inspect them; read with `git show <branch>:<path>`.

## Gotchas
- `scripts/scan_sensitive.py` is referenced by CONTRIBUTING.md and by `make lint`, but it is not on this branch. It exists on `agent/T09` (commit 279a273 and related). TODO(agent): decide whether to merge it into this branch or remove the reference from CONTRIBUTING.md. Until then `make lint` skips the sensitive-data scan with a message.
- Install and update the plugin from the pushed repository through a git marketplace, never from the working tree: a directory marketplace copies git-ignored private files (`.agent/`, `.claude/`) into the plugin cache. See README.md.
- Run Python with `python3 -B` (or `PYTHONDONTWRITEBYTECODE=1`); the scripts never write bytecode.
- Settings the dispatch guard and session policy check (warnings, not errors): `CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH` should be `1`; `CLAUDE_CODE_EFFORT_LEVEL`, `CLAUDE_CODE_SUBAGENT_MODEL` and `CLAUDE_CODE_SUBAGENT_MODEL_FORCE` should be unset. See `.env.example`.
- `data/` and `.agent/` are gitignored. Audit output goes to `$CLAUDE_PLUGIN_DATA/audits/`, outside the repository.
- The dispatch guard denies every agent type outside the tiers and dispatch.allow_agents in config/routing.json, including general-purpose and fork, so built-in commands that spawn them (/code-review, /simplify) stop unless allowlisted.
