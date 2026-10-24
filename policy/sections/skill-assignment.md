## Skill Assignment
- Every delegation message to every agent includes a Skills line. "Skills: none" is valid and is the right answer for many tasks.
- Who assigns: the main session assigns skills for scouts, planners, and fast-lane executors; the planner assigns skills for executors and verifiers, per task, in the plan file.
- What to assign: only skills that change how this specific task must be done. Examples: the project's framework or style conventions for the files being touched; the skill for a required output format (document, spreadsheet, slide deck); a testing or review skill for verifiers. Do not assign a skill merely because it is related to the topic.
- The verifier of a task always receives the same skills as that task's executor, plus any review or testing skill that applies. A verifier must judge against the same conventions the executor was told to follow.
- Limits: at most {{skill_cap_haiku}} skills for any Haiku agent, because loaded skills consume context and Haiku bills about five times more once a prompt exceeds 100K tokens; at most {{skill_cap_other}} skills for any other agent.
- Precedence when instructions conflict: this policy, then the project's claude.md, then the plan, then skills.
- An agent may load at most one unlisted skill, only when clearly necessary, and must report it. Repeated unlisted loads for the same task type mean the planner's assignment rules need updating.
