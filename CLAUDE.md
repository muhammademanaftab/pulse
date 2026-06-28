# Pulse: Claude Context

Orientation for Claude sessions. The code is the source of truth; this file is the
map. Eman drives the work directly in conversation.

## What this is

Pulse is an open-source memory engine for AI-assisted work, built around Claude Code. It
captures every Claude Code turn to the user's own Convex deployment, then a nightly
digest turns each day into an Obsidian-style daily note in the user's notes git repo.
Future: a weekly synthesizer and output heads (devlog, standup, brag doc). It is a
genericized public extraction of a private agent pipeline.

Built by Muhammad Eman Aftab (GitHub: muhammademanaftab). Solo project.

## Architecture (Convex-backed; NOT a Claude Code plugin)

This is deliberately not packaged as a plugin. Distribution is "clone the repo +
run a setup script" (capture) and "a cloud routine that clones the repo and runs the
digest SKILL" (notes), matching how Eman actually runs it.

- **Capture (L0):** `skills/setup/capture.py` runs as a `Stop` hook in the user's
  `~/.claude/settings.json`, POSTing each turn to `{CONVEX_URL}/ingest`. Creds in
  `~/.pulse/.env`. No-ops if unconfigured, always exits 0 (never breaks a session).
- **Setup:** `skills/setup/SKILL.md` (agent-driven runbook) + `skills/setup/install.py`
  (re-runnable, stdlib only). install.py deploys the backend, writes `~/.pulse/.env`,
  copies capture.py to `~/.claude/hooks/pulse-capture.py`, and safely merges the `Stop`
  hook into `settings.json`. The user only does the Convex browser login.
- **Backend (L1):** `convex-backend/` is a per-user Convex deployment. A `prompts`
  table + HTTP API (`/ingest`, `/unprocessed`, `/all`, `/mark-processed`), Bearer
  auth via `INGEST_TOKEN`.
- **Digest (L3):** `skills/digest/digest.py` (subcommands `fetch`, `render-block`,
  `month-links`, `lint`, `coverage`, `check-links`) + `skills/digest/SKILL.md` (the
  LLM runbook, read by the routine; paths are repo-relative). Writes an Obsidian daily
  note to the user's notes repo, links it into a month hub + index, runs the three
  gates and a reviewer subagent, then commits/pushes and marks rows processed.
- **Nightly:** `routines/` holds claude.ai cloud routines (`digest.md`) that clone the
  repo and run the digest with the machine off.

Rules that are the product: the daily note is derived (regenerate-and-overwrite);
linking is existence-based (`[[Project]]` only if the note exists, so no dead links);
the month hub + index keep the graph whole; never mark a Convex row processed until
its note is confirmed pushed.

## Status

- **Done:** capture (milestone 1); digest + `routines/` + reviewer subagent
  (milestone 2). Verified against mock endpoints and locally; CI compiles the scripts
  and exercises the linking rule and gates.
- **Not built yet:** project-note creation (the synthesizer's job; projects render
  bold until then), the weekly synthesizer + semantic memory, the safety/redaction
  firewall, output heads (devlog/standup/bragdoc), a notes-repo bootstrap for new
  users, and LICENSE + README (removed to keep the pre-release repo minimal; re-add
  before going public).
- **Biggest unknown:** claude.ai-sandbox git-push auth, proven on the first real
  routine run.
- Working branch: `feat/convex-onboarding` (not pushed).

## HARD security rules (the repo is public-bound)

1. NEVER share git history with the private vault. Hand-copy file contents only.
2. Scrub before anything enters this repo: the author's employer and product names,
   person names, internal hostnames, Telegram/Convex identifiers, and private vault
   folder structure. (The specific denylist lives privately, not in this public repo.)
3. Before any push, grep the diff for that scrub list.
4. Captured data (`~/.pulse/`, `*.jsonl`, `.env`) is gitignored and must never be
   committed.

## Working rules

- **No em dashes** anywhere (docs, code, comments). Strong standing preference. Use
  commas, periods, colons, parentheses.
- Plain English, no hype words.
- Keep it concrete, not granular: few files, one script per skill, no unused code.
- Assume every commit message and file will be read by strangers.
