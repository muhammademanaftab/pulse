---
name: setup
description: First-time setup for Pulse. Use when the user says "set up pulse", "install pulse", "connect pulse", or asks to start capturing their Claude Code sessions. Drives the whole setup; the user only does the Convex browser login and the claude.ai routine UI.
---

# Pulse setup (agent-driven)

Take the user from a fresh clone to: capture live, daily notes configured, a first
note produced, and (optionally) a nightly routine. You run the mechanical work via
`skills/setup/install.py`; never hand-edit the user's `settings.json` or `config.yaml`.
Run everything from the repo root. Do the phases in order.

## Phase 1: Capture

1. Say what will happen in one sentence, then run:

   ```bash
   python3 skills/setup/install.py
   ```

2. If it prints the Convex login commands (no deployment yet), have the user run them
   in their terminal (the `! ` prefix runs in this session), then re-run the script:

   ```
   ! cd convex-backend && npx convex login
   ! cd convex-backend && npx convex dev --once --dev-deployment cloud
   ```

   The second asks them to pick a team and name the project (suggest `pulse`).

3. When it finishes (creds written, hook installed, probe verified), tell them: capture
   is live, every Claude Code turn now records to their Convex, silent, logs at
   `~/.pulse/capture.log`.

## Phase 2: Daily notes

4. Ask where notes should live: offer to create `~/pulse-notes`, or take a path they
   give. Then run (add `--create` when making a new repo):

   ```bash
   python3 skills/setup/install.py notes --repo <path> --create
   ```

   This git-inits the repo, auto-detects their timezone, and writes
   `~/.pulse/config.yaml`. Confirm the detected timezone with them; pass
   `--timezone <IANA>` if wrong.

5. Produce a first note as a preview: follow `skills/digest/SKILL.md` for the most
   recent day with data, but stop after the gates. **Do NOT push or mark rows
   processed** (the routine owns that). Show the user the note path.

   If `digest.py fetch` returns `event_count` 0 (brand-new user, nothing captured
   yet), tell them plainly: notes appear once they've used Claude Code, and they can
   run the digest later. Do not treat this as an error.

## Phase 3: Nightly routine (optional)

6. Ask if they want notes built automatically every night (works with their machine
   off). If yes, walk them through creating the claude.ai routine, telling them the
   exact value for each field. Use `routines/README.md` as the source; the fields:

   - **Name:** `Pulse Daily Digest`
   - **Instructions:** paste the fenced block from `routines/digest.md`
   - **Model:** latest Sonnet or Opus
   - **Repos:** attach two: this `pulse` repo and their notes repo
   - **Trigger:** daily, late evening in their timezone
   - **Environment** `pulse`: **Network access = Full**, and these `.env` variables
     (read `CONVEX_URL`/`CONVEX_TOKEN` from their `~/.pulse/.env` and give them the
     exact lines): `CONVEX_URL`, `CONVEX_TOKEN`, `PULSE_TZ`, `NOTES_REPO`,
     `NOTES_REPO_REMOTE`, and `GITHUB_TOKEN` (or attach the notes repo instead). Setup
     script: none.
   - **Permissions:** allow git push to the notes repo

7. State the caveat: the environment's variables include secrets (`CONVEX_TOKEN`,
   `GITHUB_TOKEN`) and claude.ai shows them to anyone who can use that environment, so
   keep it private and never shared.

8. The notes repo must exist on GitHub for the routine to push. If theirs is local
   only, walk them through creating the GitHub repo and adding it as the remote.

## Rules

- Never hand-edit `~/.claude/settings.json` or `~/.pulse/config.yaml`; `install.py`
  writes both safely (backup, merge, idempotent).
- The only steps the user does themselves: the Convex login (Phase 1) and the
  claude.ai routine UI (Phase 3). Everything else is yours to run.
- The Phase 2 first note is preview-only: never push or mark rows processed during setup.
- If `install.py` stops with an error, relay its exact message; do not guess around it.

$ARGUMENTS
