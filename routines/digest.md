# Digest

Builds yesterday's daily note and pushes it to your notes repo, nightly, with your
machine off. Create it per [README.md](README.md) (Name, Model, both repos, the `pulse`
environment, permissions). Trigger: daily, late evening in `PULSE_TZ`.

Instructions (paste into the routine):

```
Read pulse/skills/digest/SKILL.md and follow every step exactly, for yesterday in $PULSE_TZ. Write the note into the notes repo at $NOTES_REPO. Do not push if any gate or the reviewer subagent fails. After the push is verified, mark the digested rows processed. Report the note path and commit SHA.
```
