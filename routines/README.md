# Pulse routines

A routine is a scheduled [claude.ai](https://claude.ai/code) agent that runs a Pulse
skill on a cron with your machine off. One file here = one routine.

| Routine | File | Cron |
|---|---|---|
| Digest | [digest.md](digest.md) | daily, late evening |
| Synth | [synth.md](synth.md) | weekly, early in the week |

## Create the routine (every field)

In claude.ai, create a routine and fill these. The values below are for the daily
digest; the weekly synth uses the same shape with the changes noted underneath.

| Field | Value |
|---|---|
| **Name** | `Pulse Daily Digest` |
| **Instructions** | the fenced block in [digest.md](digest.md) |
| **Model** | latest Sonnet or Opus |
| **Repos** | your **notes** repo (gets the note). For the pulse code, pick one below. |
| **Trigger** | daily cron, late in your day (e.g. `11:59 PM` in your timezone) |
| **Environment** | the `pulse` cloud environment below |
| **Permissions** | allow git push to the notes repo |
| **Connectors** | GitHub connector if you attach the notes repo instead of using a token |

For the **weekly synth**, create a second routine with the same fields but:
`Name` = `Pulse Weekly Synth`, `Instructions` = the fenced block in
[synth.md](synth.md), and `Trigger` = a weekly cron early in the week (e.g. Monday
morning) so the finished week is complete. It reads your daily notes and does not
touch Convex, so it can share the `pulse` environment (the Convex variables just go
unused).

## The `pulse` cloud environment

| Setting | Value |
|---|---|
| **Name** | `pulse` |
| **Network access** | **Full** (needs Convex + GitHub) |
| **Setup script** | none |

**Environment variables** (`.env` format):

```
CONVEX_URL=<your .convex.site URL, from ~/.pulse/.env>
CONVEX_TOKEN=<your INGEST_TOKEN, from ~/.pulse/.env>
PULSE_TZ=<your IANA timezone, e.g. Europe/Berlin>
NOTES_REPO=notes
NOTES_REPO_REMOTE=https://github.com/<you>/<notes-repo>.git
GITHUB_TOKEN=<fine-grained PAT, contents read/write on the notes repo>
```

`CONVEX_URL` and `CONVEX_TOKEN` are the same values `~/.pulse/.env` holds. `GITHUB_TOKEN`
is only needed for the token path (skip it if you attach the notes repo as a connector).

**Keep this environment private.** Its variables include secrets (`CONVEX_TOKEN`,
`GITHUB_TOKEN`) and claude.ai shows them to anyone who can use the environment. Do not
share it.

## Pulse code (pick one)

- **Clone at runtime (recommended):** attach only your notes repo; the routine's
  instructions clone the public pulse repo at a pinned release tag (currently
  `v0.2.0`) each run, so an unattended push-capable agent only ever runs reviewed,
  tagged code. When you cut a new release, bump the `--branch` tag in
  `digest.md` and `synth.md`.
- **Attach the pulse repo:** attach it alongside your notes repo to pin the version.

## Notes repo access (pick one)

- **Attach the repo:** add your notes repo to the routine; claude.ai handles checkout and
  push. No `GITHUB_TOKEN` needed.
- **Token:** set `GITHUB_TOKEN` + `NOTES_REPO_REMOTE`; the routine clones and pushes via
  `https://x-access-token:${GITHUB_TOKEN}@github.com/<you>/<notes-repo>.git`.

The notes repo must exist on GitHub for the routine to push to it.

## Rule every routine follows

Stop on any gate or reviewer failure, and never mark rows processed until the push is
verified. A failed day's rows stay unprocessed; run the digest for that date by hand
to backfill it.
