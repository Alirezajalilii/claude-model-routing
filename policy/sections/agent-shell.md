## Long-running commands
- Run a command in the foreground when it can finish within the Bash tool's time limit; start it with `run_in_background` only when it cannot.
- Never wait with `sleep`: Bash refuses `sleep N` followed by other commands. To wait for a background command or a condition, use Monitor with an until-loop, for example `until <check>; do sleep 5; done`.
- Before your status line, stop every background shell you started with TaskStop, unless your task says to leave it running.
