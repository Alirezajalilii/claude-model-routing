## Skills inventory
- At the start of every full-lane run, the main session builds a skills inventory: every skill available in this session (user, project, and plugin, as listed in the session's skills listing), each with its name, one-line description, and scope. Exclude skills that set `disable-model-invocation`, because agents cannot load them.
- The main session passes this inventory to the planner. It does not pass the full inventory to scouts, executors, or verifiers; they receive only their Skills line.
- `model-routing-skills` prints the user, project and plugin skills it can find, without those that set `disable-model-invocation`, as a Markdown table; add any skill from the session's listing that it missed.
