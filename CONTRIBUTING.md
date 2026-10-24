# Contributing

Thanks for helping. This plugin has no runtime dependencies: Python 3.9 or later and its standard library only.

## Layout

- `config/routing.json` is the single source of truth for tiers, roles and tunables.
- `policy/sections/` holds the policy text; `policy/agents/` holds the role body templates.
- `agents/` and `skills/routing-policy/SKILL.md` are generated. Never edit them by hand.

## Workflow

1. Change `config/routing.json`, `policy/` or `scripts/`, with tests first (`unittest`).
2. Regenerate: `python3 -B scripts/generate.py`.
3. Run every check:

```
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -v
python3 -B scripts/generate.py --check
claude plugin validate . --strict
python3 -B scripts/scan_sensitive.py --history
```

4. Keep functions under 50 lines and files under 800 lines; `tests/test_code_limits.py` enforces both.
5. Use Conventional Commits (`feat:`, `fix:`, `docs:`, `test:`, `refactor:`, `chore:`), one subject line, and no personal data in messages.

## Rules

- No third-party packages.
- No personal or machine-specific data anywhere: no home paths, e-mail addresses (other than `example.com`), IP addresses, tokens or session ids. The scan must pass on the full history.
- Plans, routing logs and transcripts never belong in this repository.
- There is no CI; run the checks above locally before opening a pull request.
