## Verifier tier selection (made by the planner)
A verifier is never weaker than the executor it checks.
- Haiku executor tiers → `verify-sonnet-med`.
- `exec-sonnet-med` and `exec-sonnet-high` → `verify-sonnet-high`.
- `exec-sonnet-xhigh`, and any task touching authentication, payments, data integrity, migrations, or security → `verify-opus-high`.

A task that starts below its planned tier names two verifier tiers: `verify-sonnet-med` for its start tier, and the tier the list above gives for its planned tier, used after a fallback. A task touching authentication, payments, data integrity, migrations, or security, or planned on `exec-sonnet-xhigh`, keeps `verify-opus-high` at both tiers.

### Verification triggers (marked by the planner)
`Verify: task` (its own verifier, before the task merges) when the task touches authentication, payments, data integrity, migrations, or security, or its planned tier is `exec-sonnet-xhigh`.
`Verify: batch` (one verifier for several tasks, after they merge into the integration branch) when no task trigger applies and:
- the task starts below its planned executor tier;
- acceptance cannot be fully expressed as automated tests: UI behavior, documentation correctness, performance, or infrastructure configuration.

All other tasks are `Verify: no` and rely on the gate.
