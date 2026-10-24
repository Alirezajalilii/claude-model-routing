## Full lane workflow
1. **Evidence.** The main session runs scouts with narrow questions, starting paths, and a Skills line (usually none; a project-conventions skill when scouts must recognize framework-specific patterns). Run scouts in parallel when the questions are independent. Use `scout-haiku-low` for locating, `scout-haiku-medium` for reading and summarizing (including read-only `gh`/API queries, CI logs and live endpoint checks), and `scout-sonnet-high` only when the root cause is unclear or spans modules.
   - Ask for plan-ready evidence: for every file the change will likely touch, the path, the line ranges and the exact excerpt of the relevant functions, types or config entries; the callers and tests involved; and the verification commands that exist. The planner builds on this without re-reading the files, so a scout question that only asks for counts or a summary is too thin.
   - Wait for every scout before dispatching the planner.
2. **Plan.** The main session chooses a planner tier and passes it: the task description, all scout evidence, the skills inventory, and a Skills line for the planner itself (for example, an architecture or domain skill that shapes the plan).
   - If the planner returns NEED_EVIDENCE, run the requested scouts, then resume the same planner instance with the results through SendMessage.
   - The planner treats the scout evidence as verified and has an evidence budget: at most {{planner_evidence_budget}} Read/Grep/Glob calls in total, each to fill a gap it names in the plan. A larger gap goes back as NEED_EVIDENCE, answered by cheap scouts, instead of the planner investigating on its own.
   - Allow at most {{max_evidence_rounds}} evidence rounds. After that, the planner must plan with what it has and list its assumptions explicitly.
3. **Execute.** Dispatch each task to the executor tier the plan assigns. Pass the plan file path, the task ID, and the task's executor Skills line exactly as written in the plan. Never pass a paraphrase of the task. Independent tasks run in parallel, each in its own worktree; dependent tasks run in order.
4. **Gate.** For every finished task, the main session runs these checks itself:
   - Red: if the task has Test Cases, check out commit one and run the new tests. They must fail. Tests that pass before the implementation exists are not testing the change.
   - Test integrity: commit two and any later commits must not modify files from commit one. The diff must add no skip, xfail, or only markers, and must remove no assertions.
   - Coverage: every Test Case in the plan has a corresponding test.
   - Scope: every changed file is in the task's file list or is one of its test files.
   - Green: the task's verification commands and the full test suite pass.
   - Report: the executor's claims match the diff and the command output.
5. **Verifier, only when triggered.** Dispatch the plan's verifier tier when any of these apply:
   - the plan marked the task Verify: yes (see Verification triggers);
   - a gate check other than Green failed (red, integrity, coverage, scope, or report mismatch); these failures need judgment, not a blind retry;
   - the task already went through a FIX round or an escalation;
   - calibration sampling selected the task.
   Pass the plan path, task ID, branch or worktree, the executor's report, the gate results, and the task's verifier Skills line exactly as written in the plan.
6. **Act on the result.**
   - Gate passed and no verifier was triggered, or the verifier returned PASS: the task is done.
   - Only the Green check failed (tests fail, everything else clean): resume the same executor instance through SendMessage with the failure output. This counts as a FIX round. No verifier is needed for it.
   - Verifier FIX: resume the same executor instance with the defect list. Then resume the same verifier instance to re-verify; it must re-run every command.
   - Allow at most {{max_fix_rounds_per_tier}} FIX rounds at one tier, counting both kinds. After that, escalate the executor one tier: launch a fresh executor with the plan path, the task ID, the Skills line, and the full defect history.
   - REPLAN: resume the same planner instance with the verifier's evidence, so it can revise that task in the plan file, including its skills if the problem was a skill conflict or a missing skill. The advisor may be consulted once more for a replan. After the revision, re-execute the task. If a second REPLAN occurs for the same task, move up one planner tier.
   - BLOCKED: fix the environment issue if it is clearly mechanical. Otherwise, treat it as a failure under the escalation caps.
7. **Final gate and integrate.**
   - Merge only when every task has passed its gate (and its verifier, if one ran) and the full test suite passes on the integrated branch. Then commit with a clear message and merge. Where a project forbids red-only commits on its main branch, fold the red commit into its green commit after the gate and before the merge.
   - Never force-push or rewrite shared history.
   - Resolve trivial merge conflicts directly. Route non-trivial conflicts as a new task to `exec-sonnet-high`, with verification.
   - Destructive database migrations, data deletion, and production deploys are outside auto-merge scope: prepare them fully, then report.
8. **Log** every delegation, as described under Logging.
