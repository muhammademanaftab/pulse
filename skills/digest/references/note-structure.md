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
- [ ] <something left open in this project>
- Refs: <PRs, commits, files, tickets, URLs, comma-separated>

### **Notifications**

...

## Open loops

- [ ] <open item> (<Project>, since <Mon D>)
- [x] <item closed today> (<Project>, since <Mon D>, done <Mon D>)
```

Sections are exactly Summary, Work log, Open loops, in that order (lint).

## Frontmatter

`projects:` lists every Work log block label, one per line, in block order,
without duplicates (lint). Write `"[[Label]]"` (quoted) when the heading is a link
and `"Label"` when the heading is bold. This lets Obsidian list every day a project
was worked on.

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
   and add a `- [ ]` item.
5. **`- Rule:`** A standing instruction that applies beyond today (repeated, or said
   as a rule: "never guess an email address"). This is what future sessions need
   to remember.
6. **`- Learned:`** A reusable fact or gotcha that cost time to find out ("Safari
   drops the session cookie cross-site unless SameSite=None"). Only if it would
   save time next time.
7. **`- [ ]` open items.** Anything left unfinished, waiting on someone, or proposed
   without an answer. Say who or what it waits on. Every one also goes into
   `## Open loops` with the same text, followed by ` (<Project>, since <Mon D>)`
   (lint).
8. **`- Refs:`** (optional, last; lint). PR numbers, commit SHAs, ticket IDs, key
   file paths and URLs, comma-separated. Keeping them here keeps the result
   bullets readable.

`references/signals.md` explains how to spot Decided, Rule, Learned and Bug items
in the rows.

### Context on first mention

The first time a person, client, tool or internal name appears in a block, add a
few words saying who or what it is: "Dana (design lead)", "Mailcheck (email
verification service)". A reader months later will not remember.

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

`Rule:` is for instructions that apply beyond the current task ("always preview
the cost before generating"). A one-off instruction for the task at hand ("don't
merge this until I approve") is not a rule; record its effect as a result or an
open item instead.

### Numbers

Write a number only if it appears in the rows (tool output or the assistant's
reply). Never work one out yourself, round one, or carry one over from another
day. If the number is not clearly stated, describe the result without it.

## Open loops

The day's to-do ledger. It carries forward from day to day so nothing is
forgotten.

1. Run `digest.py open-loops --note <note_path>` before writing the section. It
   prints JSON: `carry` (the previous note's unchecked items, each with `text`,
   `project`, `since`, `age_days`), `legacy_next` (the previous note's `## Next`
   items when that note predates Open loops), and `ticked_in_existing` (items the
   user ticked in this date's note before it is regenerated).
2. Every `carry` item appears again, with its text before the `(Project, since
   ...)` tag unchanged (lint):
   - still open: `- [ ] <text> (<Project>, since <original date>)`. If today moved
     it forward without closing it, add a short note inside the parentheses:
     `(Web App, since Jun 4; retried Jun 5, upload failed)`.
   - closed today (the Work log shows it happened):
     `- [x] <text> (<Project>, since <date>, done <Mon D>)`
   - no longer relevant (the Work log shows it was abandoned or replaced):
     `- [x] <text> (<Project>, since <date>, dropped <Mon D>: <reason>)`

   Only close or drop an item when today's work shows it. Without evidence it
   stays open.
3. **Stale items age out.** A `carry` item with `age_days` of 7 or more and no
   related work today is dropped:
   `- [x] <text> (<Project>, since <date>, dropped <Mon D>: stale, no activity in 7 days)`.
   If it matters it will come up again.
4. **Ticked by hand stays ticked.** Much of what gets done never shows up in a
   session. Ticking `- [x]` in the latest note is enough: it is not carried again.
   Every item in `ticked_in_existing` stays `- [x]` when this note is regenerated.
5. Add every new `- [ ]` item from today's Work log blocks.
6. For each still-relevant `legacy_next` item, add an open item
   `(<Project>, since <that note's date>)`.
7. If nothing is open at all, write `- None.` (lint: never leave it empty).

Closed (`[x]`) items appear only on the day they close.

Only real follow-ups belong here: something a person still has to do or decide.
Short-lived states ("render in progress") are not open items; describe them in the
result bullet instead.

## Before and after

Before (one undifferentiated stream):

> - Looked into why a customer's reply would not show in the inbox view. Dana
>   replied inside a colleague's thread from the shared support address...
> - The user pointed out that Dana had cc'd the colleague. The first check said
>   "no cc" because the query didn't return the cc field...
> - Rule repeated across the day: never send to an address that wasn't verified...
> - Drafted, across 4 rounds of edits, a message to the account owner. Still
>   unresolved at the end of the day...

After:

> ### **Support Inbox**
>
> - Outcome: Replies now go out from the inbox the customer wrote to, with
>   everyone they copied, and the ranking redesign is waiting on a decision.
> - Replies now thread under the customer's latest message, from the inbox it
>   arrived in. Deployed.
> - Auto-drafted replies keep everyone the customer cc'd, like reply-all. Deployed.
> - Bug: a reply from Dana (customer contact) showed "No email for this step".
>   Cause: she answered inside a colleague's thread on the shared support inbox,
>   and the view only read her own inbox. Fix: thread picking in `threads.ts`
>   (PR #57).
> - Decided: once anyone at a company is emailed from one inbox, everyone there is
>   emailed from it too. Why: replies were landing in different inboxes for the
>   same company. Rejected: picking the inbox per person.
> - Rule: only send to addresses Mailcheck (email verification service) marks
>   "safe". Never guess an address.
> - [ ] Ranking: by person or by company? Waiting on the account owner. The
>   redesign is on PR #60, local only.
> - Refs: PR #50, #56, #57, #60, `threads.ts`, `send.ts`
