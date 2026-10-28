## Skills
- Your delegation has a Skills line: `Skills: none`, or a comma-separated list of absolute paths to SKILL.md files.
- Right after the project rules, read each listed SKILL.md with the Read tool and follow it. Paths inside a skill are relative to its SKILL.md directory; read its other files only when the SKILL.md tells you to and your task needs them.
- If a listed SKILL.md cannot be read, say so in your output and continue, unless the task cannot be done correctly without it; then stop and reply with the BLOCKED status line of your role's Output file section.
- Read no other skill, except at most one unlisted SKILL.md whose path you already know, and only when it is clearly necessary; name it and the reason in your output.
- If a skill's guidance conflicts with the plan or the delegation, do not resolve it silently: record the conflict in your output (planners: in the plan's Risks section).
- Begin your output with a "Skills loaded" line listing every SKILL.md you read, or "none".
