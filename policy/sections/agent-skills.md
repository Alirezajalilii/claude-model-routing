## Skills
- Your delegation has a Skills line: `Skills: none`, or a comma-separated list of absolute paths to SKILL.md files.
- Right after the project rules, load each listed skill in full: read its SKILL.md with the Read tool (no offset or limit), or call the Skill tool with the skill's name when that name is in your skill listing. Skills kept in a group folder are not in the listing; Read is the only way to load them. Paths inside a skill are relative to its SKILL.md directory; read its other files only when the SKILL.md tells you to and your task needs them.
- If a listed SKILL.md cannot be read, say so in your output and continue, unless the task cannot be done correctly without it; then stop and reply with the BLOCKED status line of your role's Output file section.
- Load no other skill, by Read or by the Skill tool, except at most one unlisted skill, and only when it is clearly necessary; name it and the reason in your output. The skill listing Claude Code attaches is not an assignment.
- If a skill's guidance conflicts with the plan or the delegation, do not resolve it silently: record the conflict in your output (planners: in the plan's Risks section).
- Begin your output with a "Skills loaded" line listing every skill you loaded (its SKILL.md path, or its name for a Skill tool call), or "none".
