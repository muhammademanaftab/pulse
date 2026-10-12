# Note structure

Read this before writing any daily note. It defines what a finished note looks
like and why. `digest.py lint` checks the parts marked (lint).

## The goal

A daily note is a record you (and anything built on the notes) come back to weeks
or months later with a question:

- "What did I do on X?" and "when did we ship Y?"
- "Why did we decide Z?"
- "How did we fix that bug last time?"
- "What was still open?"

Length is fine. A busy day gets a long note. What matters is that each kind of
information is easy to find: results, decisions, bugs and open items are never
mixed into one stream of bullets.

## Layout

```markdown
---
date: "2026-06-02"
tags: [pulse, daily]
source: claude-code
projects:
  - "[[Web App]]"
  - "Notifications"
---

# Tuesday, June 2, 2026

## Summary

<2 to 4 plain sentences: what the day was about and what changed. Name the projects.>

## Work log

### [[Web App]]

- Outcome: <one sentence a stranger could follow: what is different now>
- <result bullet>
- Decided: <the choice>. Why: <the reason>. Rejected: <the alternative, if there was one>.
- Bug: <what was seen>. Cause: <why>. Fix: <what changed, or "not fixed yet">.
- Rule: <a standing instruction that applies to future work>
- Learned: <a reusable fact or gotcha>
- Open: <something left open in this project>
- Refs: <PRs, commits, files, tickets, URLs, comma-separated>

### **Notifications**

...

## Open loops

- [ ] <open item> (<Project>, since <Mon D>)
- [x] <item closed today> (<Project>, since <Mon D>, done <Mon D>)
```

Sections are exactly Summary, Work log, Open loops, in that order (lint).

**One bullet is one line** (lint). Never wrap a bullet onto an indented second
line: lint rejects it, and the weekly synth reads only the first line.

## Frontmatter

`projects:` lists every Work log block once, in block order, written exactly as
its heading shows it: `"[[Label]]"` for a linked heading, `"Label"` for a bold
one (lint). Copy the label from the `render-block` output; never invent a link.
This lets Obsidian list every day a project was worked on.

## Summary

Two to four sentences of plain prose, not bullets (lint: not empty). A reader
skimming a month of notes should get the shape of each day from this alone: the
main threads, what shipped, and anything big left hanging. Past tense. No file
paths.

## Work log blocks

One block per bucket in the digest JSON. The heading comes from
`digest.py render-block`; never type it by hand.

Inside a block, bullets go in this order. Skip any type that has nothing real in
it; never write an empty or "none" bullet inside a block.

1. **`- Outcome:`** (always, exactly one, first; lint). One sentence saying what is
   different at the end of the work compared with the start. Write it for someone
   who has never seen the project. It is not a list of steps.
2. **Result bullets** (no prefix). What was built, fixed, shipped, tested, written
   or researched. Lead with what it does, then the file or ID. State the status in
   plain words: `deployed`, `merged`, `open PR`, `local only`, `tested, not
   shipped`.
3. **`- Decided:`** One per real decision:
   `Decided: <choice>. Why: <reason>. Rejected: <alternative>.` The `Why:` is
   required (lint). Leave out `Rejected:` only if no alternative was discussed.
4. **`- Bug:`** One per real bug found:
   `Bug: <symptom as seen>. Cause: <root cause>. Fix: <what changed, with PR or file>.`
   `Cause:` and `Fix:` are required (lint). If unfixed, write `Fix: not fixed yet`
   and add an `Open:` bullet.
5. **`- Rule:`** A standing instruction that applies beyond today (repeated, or said
   as a rule: "never run a migration without a backup"). This is what future
   sessions need to remember.
6. **`- Learned:`** A reusable fact or gotcha that cost time to find out ("the CI
   cache key hashes the lockfile, so editing package.json alone does not refresh
   it"). Only if it would save time next time.
7. **`- Open:`** Something new left unfinished today, waiting on someone, or
   proposed without an answer. Say who or what it waits on. Each one is also an
   open `- [ ]` item in `## Open loops` with the same text (lint). Checkboxes
   live only in Open loops (lint), so each item is ticked in one place.
8. **`- Refs:`** (optional, last; lint). PR numbers, commit SHAs, ticket IDs, key
   file paths and URLs, comma-separated. Keeping them here keeps the result
   bullets readable.

`references/signals.md` explains how to spot Decided, Rule, Learned and Bug items
in the rows.

### Context on first mention

The first time a person, client, tool or internal name appears in a block, add a
few words saying who or what it is: "Sam (on-call engineer)", "Mailgun (email
sending service)". A reader months later will not remember.

