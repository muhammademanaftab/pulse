---
name: rules
description: Review Pulse Rule entries and propose additions to the current project's CLAUDE.md.
disable-model-invocation: true
---

# Turn Pulse rules into project instructions

Only run when explicitly invoked by the user.

1. Run `python3 skills/rules/rules.py` and inspect its JSON output. Stop on errors.
2. Review dated Rule entries for the mapped project. Ignore Learned entries.
3. Compare rules against the existing CLAUDE.md. Exclude rules already covered.
4. Merge duplicates and rewrite remaining rules as short, clear instructions.
5. Show the exact proposed additions and ask for explicit approval.
6. Never create or modify a file before approval.
7. After approval, append approved bullets under `## Rules from Pulse`.
8. If the section exists, append only new bullets. Preserve all other file contents exactly.
9. If there are no new rules, make no changes and report that.

Never run unattended or guess an unmapped project.
