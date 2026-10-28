## Verifier tier selection (made by the planner)
A verifier is never weaker than the executor it checks.
- Haiku executor tiers → `verify-sonnet-med`.
- `exec-sonnet-med` and `exec-sonnet-high` → `verify-sonnet-high`.
- `exec-sonnet-xhigh`, and any task touching authentication, payments, data integrity, migrations, or security → `verify-opus-high`.

### Verification triggers (marked by the planner as Verify: yes)
- the task touches authentication, payments, data integrity, migrations, or security;
- the executor tier is `exec-sonnet-xhigh`;
- acceptance cannot be fully expressed as automated tests: UI behavior, documentation correctness, performance, or infrastructure configuration.

All other tasks are Verify: no and rely on the gate.
