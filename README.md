# model-routing

Cost-aware model routing for Claude Code (tiered subagents, dispatch guard, audit)

The plugin is named `mr` (short for model routing). Its tier agents are named `<role>-<model>-<effort>` with the roles `scout`, `plan`, `exec`, `verify`, the models `haiku`, `sonnet`, `opus` and the efforts `low`, `med`, `high`, `xhigh`, and are dispatched as `mr:<tier>`, for example `mr:exec-haiku-med`.

## Quickstart
1. cp .env.example .env and fill in values
2. make setup
3. make dev

## Install the plugin
The plugin installs from the pushed Git repository, never from a working tree: a directory marketplace copies every file of the checkout, including git-ignored private files, into the plugin cache.
1. Add the marketplace from the SSH address of your copy of this repository: `claude plugin marketplace add git@github.com:<owner>/model-routing.git`
2. Install at user scope: `claude plugin install mr@claude-model-routing --scope user`
3. From a clean `main` checkout, confirm that the installed copy holds only committed files: `make check-install`
4. Restart Claude Code sessions.

## Update the plugin
1. Merge your change to `main` and push `main`.
2. If the update would report no change, raise `version` in `.claude-plugin/plugin.json`, commit and push.
3. Before any `claude plugin uninstall` or `claude plugin marketplace remove`, copy the plugin data directory (`~/.claude/plugins/data/<plugin>-<marketplace>/`, which holds the audits) to a backup: `marketplace remove` deletes it. Uninstall only with `--keep-data`, and copy missing files back with `cp -Rpn` afterwards.
4. `claude plugin marketplace update`
5. `claude plugin update mr@claude-model-routing`
6. From a clean `main` checkout run `make check-install`, then restart sessions.

## Documentation
- Architecture: docs/architecture.md
- Agent rules: AGENTS.md
