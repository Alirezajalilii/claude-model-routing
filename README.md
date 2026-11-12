# mr: model routing for Claude Code

[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Claude Code plugin](https://img.shields.io/badge/Claude%20Code-plugin-d97757.svg)](https://code.claude.com/docs/en/discover-plugins)
[![Python 3.9+, standard library only](https://img.shields.io/badge/python-3.9%2B%20stdlib%20only-3776ab.svg)](#requirements)

mr is a Claude Code plugin that keeps your strongest model on planning and review and sends the hands-on coding to cheaper subagents. A planner writes each task with the files it may touch and the tests it must pass. A Haiku executor implements it test-first, and a script checks the commits before the task merges.

In one logged run on this repository, Haiku executors finished 15 tasks. Priced at Anthropic's API list prices, their tokens come to about $0.80. The same tokens would cost about $14.08 at Sonnet 5.5 prices and about $28.16 at Opus 5.5 prices. [How this was measured, and what it leaves out](docs/cost.md).

## Install the plugin

You need Claude Code and `python3` 3.9 or later. [Requirements](#requirements) has the versions and platforms.

```sh
claude plugin marketplace add Alirezajalilii/claude-model-routing
claude plugin install mr@claude-model-routing
```

This installs at user scope, so the routing policy and the dispatch guard apply to every Claude Code session in every project, including the `/code-review` and `/simplify` limits described under [What runs on your machine](#what-runs-on-your-machine). To try it on one repository first, run the install from that repository with `claude plugin install mr@claude-model-routing --scope local`.

Claude Code 2.1.292 and later can do both in one command:

```sh
claude plugin install mr --marketplace Alirezajalilii/claude-model-routing
```

Inside a session, `/plugin install mr --marketplace Alirezajalilii/claude-model-routing` opens the plugin panel, so you can read what the plugin runs before you confirm (Claude Code 2.1.275 and later).

If `marketplace add` fails with an SSH error, Claude Code found an SSH key for github.com and tried SSH. Run the command again with `CLAUDE_CODE_PLUGIN_PREFER_HTTPS=1` in front of it, or pass the full URL `https://github.com/Alirezajalilii/claude-model-routing`.

Then restart Claude Code and set up each project you want to route:

1. Run `/mr:init-project` in the project. It creates `docs/plans/README.md` and `docs/model-routing-log.md` and adds a one-line pointer to the routing policy in your `CLAUDE.md`.
2. Add `CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH` to the `env` block of `~/.claude/settings.json`, so that subagents cannot start subagents of their own:

   ```json
   { "env": { "CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH": "1" } }
   ```

3. Ask Claude to run `mr-doctor`. It checks the setup above and prints a fix for anything that is off.

## How a session runs

Small, clear changes take the fast lane: one executor, no planner. Work that needs a design decision takes the full lane:

1. Read-only scouts on Haiku or Sonnet gather the evidence the planner asks for.
2. A planner on Sonnet or Opus writes a plan file. Every task names the files it may touch, its Test Cases, its executor tier and a Gate block. The planner consults Claude Code's advisor once per plan.
3. Executors start on Haiku. Each one commits the failing tests first, then the change that makes them pass.
4. `mr-gate` checks each task against its Gate block: the commits stay inside the task's files, the new tests failed before the change, and the green commands pass.
5. Verifiers on Sonnet or Opus run when the plan marks a risk (authentication, payments, data integrity, migrations, security), when a task ran below its planned tier, or after a failed check. A Haiku executor that cannot finish hands the task to its planned Sonnet tier.

Tier agents are named `<role>-<model>-<effort>` with the roles `scout`, `plan`, `exec`, `verify`, and the main session dispatches them as `mr:<tier>`, for example `mr:exec-haiku-med`.

| Role | Tiers |
| --- | --- |
| scout | `scout-haiku-low`, `scout-haiku-med`, `scout-sonnet-high` |
| plan | `plan-sonnet-high`, `plan-opus-high`, `plan-opus-xhigh` |
| exec | `exec-haiku-low`, `exec-haiku-med`, `exec-haiku-high`, `exec-sonnet-med`, `exec-sonnet-high`, `exec-sonnet-xhigh` |
| verify | `verify-sonnet-med`, `verify-sonnet-high`, `verify-opus-high` |

The policy lives in `config/routing.json` and `policy/`. A session-start hook loads it into the main session, and the `mr:routing-policy` skill holds the full text.

## What it costs

One run on this repository (2026-11-11, 15 tasks), priced with `mr-cost` at API list prices as of 2026-11-12, with 5-minute cache writes. Details in [docs/cost.md](docs/cost.md).

| Group | Agents | At the models that ran | Same tokens at Sonnet 5.5 | Same tokens at Opus 5.5 |
|---|---|---|---|---|
| scout | 7 | $0.48 | $8.86 | $17.72 |
| plan | 3 | $7.59 | $4.39 | $8.78 |
| exec | 15 | $0.80 | $14.08 | $28.16 |
| verify | 9 | $2.40 | $2.40 | $4.79 |
| total | 34 | $11.27 | $29.73 | $59.45 |

Read these numbers with their limits:

- They re-price the tokens of one run. A Sonnet or Opus executor would have used a different number of tokens, so this is not a comparison of two runs.
- The main session is not included: `mr-usage` reads subagent transcripts only.
- Every subagent starts with fixed context, roughly 15K tokens of skill listing when several hundred skills are installed. Routing pays off on multi-step work and costs more than it saves on a one-line edit.
- Haiku 5.5 bills prompts over 100K tokens at five times its base rate. This run's Haiku executors stayed under that (peak 91,105 tokens); `mr-cost` prices longer prompts at the higher rate.

To price one of your own sessions, ask Claude to run:

```sh
mr-usage <session-id> --json | mr-cost -
```

The session id is in the mr section of the session context, and `/mr:routing-report` collects it for you.

## Usage limits on Pro and Max

On a subscription, Claude Code draws on the same usage limits as claude.ai: a five-hour session limit and a weekly limit. Anthropic lists the model you use among the factors that affect usage, but it does not publish how much each model counts. mr moves the token-heavy executor work to Haiku, so the same work should use less of your limit. I have not measured how much longer a session lasts with it. If you measure it, please open an issue with your numbers.

If `ANTHROPIC_API_KEY` is set in your environment, Claude Code bills that key at API rates instead of using your plan. `mr-doctor` tells you when it is set.

## What runs on your machine

| Event | Script | What it does |
| --- | --- | --- |
| SessionStart | `scripts/session_context.py --part 1` to `--part 5` | Adds the routing policy to the main session's context and warns about settings that override tier models or efforts. After a compaction only part 1 runs, as a pointer to the `mr:routing-policy` skill. |
| PreToolUse on `Agent`, `Task`, `Skill` | `scripts/dispatch_guard.py` | Blocks a subagent call that breaks the policy, for example a tier prompt without a `Skills:` line or an `Output:` path, a `model` or `effort` override, an agent type that is not a tier, or a subagent that tries to start another agent. Its messages start with `mr dispatch guard:`. |
| PreToolUse on `Read`, `Edit`, `Write`, `Grep`, `Glob`, `Bash`, `Skill` | `scripts/stall_watch.py` | Watches executors only. It nudges, then stops, an executor that repeats the same call or keeps reading without changing anything. Its messages start with `mr stall watch:`. |
| SessionEnd | `scripts/routing_audit.py --hook` | Writes an audit of the session (policy flags and the executor tier mix) to `audits/` in the plugin data directory. |

The scripts use the Python standard library and make no network requests. They read your Claude Code transcripts, skills and environment. They write to the plugin data directory and, when you run `mr-init`, to your project's `docs/` folder and `CLAUDE.md`. `mr-doctor` runs `claude --version`. `mr-gate` runs the commands written in a plan's Gate blocks, so read a plan before the main session gates it.

The dispatch guard denies every agent type that is neither a tier nor on its allowlist (`claude-code-guide` and `statusline-setup`). That includes `general-purpose` and `fork`, so commands such as `/code-review` and `/simplify` stop with a `mr dispatch guard:` message while the plugin is on. Turn the plugin off in `/plugin` when you need them.

## Commands

The plugin puts these commands on the PATH of Claude Code's Bash tool. Ask Claude to run them.

| Command | What it does |
| --- | --- |
| `mr-init [--claude-md]` | Creates `docs/plans/README.md` and `docs/model-routing-log.md` in the project; `--claude-md` also adds the policy pointer to `CLAUDE.md`. |
| `mr-doctor` | Checks Python, the Claude Code version, the settings the policy relies on, `ANTHROPIC_API_KEY` and the project setup. |
| `mr-usage <session-id>` | Model, effort and tokens for each subagent of a session; `--json` prints machine-readable rows. |
| `mr-cost <file>` or `mr-cost -` | Prices `mr-usage --json` rows at API list prices and re-prices the same tokens at Sonnet 5.5 and Opus 5.5 rates. |
| `mr-audit <session-id>` | Policy compliance flags for a session. |
| `mr-skills` | The skills inventory the planner uses to assign skills to tasks. |
| `mr-plan waves <plan>`, `mr-plan check` | Validates a plan's task contracts and prints the order the tasks can run in. |
| `mr-gate <plan> <task-id> <worktree>` | Runs one task's gate and writes the gate file. |

Skills: `/mr:init-project` sets up a project, `/mr:routing-report` collects a session's routing evidence for `docs/model-routing-log.md`, and `mr:routing-policy` holds the full policy text.

## Requirements

- Claude Code. The plugin's behavior was checked on Claude Code 2.1.306 to 2.1.318; older versions are untested.
- `python3` 3.9 or later on macOS or Linux. The test suite passes on macOS and on Linux with Python 3.9. No packages to install.
- Windows is not supported. The hooks call `python3` and the commands depend on a `#!/usr/bin/env python3` line. WSL may work; I have not tested it.
- Planner agents use Claude Code's advisor tool. I have not tested a setup where it is unavailable.

## Update the plugin

```sh
claude plugin marketplace update
claude plugin update mr@claude-model-routing
```

Then restart Claude Code. Third-party marketplaces do not update on their own until you turn it on: run `/plugin`, open the **Marketplaces** tab, select this marketplace and choose **Enable auto-update**.

To pin a release, add the marketplace with a tag, for example `claude plugin marketplace add Alirezajalilii/claude-model-routing#v0.7.0`.

## Uninstall

The plugin data directory, `~/.claude/plugins/data/<plugin>-<marketplace>/`, holds your session audits, and `claude plugin marketplace remove` deletes it. Copy it somewhere first, then uninstall with:

```sh
claude plugin uninstall mr@claude-model-routing --keep-data
```

If you reinstall later, copy the audits back with `cp -Rpn <backup>/. ~/.claude/plugins/data/<plugin>-<marketplace>/`.

## When mr is not worth it

- Single edits and quick questions. Each subagent starts with fixed context, so the main session does small work for less.
- Work you do not want to plan. The full lane writes a plan file, red and green commits and a gate file for every task.
- Sessions that need `/code-review`, `/simplify` or other commands that start `general-purpose` agents.
- Windows machines (see [Requirements](#requirements)).

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). Maintainers: after installing from the pushed repository, run `make check-install` from a clean checkout of the same commit. It fails if the installed copy holds any file that is not committed.

## License

MIT. See [LICENSE](LICENSE).
