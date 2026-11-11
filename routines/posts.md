# Posts

Drafts a LinkedIn post and an X thread about last week from your weekly note and
pushes the drafts file to your notes repo, once a week, with your machine off.
Create it per [README.md](README.md) (Name, Model, repos, the `pulse` environment,
permissions). Trigger: weekly, after the synth routine has run (for example an
hour later on Monday morning) in `PULSE_TZ`.

It only writes drafts for you to review. It never posts anything and needs no
LinkedIn or X access. It does not touch Convex, so `CONVEX_URL` and `CONVEX_TOKEN`
are not required for this routine.

Instructions (paste into the routine):

```
If the pulse repo is not already checked out, clone the pinned release: git clone --branch v0.3.0 --depth 1 https://github.com/muhammademanaftab/pulse.git. Read pulse/skills/posts/SKILL.md and follow every step exactly, for the most recently completed week in $PULSE_TZ. Read the notes from the notes repo at $NOTES_REPO and write the drafts file back into it. Do not post anything anywhere. Do not push if any gate or the reviewer subagent fails. After the push is verified, report the drafts file path and commit SHA.
```