### What to leave out

- How the conversation went: "the user pointed out...", "after 4 rounds of
  edits". Keep only the outcome. If a correction changed a result, record the
  corrected result.
- Plumbing on its own (see `bullet-quality.md`).
- Hook noise and routine boilerplate.

### When the day changed its mind

If a plan, number or choice changed during the day, write the final version.
Mention the earlier one only if the change itself matters later, as a `Decided:`
bullet that names what it replaced.

### When the status is unclear

If the rows do not show whether something was sent, merged or deployed, write
`status not confirmed in the session` rather than guessing. Never infer
"deployed" from "was waiting for approval".

### Rule vs one-off instruction

`Rule:` is for instructions that apply beyond the current task ("always run the
tests before opening a PR"). A one-off instruction for the task at hand ("don't
merge this until I approve") is not a rule; record its effect as a result or an
`Open:` item instead.

### Numbers

Write a number only if it appears in the rows (tool output or the assistant's
reply). Never work one out yourself, round one, or carry one over from another
day. If the number is not clearly stated, describe the result without it.

## Open loops

The day's to-do ledger. It carries forward from day to day so nothing is
forgotten. Only `- [ ]` and `- [x]` lines count; anything else fails lint.

1. Run `digest.py open-loops --note <note_path>` before writing the note. It
   prints JSON: `carry` (the previous note's open items, each with `text`,
   `project`, `since`, `age_days`), `legacy_next` (the previous note's `## Next`
   items when that note predates Open loops), and `closed_in_existing` (items
   already closed in this date's note, by hand or by an earlier run, before it is
   regenerated).
2. Every `carry` item appears again, with its text unchanged (lint):
   - still open: `- [ ] <text> (<Project>, since <original date>)`. If today moved
     it forward without closing it, add a short note inside the parentheses:
     `(Web App, since Jun 4; retried Jun 5, upload failed)`.
   - closed today (the Work log shows it happened):
     `- [x] <text> (<Project>, since <date>, done <Mon D>)`
   - no longer relevant (the Work log shows it was abandoned or replaced):
     `- [x] <text> (<Project>, since <date>, dropped <Mon D>: <reason>)`

   A closed item needs `done <Mon D>` or `dropped <Mon D>: <reason>` (lint). Only
   close or drop an item when today's work shows it. Without evidence it stays
   open. Carried items stay in Open loops only: do not repeat them as `Open:` in
   the Work log; put today's progress in the parentheses.
3. **Stale items age out.** A `carry` item with `age_days` of 7 or more and no
   related work today is dropped:
   `- [x] <text> (<Project>, since <date>, dropped <Mon D>: stale, no activity in 7 days)`.
   If it matters it will come up again.
4. **Closed stays closed.** Much of what gets done never shows up in a session.
   Ticking `- [x]` in the latest note's Open loops is enough: it is not carried
   again. Every item in `closed_in_existing` stays `- [x]` when this note is
   regenerated.
5. Add an open item for every `Open:` bullet in today's Work log.
6. For each still-relevant `legacy_next` item, add an open item
   `(<Project>, since <Mon D of that note>)`.
7. If nothing is open at all, write `- None.` (lint: never leave it empty).

Closed (`[x]`) items appear only on the day they close.

Only real follow-ups belong here: something a person still has to do or decide.
Short-lived states ("render in progress") are not open items; describe them in the
result bullet instead.

## Before and after

Before (one undifferentiated stream):

> - Looked into why nightly exports were missing rows. Turned out the job ran twice...
> - The user asked whether the cron or the queue was retrying. Checked the logs, both were...
> - Rule mentioned several times today: never run a migration on production without a backup...
> - Spent a while on the export file format, went back and forth between CSV and Parquet...

After:

> ### **Data Export**
>
> - Outcome: Nightly exports now contain every row once, and the file format is settled.
> - Exports run from one scheduler instead of two. Deployed.
> - Bug: some exports were missing rows. Cause: the cron and the queue both retried a failed run, and the second run overwrote the first. Fix: only the queue retries now (PR #12).
> - Decided: export as CSV. Why: every downstream tool reads it. Rejected: Parquet.
> - Rule: never run a migration on production without a backup.
> - Open: Backfill the 3 days of short exports. Waiting on Sam (on-call engineer) to approve.
> - Refs: PR #12, `scheduler.py`, `export_job.py`
