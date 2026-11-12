# mr in practice: 18 projects, 1,785 agents

mr is a Claude Code plugin that gives each step of a coding session to a different model: Haiku scouts the code and builds the well-specified parts, Sonnet takes the harder code, and Opus plans and reviews. This is a study of how it ran across 18 projects between 2026-10-27 and 2026-11-12: 42 sessions and 1,785 agents. In the 24 sessions where Haiku did both the scouting and most of the building, subagent spend was 37% below an all-Sonnet run. Across all 42 sessions, including those where I kept executors on Sonnet, it was 5% below. Every figure below is recomputed from the data files in `docs/case-study/`.

## Headline numbers

| Key | Value |
| --- | --- |
| projects | 18 |
| transcript_projects | 11 |
| repos_with_logs | 16 |
| sessions | 42 |
| tier_agents | 1,785 |
| first_day | 2026-10-27 |
| last_day | 2026-11-12 |
| haiku_agents | 730 |
| haiku_scouts | 139 |
| scouts | 237 |
| haiku_scout_token_share_percent | 24 |
| haiku_executors | 591 |
| executors | 958 |
| opus_verifiers | 236 |
| opus_planners | 57 |
| all_routed_usd | 3,272.02 |
| all_sonnet_usd | 3,454.92 |
| all_opus_usd | 6,909.83 |
| all_saving_vs_sonnet_percent | 5 |
| all_saving_vs_opus_percent | 53 |
| haiku_heavy_sessions | 24 |
| haiku_heavy_agents | 1,055 |
| haiku_heavy_routed_usd | 835.47 |
| haiku_heavy_sonnet_usd | 1,329.17 |
| haiku_heavy_opus_usd | 2,658.34 |
| haiku_heavy_saving_vs_sonnet_percent | 37 |
| haiku_heavy_saving_vs_opus_percent | 69 |
| haiku_heavy_work_per_limit_vs_sonnet | 1.6 |
| haiku_heavy_with_main_saving_vs_sonnet_percent | 14 |
| haiku_scout_saving_vs_sonnet_percent | 92 |
| haiku_exec_saving_vs_sonnet_percent | 92 |
| repo_run_routed_usd | 11.27 |
| repo_run_sonnet_usd | 29.73 |
| repo_run_saving_vs_sonnet_percent | 62 |
| agent_median_peak | 89,877 |
| main_median_peak | 374,470 |
| context_ratio | 4.2 |
| compacted_sessions | 11 |

Cost values are USD at Anthropic API list prices. Percentages are rounded half up, ratios to one decimal. Spend figures count subagents only, except `haiku_heavy_with_main_saving_vs_sonnet_percent`, which adds the main sessions of the same sessions. `repo_run_*` come from this repository's own run in [docs/cost.md](cost.md).

## Where it ran

18 projects, 42 sessions that used mr, 2026-10-27 to 2026-11-12. Labels replace names: `P` labels are projects with session transcripts (11 of them), `T` labels are test runs of the plugin, and `L` labels are repositories that kept a routing log but left no transcripts. The 18 projects are the 20 labels minus the 2 test runs. This plugin's own repository is one of them. A multi-repo folder is a parent working folder that held several repositories.

| Label | Kind | Sessions | Agents |
| --- | --- | --- | --- |
| P01 | repo | 9 | 176 |
| P02 | multi-repo folder | 8 | 155 |
| P03 | multi-repo folder | 6 | 174 |
| P04 | repo | 5 | 163 |
| P05 | repo | 2 | 183 |
| P06 | repo | 2 | 22 |
| P07 | repo | 2 | 365 |
| P08 | repo | 1 | 281 |
| P09 | repo | 1 | 105 |
| P10 | repo | 1 | 32 |
| P11 | repo | 1 | 111 |
| T01 | test run | 2 | 16 |
| T02 | test run | 2 | 2 |
| L01 | log-only repo | 0 | 0 |
| L02 | log-only repo | 0 | 0 |
| L03 | log-only repo | 0 | 0 |
| L04 | log-only repo | 0 | 0 |
| L05 | log-only repo | 0 | 0 |
| L06 | log-only repo | 0 | 0 |
| L07 | log-only repo | 0 | 0 |

Sessions counts the sessions that used mr; agents counts the mr tier agents in them. The work across all projects spanned Kotlin, TypeScript, Rust, Python, Swift, C#, SQL. I publish no per-project stack, because a stack can point to a project.

## Which model did what

