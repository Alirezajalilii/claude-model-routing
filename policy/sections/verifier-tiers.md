## Verifier tier selection (made by the planner)
A verifier is never weaker than the executor it checks.
- Haiku executor tiers → `verify-sonnet-med`.
- `exec-sonnet-med` and `exec-sonnet-high` → `verify-sonnet-high`.
- `exec-sonnet-xhigh`, and any task touching authentication, payments, data integrity, migrations, or security → `verify-opus-high`.

A task that starts below its planned tier names two verifier tiers: `verify-sonnet-med` for its start tier, and the tier the list above gives for its planned tier, used after a fallback. A task touching authentication, payments, data integrity, migrations, or security, or planned on `exec-sonnet-xhigh`, keeps `verify-opus-high` at both tiers.

### Verification triggers (marked by the planner as Verify: yes)
- the task starts below its planned executor tier;
- the task touches authentication, payments, data integrity, migrations, or security;
- the executor tier is `exec-sonnet-xhigh`;
- acceptance cannot be fully expressed as automated tests: UI behavior, documentation correctness, performance, or infrastructure configuration.

All other tasks are Verify: no and rely on the gate.
