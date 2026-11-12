# Deep dive: model routing on a 530,000-line production monorepo

[Part of the cross-project study.](case-study.md)

Over about eight days, one developer directing Claude Code used mr routing to add 385,920 lines of production code and tests to a production TypeScript monorepo, in 5 active days. The run's 278 subagents plus its main session cost $2,105.04 at Anthropic API list prices. The same tokens on Opus for every agent would have cost $3,532.96, which is 40% less under routing, or 1.7x the work for the same spend. Against an all-Sonnet run the routed run cost 19% more, and the Opus verifiers account for about 88% of that difference. Reviewers sent work back 79 times before merge.

## Headline numbers

| Key | Value |
| --- | --- |
| routed_usd | 2,105.04 |
| all_sonnet_usd | 1,766.48 |
| all_opus_usd | 3,532.96 |
| saving_vs_opus_percent | 40 |
| work_per_limit_ratio | 1.7 |
| extra_vs_sonnet_percent | 19 |
| subagents | 278 |
| executor_token_share_percent | 80 |
| haiku_exec_percent_of_sonnet | 6 |
| lines_added | 420,377 |
| production_lines_added | 124,812 |
| test_lines_added | 261,108 |
| code_and_test_lines_added | 385,920 |
| commits | 221 |
| active_days | 5 |
| test_calls_before | 811 |
| test_calls_after | 8,025 |
| lines_at_head | 530,977 |
| verdicts | 179 |
| sent_back_verdicts | 79 |
| first_verdict_pass_groups | 45 |
| task_groups | 116 |

Cost values are USD. Percentages are rounded half up, the ratio to one decimal. `haiku_exec_percent_of_sonnet` comes from this plugin's own repository (see [docs/cost.md](cost.md)), not from the monorepo. `code_and_test_lines_added` is production plus test lines (124,812 + 261,108); `lines_added` also counts documentation, configuration and tooling.

## The project

The project is a production TypeScript monorepo: 10 apps and 12 packages. At the snapshot it held 2,834 files and 530,977 lines, excluding generated files, lockfiles, vendored code and snapshots. One developer directed Claude Code. The routed work ran from 2026-11-05 to 2026-11-12, about 8 days, with commits on 5 of them. The history has one author identity and no reverts. Nothing else about the project is published here.

## How the work was routed

The main session wrote the specs: first on Opus, then on Sonnet 5.5 at high effort from 2026-11-05 21:43 UTC. Executors were mostly Sonnet at high and xhigh effort. Risky tasks went to Opus verifiers, and one Opus planner ran once.

| Tier | Agents | Role |
| --- | --- | --- |
| exec-sonnet-xhigh | 59 | executor |
| exec-sonnet-high | 67 | executor |
| exec-sonnet-med | 26 | executor |
| exec-haiku-high | 2 | executor |
| exec-haiku-med | 3 | executor |
| verify-opus-high | 89 | verifier |
| verify-sonnet-high | 30 | verifier |
| plan-opus-high | 1 | planner |
| scout-sonnet-high | 1 | scout |

That is 157 executors, 119 verifiers, 1 planner and 1 scout. Executors used 80% of all subagent tokens (7,496,188,746 of 9,324,000,943).

## Cost

I priced the committed dataset with `python3 -B bin/mr-cost docs/case-study/2026-11-production-run.json`. The main session counts as one agent in the Agents column.

| Group | Agents | At the models that ran | All Sonnet 5.5 | All Opus 5.5 |
| --- | --- | --- | --- | --- |
| scout | 1 | $2.88 | $2.88 | $5.75 |
| plan | 1 | $2.40 | $1.20 | $2.40 |
| exec | 157 | $1,230.49 | $1,236.80 | $2,473.60 |
| verify | 119 | $654.55 | $355.80 | $711.61 |
| main | 1 | $214.73 | $169.80 | $339.61 |
| total | 279 | $2,105.04 | $1,766.48 | $3,532.96 |

