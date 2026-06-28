# Signals, not steps

Some events are not actions, they are signals. These are often the most valuable
thing in a day's log, and they never show up as tool calls. If you only write
"what was done" bullets, you lose all of it. Capture each of these under the
"Decisions & signals" section.

A *step* is something the user did: ran a command, wrote a file. A *signal* is
something the user **learned, decided, or kept repeating.**

## The four signal types

### 1. Standing principles / briefs

If the user states the same constraint or directive across 3+ prompts in a day,
that is a rule for future work, not a one-time edit. Capture it as a brief.

> Brief: every API handler must validate input before touching the database.
> Repeated 4 times while reviewing the webhook code.

### 2. Confusion → resolution

When the user asks "why is X happening?" and gets an answer that resolves it,
capture both halves in one line. The confusion will recur; the resolution belongs
in the log.

> Clarified that the retry was firing twice because the client and the queue both
> had their own backoff.

### 3. Decisions and rejections

When the user picks option B over A, or rejects a drafted approach, name it.
Decisions encode *why* something is the way it is, the most reusable thing in a log.

> Chose to keep the worker stateless and push state to the DB rather than cache it
> in memory.

### 4. Failed attempts that taught something

If a command errored, a path did not work, a dependency was missing, write what
did not work and why, not just the eventual fix. A failure with a lesson is worth
more than the fix alone.

> `npm install -g` failed, no global Node on PATH. Switched to nvm, every later
> CLI call now sources nvm first.
