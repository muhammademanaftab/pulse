# Weekly Note Style

The weekly note is your record of what a week was about. Six months from now,
scrolling through `Pulse/Weekly/` should read like a log written by a person who
paid attention, not a machine.

## Voice

- Plain English. Write like a sharp engineer telling a colleague about the week.
- Active verbs. "Shipped the preview button" not "the preview button was shipped".
- No AI tone. Avoid: leverage, robust, seamless, streamline, empower, journey,
  unlock, delve, navigate, landscape, paradigm.
- No em dashes anywhere. Use commas, periods, colons, parentheses.
- Concrete numbers over vague ones. "59 job applications" not "many".

## Length

The whole note fits on one screen, roughly 150 to 350 words. If a section has
nothing real to say, say so in one line and move on. Do not pad.

## Linking

The weekly note is part of the Obsidian graph. Never hand-type a `[[wikilink]]`.

- Project names in "What you worked on": use the `rendered` field from
  `synth.py buckets`. It is already `[[Project]]` when a project note exists and
  `**Project**` when it does not, so the graph never gets a dead link.
- The "Sources" line links every daily note read this week, full path with a
  short alias: `[[Pulse/Daily/2026-06/2026-06-08|Jun 8]]`. Full paths are
  required because the same file name lives in several month folders.
- The note ends with `---` then `Part of [[<Weekly hub> <YYYY-MM>|<Month YYYY>]]`.
  The `week-links` command creates and maintains that hub.

## Structure

Frontmatter, a headline, then four sections and the footer, in this order:

```
# Week of <Mon D> to <Mon D>, YYYY
<one-sentence headline>

## What you worked on
One bullet per project. Each bullet: project (N days): one-line summary.

## What I skipped (and why)
Projects that showed up but did not earn a full line, one each with the reason
(one quiet mention, no real outcome, pure plumbing). "Nothing skipped." if empty.

## One number to remember
A single concrete metric from the week, one short sentence.

## Sources
One line linking every daily note read this week, then the footer.
```

## Headline

One sentence at the top. It should answer "what was this week about?" in a way
you could repeat to a friend.

Good:
- "Made the app faster and fixed the alerts that were getting dropped."
- "Quiet week, mostly cleanup and one bug fix."

Bad:
- "This week involved various activities across multiple projects." (vague)
- "A productive week with significant progress." (AI tone)

## Quiet weeks

If a week genuinely has little in it, still write the note. Headline: "Quiet
week." A short "What you worked on" is fine. The continuity is the point.

## Anti-patterns

- Do not quote daily-note bullets word for word. Rewrite them.
- Do not summarize the structure of the daily notes. The reader wants the work.
- Do not write "this week, you" filler or address a third person. Write plainly.
- Do not add a "next week" section. The note observes, it does not plan.
