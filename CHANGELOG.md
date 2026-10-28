# Changelog

All notable changes to this project are documented here. The format follows Keep a Changelog, and the project uses Semantic Versioning.

## [Unreleased]

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
- `hooks/hooks.json` runs SessionStart as `session_context.py --part 1` to `--part 5`, matching the dispatcher parts in config.
- The skills inventory table has the columns Skill, Scope, Path and Description, and `model-routing-skills` accepts `--out FILE`.
- `model-routing-usage` counts Read calls on `*/SKILL.md` in `skill_calls` and reports `peak_prompt_tokens` in its JSON.
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
