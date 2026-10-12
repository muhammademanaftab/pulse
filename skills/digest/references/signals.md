# Signals, not steps

Some events are not actions, they are signals. These are often the most valuable
thing in a day's log, and they never show up as tool calls. If you only write
"what was done" bullets, you lose all of it. Capture each one inside its project's
Work log block, using the prefix from `note-structure.md` so it can be found later
with a plain search.

A *step* is something the user did: ran a command, wrote a file. A *signal* is
something the user **learned, decided, or kept repeating.**

## The four signal types

### 1. Standing principles / briefs

If the user states the same constraint across 3+ prompts in a day, or states it as
a rule ("never", "always"), that is a rule for future work, not a one-time edit.
Write it as a `- Rule:` bullet.

> - Rule: every API handler must validate input before touching the database.
>   Stated 4 times while reviewing the webhook code.

### 2. Confusion → resolution

When the user asks "why is X happening?" and gets an answer that resolves it,
capture the answer as a `- Learned:` bullet. The confusion will recur; the answer
belongs in the log.

> - Learned: the retry fired twice because the client and the queue both had
>   their own backoff.

### 3. Decisions and rejections

When the user picks option B over A, or rejects a drafted approach, write a
`- Decided:` bullet with the reason and the rejected option. Decisions explain
*why* something is the way it is, the most reusable thing in a log.

> - Decided: keep the worker stateless and push state to the DB. Why: workers are
>   restarted on every deploy. Rejected: caching state in memory.

### 4. Failed attempts that taught something

If a command errored, a path did not work, a dependency was missing, write what
did not work and why, not just the eventual fix. Use `- Bug:` when it was a defect
in something being built, `- Learned:` when it was an environment or tooling
gotcha.

> - Learned: `npm install -g` fails here because there is no global Node on PATH.
>   Use nvm: every CLI call sources nvm first.
