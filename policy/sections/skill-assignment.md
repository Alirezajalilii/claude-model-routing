## Skill Assignment
- Every delegation message to every agent includes a Skills line. "Skills: none" is valid and is the right answer for many tasks. Name each skill by the absolute path of its SKILL.md (the inventory's Path column), comma-separated.
- Who assigns: the main session assigns skills for scouts, planners, and fast-lane executors; the planner assigns skills for executors and verifiers, per task, in the plan file.
- The main session passes the skills the user names as must-follow to the planner with the user's decisions; the planner puts them on every executor and verifier Skills line they apply to, and the main session does the same for scouts and fast-lane executors.
- What to assign: the general skills the user or the project rules name as must-follow, plus the skills for the task's language, framework and specific work (its testing, review or output-format skill). Do not assign a skill merely because it is related to the topic.
- The verifier of a task always receives the same skills as that task's executor, plus any review or testing skill that applies. A verifier must judge against the same conventions the executor was told to follow.
- Limits: at most {{skill_cap_haiku}} skills for any Haiku agent, because loaded skills consume context and Haiku bills about five times more once a prompt exceeds 100K tokens; at most {{skill_cap_other}} skills for any other agent.
- Precedence when instructions conflict: this policy, then the project's claude.md, then the plan, then skills.
- An agent may read at most one unlisted SKILL.md, only when clearly necessary, and must report it. Repeated unlisted loads for the same task type mean the planner's assignment rules need updating.
