---
name: setup
description: First-time setup for Pulse capture. Use when the user says "set up pulse", "install pulse", "connect pulse", or asks to start capturing their Claude Code sessions. Drives the whole setup; the user only does the Convex browser login.
---

# Pulse setup (agent-driven)

Get the user from a fresh clone to live capture. You do the work and explain each
step; the user only logs in to Convex in their browser once. The safe, mechanical
parts (writing credentials, editing `~/.claude/settings.json`, verifying) are done
by `skills/setup/install.py`, so you never hand-edit the user's settings. Run everything
from the repo root.

## Steps

1. **Say what will happen.** One sentence: "I'll deploy your own Convex backend, wire
   the capture hook, and confirm it works. You'll just log in to Convex once."

2. **Run the setup script:**

   ```bash
   python3 skills/setup/install.py
   ```

   It is re-runnable and reports what it did. Read its output and act on it:

   - **If it prints the Convex login commands** (the deployment does not exist yet),
     the user must run them. Show them clearly and ask the user to run them in their
     own terminal (the `! ` prefix runs a command in this session):

     ```
     ! cd convex-backend && npx convex login
     ! cd convex-backend && npx convex dev --once --dev-deployment cloud
     ```

     The second one asks them to pick a team and name the project (suggest `pulse`).
     Wait for them to confirm both finished, then run `python3 skills/setup/install.py`
     again to finish.

   - **If it finishes** (writes credentials, installs the hook, verifies a probe),
     setup is done. Move on.

3. **Confirm and explain.** Tell the user plainly:
   - Capture is live: every Claude Code turn now records to their own Convex.
   - It is silent and never interrupts a session; logs are at `~/.pulse/capture.log`.

4. **Offer the next step (optional).** Daily notes need a notes git repo. Ask if they
   want to set that up now: copy `config.example.yaml` to `~/.pulse/config.yaml` and
   set `notes_repo` to their notes repo path. Then the digest (see `routines/`) can
   write daily notes. If they are not ready, leave it; capture works without it.

## Rules

- Never hand-edit `~/.claude/settings.json` yourself. `install.py` does that safely
  (it backs up and merges without touching other settings). Your job is to run it and
  guide the user.
- The Convex browser login is the only step the user must do themselves. Everything
  else is yours to run.
- If `install.py` stops with an error, relay its exact message; do not guess around it.

$ARGUMENTS
