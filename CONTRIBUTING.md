# Contributing

Thanks for helping. mr has no runtime dependencies: Python 3.9 or later and its standard library only.

## Layout

- `config/routing.json` is the single source of truth for tiers, roles and tunables.
- `policy/sections/` holds the policy text; `policy/agents/` holds the role body templates.
- `agents/` and `skills/routing-policy/SKILL.md` are generated. Never edit them by hand; run `make build`.
- `scripts/` holds the hooks and commands; `bin/` holds their launchers.

## Workflow

1. Open an issue before a behavior change so we can agree on the approach first.
2. Change `config/routing.json`, `policy/` or `scripts/` with tests first (`unittest`).
3. Regenerate: `make build`.
4. Run the checks:

   ```
   make test
   make lint
   ```

   `make lint` checks that the generated files are current, runs `claude plugin validate --strict` on a copy of what git would ship when the `claude` CLI is on your PATH, and runs the sensitive-data scan on the full history (`python3 -B scripts/scan_sensitive.py --history`).
5. Keep functions under 50 lines and files under 800 lines; `tests/test_code_limits.py` enforces both.
6. Use Conventional Commits (`feat:`, `fix:`, `docs:`, `test:`, `refactor:`, `chore:`), one subject line, and no personal data in messages.

## Installing and updating

Users install from the pushed repository; see the README sections "Install the plugin" and "Update the plugin". Never add a working tree as a directory marketplace: Claude Code copies git-ignored files such as .agent/ and .claude/ into the plugin cache. After installing a build from a pushed branch, run make check-install from a clean checkout of the same commit; it fails when the installed copy holds a file that is not committed at HEAD. Back up the plugin data directory before any uninstall or marketplace removal; see the README.

## Rules

- No third-party packages.
- No personal or machine-specific data anywhere: no home paths, e-mail addresses (other than `example.com`), IP addresses, tokens or session ids. The scan must pass on the full history.
- Plans, routing logs and transcripts never belong in this repository.
- There is no CI; run the checks above locally before opening a pull request.
