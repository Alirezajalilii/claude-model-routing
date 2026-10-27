# model-routing — agent guide

This project follows the workspace standard in ~/Work/AGENTS.md. Read that first. This file holds only what is specific to this project.

## Identity
- Purpose: Cost-aware model routing for Claude Code (tiered subagents, dispatch guard, audit)
- Created: 2026-10-27
- Status: scaffolded (update as the project evolves)

## Stack
(List the actual stack once chosen. Defaults from ~/Work/AGENTS.md section 6 apply until stated otherwise.)

## Apps
(One line per folder in apps/: what it is, how it is deployed.)

## Commands
All routine work goes through the Makefile: make setup, make dev, make test, make lint, make fmt, make typecheck, make build, make clean (plus make migrate / make db-reset when a database exists). Document here any target with non-obvious behaviour.

## Project-specific conventions
(Only conventions that add to or refine the workspace standard.)

## Deviations from the workspace standard
- `CLAUDE.md` is not committed. The project's own `.gitignore` ignores `/CLAUDE.md` (kept as the project chose). The file on disk holds only `@AGENTS.md`; the pre-standard content was merged into this file. Decide whether to track it: remove the `/CLAUDE.md` line from `.gitignore` and commit the one-line file.

## Current state
(What works, what is in progress, known issues. Keep short and current.)

## Gotchas
(Traps a new agent would fall into.)
