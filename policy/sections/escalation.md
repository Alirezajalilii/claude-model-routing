## Escalation caps
Per task, allow at most: {{max_executor_escalations}} executor-tier escalations; one replan at each planner tier; two planner tiers in total.
When the caps are exhausted, stop work on that task and report to the human with the full log: plan, verdicts, skills used, and defect history. Continue with other tasks that do not depend on it.
