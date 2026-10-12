# Synth

Builds last week's weekly note from your daily notes and pushes it to your notes
repo, once a week, with your machine off. Create it per [README.md](README.md)
(Name, Model, repos, the `pulse` environment, permissions). Trigger: weekly, early
in the week (e.g. Monday morning) in `PULSE_TZ`, so the just-finished week is complete.

The synth reads your daily notes, so it needs the notes repo. It does not touch
Convex, so `CONVEX_URL` and `CONVEX_TOKEN` are not required for this routine.

Instructions (paste into the routine):

```
If the pulse repo is not already checked out, clone the pinned release: git clone --branch v0.2.0 --depth 1 https://github.com/muhammademanaftab/pulse.git. Read pulse/skills/synth/SKILL.md and follow every step exactly, for the most recently completed week in $PULSE_TZ. Read the daily notes from the notes repo at $NOTES_REPO and write the weekly note back into it. Do not push if any gate or the reviewer subagent fails. After the push is verified, report the weekly note path and commit SHA.
```
