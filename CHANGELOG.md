# Changelog

All notable changes to this project are documented here. The format follows Keep a Changelog, and the project uses Semantic Versioning.

## [Unreleased]

### Changed
- Planners own the solution: they plan from the user's request and the evidence, not from the dispatcher's framing, and record any departure under assumptions.
- One planner instance per topic. Small, clear work and wrap-up never go to a planner; planners can reply OUT_OF_TOPIC or NO_PLAN_NEEDED.
- One advisor consult per plan, after the complete draft is written; no second consult to check the revision.
- Planners get the Edit tool, so a REPLAN edits only the affected task instead of rewriting the plan file.

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
