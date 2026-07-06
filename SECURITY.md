# Security

Pulse captures your Claude Code sessions to a Convex deployment you own, then turns
them into notes in a git repo you own. Nothing is sent to the maintainer. This file
explains what is stored, how it is protected, and the limits of that protection.

## What gets captured

The capture hook (`skills/setup/capture.py`) runs as a Claude Code `Stop` hook. For
each turn it stores, in your Convex deployment:

- your prompt text and the assistant response (including thinking blocks)
- tool calls and their inputs, with `content`, `old_string`, and `new_string`
  dropped (file bodies and edit payloads are never sent)
- project name, working directory path, git user name, session id, timestamp, model

## How it is protected

- **Redaction.** Before anything leaves your machine, capture scrubs common secret
  shapes: private key blocks, AWS / GitHub / Slack / OpenAI-style keys, `Bearer`
  headers, `key=value` assignments for api-key / token / secret / password, and long
  hex runs. Matches become `[REDACTED:<kind>]`.
- **This is best-effort, not a guarantee.** Novel or unusual secret formats can slip
  through. Do not rely on it as your only control. If you paste a credential into a
  session, rotate it. The redaction patterns live in `capture.py` (`REDACT_PATTERNS`)
  and are easy to extend for your own formats.
- **Transport.** Capture and the digest refuse a non-`https://` `CONVEX_URL`, so the
  ingest token and your content never cross the network in cleartext.
- **Auth.** The backend accepts only requests bearing your `INGEST_TOKEN`
  (`Authorization: Bearer ...`), compared in constant time. The token is a 64-char
  random hex value generated at setup.
- **Credentials on disk.** `~/.pulse/.env` holds `CONVEX_URL` and `CONVEX_TOKEN`
  and is written `0600` (owner read/write only). Captured data under `~/.pulse/`
  and any `.env` or `*.jsonl` are gitignored and must never be committed.
- **Size limits.** Fields are truncated before send and the backend rejects
  oversized bodies, so a single huge turn cannot wedge ingestion.

## Unattended runs

The nightly digest and weekly synth run unattended with push access to your notes
repo. Two guards apply:

- Captured content is treated as untrusted data, never as instructions (see the
  guard note at the top of `skills/digest/SKILL.md` and `skills/synth/SKILL.md`).
- The routines clone the pulse repo at a pinned release tag, so an unattended agent
  only runs reviewed, tagged code.

## Reporting a vulnerability

Open a GitHub security advisory on this repository, or a private issue. Please do
not disclose publicly until a fix is available.
