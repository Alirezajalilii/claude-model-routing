## Haiku context discipline
- Haiku bills about five times more for any request whose prompt exceeds 100K tokens.
- Keep Haiku tasks narrow: exact paths and line ranges, at most {{skill_cap_haiku}} skills, and an instruction not to read beyond them.
- A task that genuinely needs broad context or many skills is a Sonnet task.
- Measured baseline (Claude Code 2.1.306, 2026-10-24): a tier agent's first turn is about 36K prompt tokens outside a repository. A project's CLAUDE.md and its imports add their full size on top, so inside a repository with a heavy CLAUDE.md a Haiku agent can have only about 30K tokens of headroom before the 100K line.