mr has four agent roles. Scouts gather evidence: they read code and docs and report back. Planners write the task plan. Executors write the code. Verifiers review a finished task before it merges. Each role has tiers on one or more of Haiku, Sonnet and Opus, and each tier fits a different kind of work. These are the agents that ran, by the model of their tier:

| Role | Agents | Haiku | Sonnet | Opus |
| --- | --- | --- | --- | --- |
| Scout | 237 | 139 | 98 | 0 |
| Plan | 66 | 0 | 9 | 57 |
| Exec | 958 | 591 | 367 | 0 |
| Verify | 524 | 0 | 288 | 236 |
| Total | 1,785 | 730 | 762 | 293 |

Scouting goes to Haiku by default, so reading code and docs stops costing Sonnet or Opus rates: 139 of 237 scouts ran on Haiku. By tokens the share is smaller. Haiku scouts carried 24% of scout tokens, and Haiku executors carried 14% of executor tokens. The long reads and the big builds went to Sonnet more often, so I do not claim that Haiku did most of the reading. What the counts show is that Haiku took 730 of 1,785 agents.

Each role runs where it does for a reason. Haiku suits evidence gathering and well-specified code, where the task says what to do and a test says whether it worked. Sonnet suits harder code and mid-risk review. Opus suits planning and high-risk review, where a wrong call costs more than the tokens.

That is the case against both single-model setups. A Sonnet-only session gives up top-tier planning and review. An Opus-only session spends its most expensive model on file edits and routine reads. mr puts each model where it is strongest: 57 Opus planners and 236 Opus verifiers on the steps that decide whether the work is right, against 591 Haiku executors on code a plan had already specified. This is a design argument. The data shows where the work went; it does not measure the quality of the output.

## Cost

I priced the rows with `mr-cost`: the same tokens at list prices on the models that ran, on Sonnet 5.5 and on Opus 5.5, with 5-minute cache writes. A run on another model would use a different number of tokens, so these are estimates, not a comparison of two runs. Across all 42 sessions, including those where executors stayed on Sonnet, subagent spend was 5% below all-Sonnet and 53% below all-Opus.

| Scope | Agents | Routed | All Sonnet | All Opus | Saving vs Sonnet | Saving vs Opus |
| --- | --- | --- | --- | --- | --- | --- |
| All sessions | 1,785 | $3,272.02 | $3,454.92 | $6,909.83 | 5% | 53% |
| Haiku-heavy sessions | 1,055 | $835.47 | $1,329.17 | $2,658.34 | 37% | 69% |
| This repository's run | 34 | $11.27 | $29.73 | $59.45 | 62% | 81% |

Rows one and two count subagent spend only. Row three is the plugin's own 2026-11-11 run with Haiku scouts and Haiku executors, priced in [docs/cost.md](cost.md).

**The Haiku-heavy condition.** I call a session Haiku-heavy when more than half of its executors ran on Haiku and, if it had scouts, more than half of its scouts did too: 24 of 42 sessions, 1,055 agents. There, with scouting and building both on Haiku, subagent spend was 37% below all-Sonnet and 69% below all-Opus. By role, the same tokens cost 92% less on Haiku scouts than on Sonnet, and 92% less on Haiku executors.

**Sonnet-heavy sessions cost more.** In 7 sessions more than half of the executors ran on Sonnet, and subagent spend there was about 16% above all-Sonnet. Two things drive that. Those sessions used Opus for review, which costs more than the same review on Sonnet, and the executors stayed on Sonnet because I ordered it. Across all 42 sessions the saving shrinks to 5% for that reason, even though the Haiku-heavy sessions save 37%.

**The main session.** The main session's model is the user's choice and runs with or without mr, so the tables leave it out. Adding it changes the picture: with the main sessions, Haiku-heavy sessions came out 14% below all-Sonnet, and all 42 sessions together came out about 6% above it. In 20 of 42 sessions the main session used Opus for at least part of the work. mr does not change that choice.

The large run's figures here (281 agents, $1,932.68) differ from the deep dive's (278 agents, $1,890.98) because they come from different snapshots that handle `<synthetic>` rows differently. Agent, cost and context figures come from the 11 projects with transcripts, plus 18 agents in two test runs. The other 7 projects contribute routing logs only.

## What the same usage limit covers

In Haiku-heavy sessions the same tokens cost $835.47 as routed and $1,329.17 on Sonnet, which is 1.6x the subagent work per usage limit compared with all-Sonnet. That holds under two assumptions. First, the same work would use the same token counts on another model, which is not guaranteed. Second, your plan meters usage in proportion to API list price. Anthropic does not publish how it meters, so read 1.6x as a list-price ratio, not a promise about your plan.

