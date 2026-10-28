## Haiku context discipline
- Haiku bills about five times more for any request whose prompt exceeds 100K tokens.
- Keep Haiku tasks narrow: exact paths and line ranges, at most {{skill_cap_haiku}} skills, and an instruction not to read beyond them.
- A task that genuinely needs broad context or many skills is a Sonnet task.
- Tier agents start without the user's and the project's CLAUDE.md files (`omitClaudeMd`) and without a skill-loading tool, so their fixed context is the agent body, the tool definitions and the environment; the project rules files and SKILL.md files they read come on top. Haiku tier agents compact before the 100K line (`autoCompactWindow`), and the audit flags every Haiku request over {{haiku_prompt_flag_tokens}} prompt tokens. Where the project rules files are large, name only the rules a task needs on its Project rules line.
- A task expected to need more than about {{haiku_max_tool_calls}} tool calls is not a Haiku task.
