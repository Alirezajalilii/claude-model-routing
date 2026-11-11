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

## [2026-10-27] lint | Mac final audit: tests and lint pass on macOS
- `make test` had 4 failures on the Mac: `scripts/skills_inventory.py` compared a resolved `projectPath` with an unresolved project dir (macOS `/var` vs `/private/var`); the code-limit test scanned the git-ignored `.agent/` run records; the packaging test failed on the git-ignored local `CLAUDE.md`; the naming test flagged the old checkout name in this append-only log.
- Fixed: both sides are resolved; the code-limit and packaging tests look at what git ships; the wiki log is exempt from the old-name check. `make lint` validates a temporary copy of the shipped files. Result: 215 tests OK, lint passes.

## [2026-11-11] update | release 0.5.0: task contracts, mr-plan, stall watch
- Pages and files: AGENTS.md (stack version, bin/ launchers, current state, hooks line and gotchas), CHANGELOG.md, policy/sections/task-contracts.md and stall-watch.md (new), plan-contract.md, full-lane.md, config/routing.json (`stall_watch`, policy sections), hooks/hooks.json (stall watch PreToolUse group).
- Source: a comparison with Atomic Agent's Fusion mode (inter-task contracts, dependency waves, stuck-worker detection), adapted without a model call in the hook so the advisor rule stays unchanged.
- Open: the stall-watch thresholds rest on 66 healthy executor transcripts (63 on Sonnet, no stuck run measured); tune `repeat_limit` and `read_only_streak_limit` from real firings (every denial starts with `mr stall watch:`).

## [2026-11-11] update | release 0.5.1: stall watch repeat key fix
- Pages and files: AGENTS.md (stack version, current state), CHANGELOG.md, config/routing.json (`stall_watch.call_key_fields`), scripts/routing_config.py, scripts/stall_watch.py, policy/sections/stall-watch.md.
- Finding: the 0.5.0 release smoke test showed the repeat signal never fired, because the call key hashed Bash's free-text `description`. Fixed by keying on the fields that decide what a call does.
- Open: re-check the Bash input keys when the Claude Code version changes; a new parameter that changes what a call does would be ignored by the key until it is added to `call_key_fields`.

## [2026-11-12] update | release 0.6.0: mr-gate, batch verification, Haiku window
- Pages and files: AGENTS.md, CHANGELOG.md, policy/sections/gate.md (new), plan-contract.md, verifier-tiers.md, executor-tiers.md, full-lane.md, handoffs.md, calibration.md, logging.md, forbidden.md, cost.md, haiku-context.md, policy/agents/verifier.md and executor.md, config/routing.json, scripts/session_context.py, scripts/routing_audit.py, the new gate scripts and bin/mr-gate.
