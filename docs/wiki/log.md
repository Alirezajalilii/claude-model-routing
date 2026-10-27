# Wiki log — model-routing

Append-only. Header format: ## [YYYY-MM-DD] ingest|update|query|lint | short title

## [2026-10-27] update | project scaffolded
- Created from ~/Work/templates/project.

## [2026-10-27] ingest | migrated from Linux workstation
- Source on the Linux workstation: `work/claude-model-routing` (imported in Phase 1, see the migration logs under ~/Work/logs/linux-migration/).
- Merged into AGENTS.md: stack, commands (Makefile targets wired to unittest, generate.py, claude plugin validate), deviations (plugin files at root, config/, policy/, templates/, tests/).
- Makefile: every required target now runs the project's real commands; `make lint` skips `scripts/scan_sensitive.py` with a message because the file is absent on this branch.
- Gotcha: CONTRIBUTING.md and the lint target reference `scripts/scan_sensitive.py`, which exists only on branch `agent/T09`. TODO(agent): merge or drop the reference.
- Gotcha: `agents/*.md` and `skills/routing-policy/SKILL.md` are generated; change `config/routing.json` or `policy/` and run `make build`.
- `/CLAUDE.md` stays untracked as the project's own `.gitignore` rule; the deviation is recorded in AGENTS.md.
