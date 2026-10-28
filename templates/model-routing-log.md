# Model routing log

Per-task record of how work was routed under the Model Routing Policy v2.1 (plugin mr, section "Logging"). The main session appends one row per task to the Log table. Tokens come from `mr-usage <session-id>` (taken from each subagent's `message.usage`); log tokens, not dollars. Plans live in `docs/plans/`.

Gate checks (Full lane workflow, step 4): R = red, I = test integrity, C = coverage, S = scope, G = green, P = report. Record each as pass, fail or n/a (for example `R pass, I pass, C pass, S pass, G fail, P pass`). Verifier reason: plan trigger, gate failure, post-FIX, or sample (with the sampling draw).

## Log

| Date | Task type | Lane | Planner tier | Executor tier | Verifier tier | Skills assigned / skills loaded per agent (incl. unlisted loads and why) | Gate results per check | Verifier ran? Why, verdict | FIX rounds | REPLANs | Escalations | Outcome | Input / output / cache tokens per agent |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |

## Aggregate

Update at the end of every session. It belongs in the project's claude.md; keep it here only where claude.md is generated.

| Tier | Task type | Tasks | First-pass gate pass rate | Average FIX rounds | Average tokens (input / output / cache) | Sampled-verifier defect rate |
| --- | --- | --- | --- | --- | --- | --- |

## Proposed rule changes

Proposals only; the policy is never changed silently. Add an entry when the data shows a task type consistently passing one tier lower, consistently escalating, a planner tier consistently producing REPLANs, a skill consistently loaded unlisted, a recurring Skill Gap, or a calibration-sampling threshold crossed (under 5% defects after 50 tasks: drop sampling to 5%; over 10% for a tier or task type: propose Verify: yes for it).

None yet.
