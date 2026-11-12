# mr: agent guide

Rules for coding agents and contributors working on this repository. User documentation is in README.md; the contribution workflow is in CONTRIBUTING.md.

## Stack
- Claude Code plugin named `mr`. Manifest: `.claude-plugin/plugin.json`; the version is there and in CHANGELOG.md.
- Python 3.9+ standard library only; no third-party packages. Tests use `unittest`.
- Plugin parts: hooks (`hooks/hooks.json`: SessionStart runs `session_context.py --part 1` to `--part 5` (after a compaction only part 1, a pointer to the routing-policy skill), PreToolUse on `Agent|Task|Skill` runs the dispatch guard, PreToolUse on the executor tools runs the stall watch (`scripts/stall_watch.py`), SessionEnd runs the audit), generated subagents (`agents/`), skills (`skills/`), launchers (`bin/`).
- Single source of truth for tiers, roles and tunables: `config/routing.json`. Policy text: `policy/`.
- No database, no queue, no containers, no CI.

## Commands
All routine work goes through the Makefile. Run `make help` for the list.
- `make setup`: prints the Python version. Nothing to install.
- `make dev`: not applicable; prints why and exits 0.
- `make test`: `python3 -m unittest discover -s tests -v` with `PYTHONDONTWRITEBYTECODE=1`.
- `make lint`: `scripts/generate.py --check` (fails if generated files are stale), then `scripts/render_charts.py --check`, then `claude plugin validate --strict` on a temporary copy of what git would ship (tracked plus untracked, not ignored) if the `claude` CLI is on PATH, then `scripts/scan_sensitive.py --history`.
- `make check-install`: fails if the installed plugin cache holds any file not committed at HEAD (run after install or update, from a clean checkout of the installed commit).
- `make fmt`, `make typecheck`: not applicable; print why and exit 0.
- `make build`: runs `scripts/generate.py` and rewrites the generated files `agents/*.md` and `skills/routing-policy/SKILL.md`.
- `make charts`: runs `scripts/render_charts.py` and rewrites the data charts in `docs/assets/chart-*.svg` from `docs/case-study/` and `docs/cost/`; `make lint` fails when they are stale.
- `make clean`: removes `__pycache__` directories outside `.git`.

## Conventions
- `agents/` and `skills/routing-policy/SKILL.md` are generated. Never edit them by hand: change `config/routing.json` or `policy/`, then `make build`.
- Change `config/routing.json`, `policy/` or `scripts/` with tests first (`unittest`).
- Functions stay under 50 lines and files under 800 lines; `tests/test_code_limits.py` enforces both.
- Conventional Commits (`feat:`, `fix:`, `docs:`, `test:`, `refactor:`, `chore:`), one subject line, no personal data in messages.
- No personal or machine-specific data anywhere: no home paths, no e-mail addresses other than `example.com`, no IP addresses, tokens or session ids.
- Plans, routing logs and transcripts never belong in this repository (`docs/plans/` and `docs/model-routing-log.md` are gitignored).
- `docs/cost/` holds token tables derived from a routing log, with no session ids, paths or transcript text.

## Layout
- `.claude-plugin/`, `agents/`, `hooks/`, `skills/` sit at the repository root: the Claude Code plugin format and the marketplace entry (`source: "."` in `.claude-plugin/marketplace.json`) require them at the plugin root.
- `bin/`: launchers for the plugin commands `mr-usage`, `mr-audit`, `mr-skills`, `mr-init`, `mr-plan`, `mr-gate`, `mr-cost`, `mr-doctor`.
- `config/`: `routing.json`.
- `policy/`: policy text fragments and agent body templates rendered by `scripts/generate.py`.
- `scripts/`: the hook scripts and the command implementations.
- `templates/`: `model-routing-log.md` and `plans-README.md`, copied into user projects by the init-project skill.
- `tests/`: the unittest suite, at the root because all Python code is in `scripts/` and `bin/` and the suite checks cross-cutting rules (plugin manifest, code limits, generated output).
- `docs/architecture.md`; `docs/cost.md` with its data in `docs/cost/`.
- `CHANGELOG.md`, `CONTRIBUTING.md`, `LICENSE`, `SECURITY.md`.
- `.agent/`, `.claude/` and `CLAUDE.md` are git-ignored. If your tool reads CLAUDE.md, create one locally holding the single line `@AGENTS.md`.

## Gotchas
- Install and update the plugin from the pushed repository through a git marketplace, never from the working tree: a directory marketplace copies git-ignored private files (`.agent/`, `.claude/`) into the plugin cache. See README.md.
- Run Python with `python3 -B` (or `PYTHONDONTWRITEBYTECODE=1`); the scripts never write bytecode.
- Tier names are generated as `<role prefix>-<model>-<effort label>` from `roles.*.prefix` and `effort_labels` in `config/routing.json`; the agent `effort` value stays the real effort (`medium`, not `med`).
- `claude plugin marketplace remove` deletes the plugin data directory (audits). Back it up before removing the marketplace or uninstalling, uninstall only with `--keep-data`, and restore it with `cp -Rpn`.
- Settings the dispatch guard and session policy check (warnings, not errors): `CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH` should be `1`; `CLAUDE_CODE_EFFORT_LEVEL`, `CLAUDE_CODE_SUBAGENT_MODEL` and `CLAUDE_CODE_SUBAGENT_MODEL_FORCE` should be unset. See `.env.example`.
- `.agent/` is gitignored. Audit output goes to `$CLAUDE_PLUGIN_DATA/audits/`, outside the repository.
- The dispatch guard denies every agent type outside the tiers and dispatch.allow_agents in config/routing.json, including general-purpose and fork, so built-in commands that spawn them (/code-review, /simplify) stop unless allowlisted.
- The stall watch (`scripts/stall_watch.py`) keeps per-agent state in `$CLAUDE_PLUGIN_DATA/stall-watch/<agent_id>.json`, removes state files older than `stall_watch.state_max_age_hours`, and fails open: its own errors never block a tool call. Its deny messages start with `mr stall watch:`. Two calls count as the same when the tool and the fields listed for it in `stall_watch.call_key_fields` match (Bash: `command`, `timeout`, `run_in_background`; any other tool: its whole input), so free-text fields such as the Bash `description` never hide a repeat.