Against all-Opus, the routed run cost 40% less. Against all-Sonnet it cost 19% more. The cause is the Opus verifier tier: its 89 agents cost $597.50 at Opus prices and the same tokens would cost $298.75 at Sonnet prices. That $298.75 premium is the price of Opus review on the risky tasks, and it makes up about 88% of the $338.56 gap between routed and all-Sonnet. The all-Sonnet run is cheaper in dollars; what the extra spend bought is review by a stronger model, and the next sections show what review sent back.

## What the same usage limit covers

The routed run cost 1/1.7 of the all-Opus run for the same tokens, so the same usage limit covers about 1.7x the work, if two assumptions hold. First, the same work would use the same token counts on another model, which is not guaranteed. Second, your plan meters usage in proportion to API list price, which Anthropic does not publish. Cache reads are 98% of the tokens, so a meter that weights them differently moves the ratio.

## Output

Counts below are from git history, excluding generated files, lockfiles, vendored code and snapshots, for the 221 commits made under mr routing.

| Category | Lines added |
| --- | --- |
| Production code | 124,812 |
| Tests | 261,108 |
| Documentation, plans and specs | 15,780 |
| Configuration and ops | 13,581 |
| Tooling scripts | 5,096 |
| Total | 420,377 |

TypeScript test calls grew from 811 at the last commit before routing to 8,025 at the snapshot (counted as `it(` and `test(` call lines).

Counting added plus deleted lines in the same categories, the earlier setup produced 60,138 lines per active day (3 days) and routing produced 86,101 (5 days). The comparison has a caveat: the earlier setup used an external non-Claude model without per-task verification, so this compares two setups, not a controlled experiment. The shared day 2026-11-05 counts in both.

## Review and quality

Verifiers wrote 179 verdict files: 98 PASS, 70 FIX, 9 REPLAN and 2 that were not final verdicts. Reviewers sent work back 79 times (70 FIX plus 9 REPLAN), counting re-verification rounds. Grouped by task, the first verdict was PASS in 45 of 116 task groups.

The project owner classified the defects that verifiers found after the gate had passed: 25 touched security, money, data or authorization, and 50 were wrong behavior, a broken gate or a test that did not test. This is the owner's classification. I did not re-derive it.

Not measured: how many defects reached the merge. The data shows what was caught before merge, not what was missed.

## What did not go well

- Haiku executors: 3 of 5 ended BLOCKED, and 2 of the 3 had compacted their context first. Five agents is a small sample.
- Xhigh executors: on feature tasks in one phase, the first-pass gate passed 6 of 26 times, and the owner found their first-verdict defect rate no lower than at high effort.
- Usage limit: the weekly limit error appeared on 2026-11-07. Five subagent transcripts show it, and each kept working and ended with a report. Some verifications stayed open afterwards.
- Opus verifiers carried a $298.75 premium over the same tokens at Sonnet prices.
- Main-session prompts: the largest single prompt was 966,778 tokens.

## Method

Subagent tokens come from session transcripts read with `mr-usage`. Verdict counts come from the verdict files the verifiers wrote, and code counts come from git history. The snapshot was taken on 2026-11-12 at 15:52 UTC while the run was still live, so later totals differ slightly.

The dataset holds 11 aggregated rows: nine subagent tiers and the main session split by model. The main session rows cover the routed period only, from 2026-11-05 10:40 UTC. Excluded: the main session before the switch, all phase-verification sessions (their tokens are not split per session), and the earlier non-Claude worker, which left no transcripts. The total therefore understates what the project spent.

Prices are those in [docs/cost.md](cost.md), with 5-minute cache writes. The aggregated `exec-haiku-med` row prices all its tokens at the up-to-100K-token Haiku rate, so the routed total is about $0.67 below the per-agent total of $2,105.71, where at least one prompt passed 100K tokens. The headline percentages do not change. Sonnet and Opus prices are flat, so their rows aggregate exactly.

To reproduce the cost table, run `python3 -B bin/mr-cost docs/case-study/2026-11-production-run.json`. For the 1-hour cache write variant, add `--cache-ttl 1h`.
