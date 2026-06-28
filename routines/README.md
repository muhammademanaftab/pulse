# Pulse routines

Each file is one [claude.ai](https://claude.ai/code) scheduled agent that runs a
Pulse skill on a cron with your machine off. One file = one paste-ready routine.
Paste a file's fenced block into the routine's Instructions box and attach the
`pulse` environment.

| Routine | File | Cron |
|---|---|---|
| [Digest](digest.md) | yesterday's rows → daily note in your notes repo | `0 5 * * *` |

## Environment: `pulse`

One claude.ai environment, shared by every routine:

| Variable | Meaning |
|---|---|
| `CONVEX_URL` | your `.convex.site` URL (same as `~/.pulse/.env`) |
| `CONVEX_TOKEN` | your `INGEST_TOKEN` (same as `~/.pulse/.env`) |
| `PULSE_TZ` | your IANA timezone, e.g. `Europe/Berlin` |

The scripts read these (env wins over any file), so the routine needs no config
file on disk.

## Notes repo access

Give the routine read/write access to your notes repo one of two ways, whichever
you prefer:

- **Attach the GitHub repo to the routine** on claude.ai. The built-in GitHub
  integration handles the checkout and the push for you, no token needed.
- **Or use a GitHub token.** Set `GITHUB_TOKEN` (a fine-grained PAT with contents
  read/write on the notes repo) plus `NOTES_REPO_REMOTE` (its HTTPS clone URL) in
  the environment; the routine clones and pushes over HTTPS with
  `https://x-access-token:${GITHUB_TOKEN}@github.com/<you>/<notes-repo>.git`.

Rule every routine follows: stop on any gate failure, and **never mark rows
processed until the push is verified** (else the next run retries cleanly).
