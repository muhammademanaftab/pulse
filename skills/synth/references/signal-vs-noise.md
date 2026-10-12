# Signal vs Noise

Read this before writing any line of the weekly note.

A weekly note exists to capture what got **built, shipped, decided, or learned**
that week. Not how the work was committed, and not a replay of every daily note.

## The rule

If a line only describes mechanics, drop it. If a line describes a capability, a
decision, a real artifact, or a problem solved, keep it.

## Reading the daily bullets

Daily notes use typed bullets (see `skills/digest/references/note-structure.md`):

- `Outcome:` is the best one-line summary of that day's work on a project.
- `Decided:`, `Bug:`, `Rule:` and `Learned:` are the decisions, fixes and lessons.
- `Open:` bullets were unfinished that day. `open_loops` in the buckets JSON
  holds each item's latest state that week: never report it as still open if it
  is `- [x]` there, or as shipped if it is `- [ ]`.
- `Refs:` is plumbing: links, not results.

Older notes have plain bullets; read them as results.

## Do not write the plumbing

These, on their own, are not worth a line in the weekly note:

- Branch or PR opened, merged, closed, renamed
- Commit, push, rebase, fetch, stash
- File or folder renamed, moved, gitignored
- A ticket filed or re-titled (unless the ticket is the artifact)
- "Updated the README to match the new path"
- "Fixed a typo"

Plumbing belongs in `git log`, not the weekly note.

## Do write the substance

| Type | Example |
|---|---|
| Capability shipped | "Cut the home page load from 4 seconds to about 1." |
| Decision made | "Chose to keep people signed in for 30 days instead of asking every visit." |
| Problem solved | "Found the bug that was dropping some alerts and fixed the ordering that caused it." |
| Tool or API adopted | "Started using the new image API for the render step." |
| Real artifact produced | "Shipped the preview-before-publish button end to end." |

## How much per project per week

One line per project in "What you worked on". If the week had a lot for one
project, pick the single most important thread and say it in one line. Quiet
weeks for a project are fine. Do not pad.

## Rewrite, do not quote

Do not copy daily-note bullets word for word. The daily notes are the source;
the weekly note is a shorter, higher-level read. Write it in your own plain
words, the way you would tell a colleague what your week was about.
