# What mr costs: one logged run, priced

The executors of the 2026-11-11 run cost $0.80 at the models that ran, $14.08 at Sonnet 5.5 and $28.16 at Opus 5.5 (5-minute cache writes). The whole run, including scouts, planners and verifiers, cost $11.27 at the models that ran, $29.73 at Sonnet 5.5 and $59.45 at Opus 5.5. These are list-price estimates of one run.

## The run

Date: 2026-11-11. The run had 15 tasks across three plans of this repository's own development (task contracts and `mr-plan`, the stall watch, the stall watch's repeat key), plus two releases (0.5.0, 0.5.1) and one rename. Every executor ran on Haiku. There were 9 `verify-sonnet-med` runs, all PASS. Scouts ran as `scout-haiku-med`, and the planners as `plan-opus-high`, `plan-opus-xhigh` and `plan-sonnet-high`, as in the dataset.

## Prices used

The prices below are the ones `mr-cost` applies. They are USD per 1M tokens, as of 2026-11-12, from https://platform.claude.com/docs/en/about-claude/pricing.

| Model | Input | Output | Cache write, 5 minutes | Cache write, 1 hour | Cache read |
|---|---|---|---|---|---|
| claude-haiku-5-5 (prompts up to 100K tokens) | 0.10 | 0.50 | 0.125 | 0.20 | 0.01 |
| claude-haiku-5-5 (prompts over 100K tokens) | 0.50 | 2.50 | 0.625 | 1.00 | 0.05 |
| claude-sonnet-5-5 | 2 | 10 | 2.50 | 4 | 0.10 |
| claude-opus-5-5 | 4 | 20 | 5 | 8 | 0.20 |

## Results with 5-minute cache writes

| Group | Agents | At the models that ran | Same tokens at Sonnet 5.5 | Same tokens at Opus 5.5 |
|---|---|---|---|---|
| scout | 7 | $0.48 | $8.86 | $17.72 |
| plan | 3 | $7.59 | $4.39 | $8.78 |
| exec | 15 | $0.80 | $14.08 | $28.16 |
| verify | 9 | $2.40 | $2.40 | $4.79 |
| total | 34 | $11.27 | $29.73 | $59.45 |

## Results with 1-hour cache writes

| Group | Agents | At the models that ran | Same tokens at Sonnet 5.5 | Same tokens at Opus 5.5 |
|---|---|---|---|---|
| scout | 7 | $0.62 | $11.56 | $23.13 |
| plan | 3 | $9.03 | $5.27 | $10.55 |
| exec | 15 | $1.02 | $18.32 | $36.64 |
| verify | 9 | $3.42 | $3.42 | $6.84 |
| total | 34 | $14.08 | $38.57 | $77.15 |

## What these numbers do not show

- The main session is not included. `mr-usage` reads subagent transcripts only.
- The re-priced columns keep the same tokens. A run on Sonnet or Opus would use a different number of tokens, so this is not a comparison of two runs.
- Quality is not compared. In this run the gate passed every task and 9 of 9 verifier runs passed. A defect (the stall watch's repeat key never fired) was found after the 0.5.0 release by a smoke test, not by a gate or verifier.
- Every Haiku prompt in this run stayed under 100K tokens (peak 91,105). Since 0.6.0, Haiku agents run on the full context window, so longer prompts bill at the higher rate, and `mr-cost` prices them that way.
- On a subscription these tokens count against usage limits, not dollars. Anthropic does not publish how each model counts.

## Reproduce

To price the dataset in this repository, run:

```bash
python3 -B bin/mr-cost docs/cost/2026-11-11-run.json
python3 -B bin/mr-cost docs/cost/2026-11-11-run.json --cache-ttl 1h
```

To price your own sessions, run `mr-usage <session-id> --json | mr-cost -`.

The dataset rows come from the project's routing log. Tokens are as recorded by `mr-usage`, model ids follow each agent's tier, and `peak_prompt_tokens` is the run's stated peak.

## Agents included

| Label | Tier | Role |
|---|---|---|
| scout-1 | scout-haiku-med | scout |
| scout-2 | scout-haiku-med | scout |
| scout-3 | scout-haiku-med | scout |
| scout-4 | scout-haiku-med | scout |
| scout-5 | scout-haiku-med | scout |
| plan-A | plan-opus-high | plan |
| plan-B | plan-opus-xhigh | plan |
| plan-C | plan-sonnet-high | plan |
| scout-C1 | scout-haiku-med | scout |
| scout-C2 | scout-haiku-med | scout |
| A-T1 | exec-haiku-high | exec |
| A-T2 | exec-haiku-med | exec |
| A-T3 | exec-haiku-high | exec |
| A-T4 | exec-haiku-med | exec |
| A-T5 | exec-haiku-high | exec |
| B-T1 | exec-haiku-med | exec |
| B-T2 | exec-haiku-high | exec |
| B-T3 | exec-haiku-high | exec |
| B-T4 | exec-haiku-med | exec |
| R1 | exec-haiku-med | exec |
| C1 | exec-haiku-med | exec |
| C2 | exec-haiku-high | exec |
| C3 | exec-haiku-med | exec |
| R2 | exec-haiku-med | exec |
| R3 | exec-haiku-low | exec |
| A-T3 | verify-sonnet-med | verify |
| A-T5 | verify-sonnet-med | verify |
| B-T1 | verify-sonnet-med | verify |
| B-T2 | verify-sonnet-med | verify |
| B-T3 | verify-sonnet-med | verify |
| B-T4 | verify-sonnet-med | verify |
| C1 | verify-sonnet-med | verify |
| C2 | verify-sonnet-med | verify |
| C3 | verify-sonnet-med | verify |

None excluded. The main session is not in the table.
