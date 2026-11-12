# Architecture — model-routing

## Context
mr is a Claude Code plugin for cost-aware model routing. It gives a dispatcher session tiered subagents (scouts, planners, executors, verifiers) on Haiku, Sonnet and Opus at chosen effort levels, injects the routing policy at session start, blocks delegations that break the policy, and writes a session audit. Users are developers who run Claude Code and install the plugin. Boundary: the plugin runs inside Claude Code and the user's own machine; it has no server, no database and no network component of its own.

## Components
There are no apps and no packages. The plugin is made of these parts:
- **Plugin manifest and marketplace** (`.claude-plugin/`): `plugin.json` (name and the release version; see CHANGELOG.md) and `marketplace.json` (source `.`). Tech: JSON.
- **Hooks** (`hooks/hooks.json`, scripts in `scripts/`): SessionStart runs `session_context.py --part 1` to `--part 5` to inject the policy (after a compaction only part 1 runs, with a pointer to the `mr:routing-policy` skill); PreToolUse on `Agent|Task|Skill` runs `dispatch_guard.py`; PreToolUse on `Read|Edit|Write|Grep|Glob|Bash|Skill` runs `stall_watch.py` for executors; SessionEnd runs `routing_audit.py --hook`. Tech: Python 3.9+ standard library.
- **Config and policy** (`config/routing.json`, `policy/`): the single source of truth for tiers, roles, tunables and policy sections. `scripts/routing_config.py` loads and validates it; `scripts/policy_text.py` renders the policy text.
- **Generated agents and skill** (`agents/*.md`, `skills/routing-policy/SKILL.md`): produced by `scripts/generate.py`; never edited by hand. Owns no data.
- **Skills** (`skills/init-project`, `skills/routing-policy`, `skills/routing-report`): instructions Claude loads on demand. `init-project` copies `templates/` into a user project.
- **Commands** (`bin/mr-*`): launchers for `scripts/routing_audit.py`, `subagent_usage.py`, `skills_inventory.py`, `init_project.py`, `plan_cli.py` (`mr-plan`) and `gate_cli.py` (`mr-gate`, built on `plan_gate.py`, `gate_checks.py` and `gate_git.py`). `cost_estimate.py` backs `mr-cost`, which prices `mr-usage --json` rows at API list prices and re-prices the same tokens at Sonnet 5.5 and Opus 5.5 rates. `doctor.py` backs `mr-doctor`, which checks Python, the Claude Code version, the settings the policy relies on, `ANTHROPIC_API_KEY` and the project setup.
- **Sensitive-data scan** (`scripts/scan_sensitive.py`, `scripts/sensitive_rules.py`): `make lint` runs `scan_sensitive.py --history`, which scans the full git history; `sensitive_rules.py` holds the rules and never calls git. Tech: Python 3.9+ standard library.
- **Transcript reader** (`scripts/transcripts.py`, `subagent_usage.py`): reads Claude Code session JSONL transcripts; reads only.
- **Data owned**: the session audit written under `$CLAUDE_PLUGIN_DATA/audits/`, outside the repository. `init-project` writes its two files into the user's own project, not into this repository.

## Data flow
```mermaid
flowchart LR
    CONF[config/routing.json] --> GEN[scripts/generate.py]
    POL[policy/] --> GEN
    GEN --> AG[agents/*.md]
    GEN --> SK[skills/routing-policy/SKILL.md]
    CONF --> SC[session_context.py]
    POL --> SC
    SS[SessionStart hook] --> SC --> CC[Claude Code session]
    CC -->|Agent or Task call| DG[dispatch_guard.py]
    DG -->|allow or block with reason| CC
    SE[SessionEnd hook] --> RA[routing_audit.py]
    TR[session transcript JSONL] --> RA
    RA --> AUD[$CLAUDE_PLUGIN_DATA/audits]
```

## External services
- Claude Code (host runtime): loads the plugin, runs hooks, dispatches subagents.
- Anthropic models named in the tiers: Haiku, Sonnet and Opus, selected per subagent. The plugin calls no model API directly.
- No third-party APIs, storage or queues.

## Deployment
- Not deployed as a service. Distributed as a Claude Code plugin: users add the marketplace at this repository (`.claude-plugin/marketplace.json`, source `.`) or load it from a checkout.
- Built with `make build` (regenerates `agents/` and the reference skill). No container image.
- Released by semver tag. Changes are recorded in CHANGELOG.md. No tags exist yet.
- No CI; checks run locally through `make lint` and `make test`.

## Key decisions
No ADRs yet. Decisions visible in the code and changelog, pending ADRs:
- Tiers and roles are data in `config/routing.json`; agent files are generated from it.
- The dispatch guard enforces policy at PreToolUse on `Agent|Task|Skill` rather than trusting the dispatcher prompt.
- No third-party Python packages (CONTRIBUTING.md).
