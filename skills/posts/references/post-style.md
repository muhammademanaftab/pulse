# Post style

Read this before writing a draft. The drafts are for the user to review, edit and
post themselves. They should sound like a person telling peers what they built
this week, not like marketing.

## What a good post is

One real thing from the week, told plainly, that another builder would find
useful or interesting. Pick the single strongest thread from the weekly note:

- a problem and how it was actually solved (the cause is the interesting part)
- a decision and the reason behind it, including what was rejected
- something learned the hard way that would save someone else time
- a result with a real number

One thread per post. A list of everything done this week is a status report, not
a post. If the week has no thread worth posting, say so (see Quiet weeks).

## Truth rules

- Every claim must be in the weekly note or the daily notes. Never invent a
  number, a result, a user, or a reaction.
- Use numbers exactly as the notes have them. Never round up or estimate.
- If the notes say something is unfinished, the post does not say it shipped.
- Write only about the user's own work. Do not name other people, clients,
  employers or companies that appear in the notes, and do not quote private
  conversations. Describe them by role instead ("a client", "a teammate").
- Leave out anything that reads like a secret or internal detail: credentials,
  internal URLs, hostnames, unreleased plans, money figures.

## Voice

- First person, past tense, plain English. Short sentences.
- Start with the point. No "I'm excited to share", "Thrilled to announce",
  "Here's what I learned", "Let me tell you".
- No hype words: game-changer, revolutionary, supercharge, unlock, 10x, insane.
- No engagement bait: no "Agree?", "Thoughts?", "Comment below", no fake
  cliffhangers, no one-line-per-sentence padding to look longer.
- No emoji walls. Zero is fine; never more than two.
- No em dashes. No AI vocabulary (`skills/shared/humanizer.md`).
- Plain text only: no markdown, no `[[links]]`, no bold, no backticks. The text
  is pasted straight into the site.

## LinkedIn

- 600 to 1,300 characters is the sweet spot. Hard limit 3,000 (lint).
- First two lines carry the post: they are all that shows before "see more".
- Short paragraphs with a blank line between them.
- End on the takeaway or the open question you are honestly still working on.
- At most 3 hashtags on the last line, or none. Hard limit 5 (lint).
- No link in the body. Put a suggested link, if any, in a final line that
  starts with `First comment:` so the user can post it as a comment.

## X

- A thread of 2 to 6 posts, or a single post if that is all the week needs.
- Each post is one paragraph that starts with its number and a slash: `1/ `,
  `2/ `. Each is at most 280 characters including the number (lint).
- Post 1 must stand alone and make sense with no context.
- No hashtags unless one is truly the topic. No "🧵".

## Quiet weeks

If nothing in the week is worth a post, still write the file so the record is
complete, but be honest: the LinkedIn section is one line, `No post this week:
<short reason>.`, and the X section is `1/ No post this week.` Do not stretch
a thin week into a post.

## Good and bad

Bad:

> Excited to share a HUGE week! 🚀 Shipped tons of improvements across multiple
> projects and learned so much. Consistency is key. What did you ship? 👇

Good:

> Some of our alerts were never arriving. No error, nothing in the logs.
>
> The cause was two workers picking up the same job. One sent it, the other
> marked it failed, and the failure won.
>
> The fix was one lock per job before sending. The slow part was believing the
> queue could hand out the same job twice.
>
> If a message system "sometimes" loses things, check who else is reading the
> queue before you check the sender.
