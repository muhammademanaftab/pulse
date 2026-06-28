# Bullet quality

Read this before writing any work-log bullet. Bullets fail in two ways: they say
something that did not happen ("merged a branch" when only a delete ran), or they
say it too vaguely to find again ("cleaned up some files"). This covers both:
truth-checking against the response, and specificity that keeps a bullet useful
six months from now.

## 1. Truth-check against the response, not the prompt

The prompt is what the user asked for. The **response** shows what actually
happened. Verify every bullet against the response text and its tool calls.

- **Read the `<tool_use>` blocks. They are ground truth.** `Bash`, `Edit`,
  `Write`, `Read`, API calls: these tell you what was done, not what was discussed.
- **Match the verb to reality:**
  - `Write` used → "wrote"
  - `Edit` used → "edited" (or "patched" for a one-line fix)
  - `Read` only, no Write/Edit → "reviewed" or "discussed", NOT "wrote"
  - a delete command → "deleted", NOT "merged"
  - a merge → "merged"
  - tested/ran and it passed → "tested" / "confirmed"
- **Confirm completion before claiming it.** If the response shows the tool call
  but an error or no success output, say "attempted" or describe the failure.
- **If you cannot verify a claim from the response, leave it out.** Undersell
  rather than invent.
- **Capture the payoff, not just the setup.** The most important bullet is often
  the moment work pays off: a test passes, a call returns real data, a deploy goes
  green, numbers match. Read the last events' responses for the result, not only
  the prompts for the ask. Missing a verified win is a real failure, not safe
  underselling.

## 2. Specificity (non-negotiable)

The reader six months from now must be able to find the artifact from the bullet
alone.

- **Name files by path or filename.** Not "the script", say `src/webhook.ts`.
- **Name identifiers verbatim.** Branches, refs, IDs, config keys, exact values.
- **Use exact counts.** Banned: "multiple", "several", "various", "some", "many",
  "a few". Replace with the number ("deleted 1 stale branch", "rejected 5 drafts").
- **Name assets by their title** (a doc, a post, a feature), never "the doc".
- **Include exact tool names, flags, and parameters** when they were iterated on.
  Implementation specifics answer "how did I do this last time?".

## 3. Don't bullet the plumbing

Workflow chrome is not worth a bullet on its own: PR opened/merged/closed, branch
created/deleted/renamed, commit + push, rebase, fetch, stash, file moved or
gitignored, a ticket filed or re-titled, "updated README to reflect new path".
These show how work landed, not what was built. A plumbing bullet is OK only when
the plumbing IS the substance (a real engineering decision, like swapping one
integration for another), not the mechanics of shipping it.

## 4. Voice

Plain English, no em dashes (the humanizer pass enforces tone). Short, concrete,
named. The weekly synthesizer reads these notes later, so the cleaner the signal
here, the better everything built on top.
