# Security

## Supported versions

Only the latest release receives fixes.

## Reporting a vulnerability

Use GitHub private vulnerability reporting: open the repository's Security tab and choose "Report a vulnerability". Please do not open a public issue for security problems.

## What the plugin does on your machine

- Its hooks run local Python scripts at session start, before Agent tool calls and at session end.
- The scripts read Claude Code transcripts on your machine only to build usage and audit reports. They make no network requests.
- The session-end audit is written to the plugin data directory under `~/.claude/plugins/data/`.
- Nothing is written into the installed plugin directory.
