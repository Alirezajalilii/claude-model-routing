# model-routing

Cost-aware model routing for Claude Code (tiered subagents, dispatch guard, audit)

## Quickstart
1. cp .env.example .env and fill in values
2. make setup
3. make dev

## Install the plugin
The plugin installs from the pushed Git repository, never from a working tree: a directory marketplace copies every file of the checkout, including git-ignored private files, into the plugin cache.
1. Add the marketplace from the SSH address of your copy of this repository: `claude plugin marketplace add git@github.com:<owner>/model-routing.git`
2. Install at user scope: `claude plugin install model-routing@claude-model-routing --scope user`
3. From a clean `main` checkout, confirm that the installed copy holds only committed files: `make check-install`
4. Restart Claude Code sessions.

## Update the plugin
1. Merge your change to `main` and push `main`.
2. If the update would report no change, raise `version` in `.claude-plugin/plugin.json`, commit and push.
3. `claude plugin marketplace update`
4. `claude plugin update model-routing@claude-model-routing`
5. From a clean `main` checkout run `make check-install`, then restart sessions.

## Documentation
- Architecture: docs/architecture.md
- Decisions: docs/decisions/
- Specs: docs/specs/
- API: docs/api/
- Runbooks: docs/runbooks/
- Knowledge base: docs/wiki/index.md
- Agent rules: AGENTS.md