## Separate agents, smaller contexts

One session that scouts, plans and builds in a single context carries the leftovers of every stage into the next. mr gives each stage its own agent, so a scout reads a repository without a half-built plan in its context, and an executor starts from the task, not from the reading that preceded it. This is the design reason for splitting the work. I did not measure output quality, so I make no claim about it.

What I did measure is how much context each side carried. The median agent peaked at 89,877 prompt tokens. The median main session peaked at 374,470, which is 4.2x larger. 11 of 42 sessions had at least one context compaction.

The limits matter. About one agent in ten peaked above roughly 300,000 tokens, and 70 of the 730 Haiku agents passed 100,000. Planners are the exception to the small-context picture: their median peak was 374,604 tokens, about the same as the main session's.

## Review and quality

The routing logs record one row per task or batch, so the counts below are approximate. A row can cover several tasks, and I parsed the tables with a script. 14 repos had a parsed task table, and 16 had a routing log; the other two kept an aggregate only or a different format. Of 497 rows, 352 (71%) had no FIX, no REPLAN and no escalation. 101 rows had a FIX, 45 a REPLAN and 19 an escalation to a stronger tier. Treat these as orders of magnitude.

For verifier verdicts I have one project where I counted the verdict files: the large run in [the deep dive](case-study-monorepo.md). Its verifiers sent work back 79 times, and the first verdict was PASS in 45 of 116 task groups.

One defect is known to have escaped. In this plugin's own repository, a stall-watch defect reached a release and was found by a release smoke test, not by a gate or a verifier ([docs/cost.md](cost.md)). The logs show what was caught before merge. They do not show what slipped through, and I have no quality figure beyond these counts.

## What did not go well

- Non-tier subagents ran inside mr sessions: 53 of them, outside the tier totals above, costing $88.24 as run. The dispatch guard denies agent types outside the tiers unless they are allowlisted.
- The main session used Opus in 20 of 42 sessions, so some of the spend sits outside what mr controls.
- In two projects I ordered no Haiku executors partway through the run. Those sessions are in the Sonnet-heavy group.
- 67 mr dispatches in three sessions of one project left no subagent transcript, so they are unpriced. The totals understate that work.
- Two counts of long-prompt Haiku agents disagreed, 70 and 103. They agree once the 33 non-tier subagents are included (70 + 33 = 103). `mr-cost` now counts agents, not rows, and prints 103.
- In the large Sonnet-heavy run, 3 of 5 Haiku executors ended BLOCKED, and 2 of the 3 had compacted their context first. Five agents is a small sample.

## The large production run

One of the 18 projects is a large production run that I wrote up separately. Executors there were mostly Sonnet and Opus reviewed the risky tasks, so it sits in the Sonnet-heavy group: routed, it cost 40% less than all-Opus and 19% more than all-Sonnet. Its [deep dive](case-study-monorepo.md) has the cost table, the output, and what review sent back.

## Method

Data files, all in `docs/case-study/`: `cross-project-usage.json` (aggregated rows by project, session, agent type and model, with token counts and peak prompt size), `context-peaks.json` (peak prompt per agent and per main session), `projects.json` (reach, sessions and segment counts per label) and `routing-logs.json` (parsed routing-log counts). Labels `P01` to `P11`, `T01`, `T02` and `L01` to `L07` replace project names, and sessions are numbered `S01` to `S42`. The files hold no paths, transcript text or identifiers.

To reproduce the cost lines, run `python3 -B bin/mr-cost docs/case-study/cross-project-usage.json`. Its scout, plan, exec and verify lines add up to the all-sessions row. The main and other lines are the main sessions and the non-tier subagents. The report prints 103 Haiku agents priced at the higher rate for prompts over 100,000 tokens: 70 tier agents and 33 non-tier subagents. For this repository's run, use `python3 -B bin/mr-cost docs/cost/2026-11-11-run.json`. Add `--cache-ttl 1h` for 1-hour cache writes.

Segments are per session, from the mr tier agents in it. A: more than half of the executors on Haiku and, if the session had scouts, more than half of them on Haiku too (24 sessions). B: more than half of the executors on Sonnet (7 sessions). C: other sessions with executors (3). The remaining 8 sessions had no executors. `tests/test_cross_project_study.py` recomputes every Headline value from the data files, including the segment rule.

Rows come from `mr-usage` over each session's transcripts. Rows whose first model was a `<synthetic>` placeholder use the real model listed after it. Main-session usage is the last usage entry per message. Prices are those in [docs/cost.md](cost.md).
