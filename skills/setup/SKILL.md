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
   ! cd backend && npx convex login
   ! cd backend && npx convex dev --once --dev-deployment cloud
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

5. Produce a first note as a preview. Find a day with data: run
   `python3 skills/digest/digest.py fetch --date today --include-today`, and if its
   `event_count` is 0, try `--date yesterday`. Then follow `skills/digest/SKILL.md`
   steps 4 to 7 for that day (write the note, wire it, run the three gates) and
   stop there: skip the reviewer (7b) and all of step 8. **Do NOT commit, push, or
   run `mark-processed`**, even where the digest runbook says to (the routine owns
   that). Show the user the note path.

   If both days have `event_count` 0 (brand-new user, nothing captured yet), tell
   them plainly: notes appear once they've used Claude Code, and they can run the
   digest later. Do not treat this as an error.

6. Install the recall skill, so they can ask about past work from any project
   ("when did I fix the alert bug?") with `/pulse-recall`:

   ```bash
   python3 skills/setup/install.py recall
   ```

## Phase 3: Nightly routine (optional)

7. Ask if they want notes built automatically every night (works with their machine
   off). If yes, walk them through creating the claude.ai routine, telling them the
   exact value for each field. Use `routines/README.md` as the source; the fields:

   - **Name:** `Pulse Daily Digest`
   - **Instructions:** paste the fenced block from `routines/digest.md`
   - **Model:** latest Sonnet or Opus
   - **Repos:** attach their notes repo. For the pulse code, either attach this repo
     too, or let the routine clone it at runtime (recommended, only the notes repo attached)
   - **Trigger:** daily, late evening in their timezone
   - **Environment** `pulse`: **Network access = Full**, and these `.env` variables
     (tell them to copy the `CONVEX_URL` and `CONVEX_TOKEN` lines straight from
     `~/.pulse/.env`; do not read the token out or print it in the chat):
     `CONVEX_URL`, `CONVEX_TOKEN`, `PULSE_TZ`, `NOTES_REPO`,
     `NOTES_REPO_REMOTE`, and `GITHUB_TOKEN` (or attach the notes repo instead). Setup
     script: none.
   - **Permissions:** allow git push to the notes repo

8. State the caveat: the environment's variables include secrets (`CONVEX_TOKEN`,
   `GITHUB_TOKEN`) and claude.ai shows them to anyone who can use that environment, so
   keep it private and never shared.

9. The notes repo must exist on GitHub for the routine to push. If theirs is local
   only, walk them through creating the GitHub repo and adding it as the remote.

## Rules

- Never hand-edit `~/.claude/settings.json` or `~/.pulse/config.yaml`; `install.py`
  writes both safely (it backs up, keeps the user's other settings, and can be re-run).
- The only steps the user does themselves: the Convex login (Phase 1) and the
  claude.ai routine UI (Phase 3). Everything else is yours to run.
- The Phase 2 first note is preview-only: never push or mark rows processed during setup.
- If `install.py` stops with an error, relay its exact message; do not guess around it.

$ARGUMENTS
