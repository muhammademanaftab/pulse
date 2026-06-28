# Pulse

Turn your Claude Code sessions into a daily work journal, automatically.

![Six months of Claude Code sessions, captured by Pulse and turned into a linked vault of daily and project notes](assets/graph.png)

*Every session becomes a linked daily note. Over months it builds a connected map of your work, here shown as an Obsidian graph.*

Pulse records every Claude Code session to a database you own, and each night it
writes a plain-markdown note of what you did, organized by project and ready to open
in Obsidian. You stop guessing what you got done last Tuesday.

Your data goes to your own [Convex](https://convex.dev) deployment (free tier) and
your own notes repo. There is no Pulse server and no account to create with us.

## How it works

```
Claude Code session  ─▶  capture (a Stop hook)  ─▶  your Convex deployment
                                                          │
                            nightly digest (cloud routine)│
                                                          ▼
                                     daily note  ─▶  your notes git repo  ─▶  Obsidian
```

- **Capture** is a `Stop` hook that runs a small script after every turn and saves the
  prompt and response. It is silent and never interrupts your session.
- **Digest** reads a day of sessions, groups them by project, and writes one note. It
  links each note into a monthly index so your vault stays connected, and a reviewer
  pass checks the note against the raw sessions before it is saved.

There is no plugin to install. Capture is a hook in your Claude Code settings; the
digest is a scheduled cloud routine that runs the code in this repo.

## Requirements

- Claude Code
- Node.js 18 or newer (for the Convex CLI)
- A free Convex account
- A git repo for your notes (any GitHub repo; open it in Obsidian if you like)

## Setup

Clone the repo, open it in Claude Code, and ask Claude to set it up:

```
git clone https://github.com/muhammademanaftab/pulse.git
cd pulse
```

Then in Claude Code: **"set up pulse"**. Claude follows the setup runbook
([skills/setup/SKILL.md](skills/setup/SKILL.md)) and walks you through three phases:

1. **Capture:** deploys your Convex backend, stores your credentials, wires the hook.
   You log in to Convex in your browser once, when Claude asks.
2. **Daily notes:** Claude asks where your notes should live (creates `~/pulse-notes`
   or uses a path you give), writes the config for you, and shows you a first note.
3. **Nightly routine (optional):** Claude walks you through the claude.ai routine so
   notes build automatically every night.

Prefer to run the mechanical parts yourself:

```
python3 skills/setup/install.py                          # capture
python3 skills/setup/install.py notes --repo ~/pulse-notes --create   # notes config
```

After setup, capture is on and every session is recorded.

## Daily notes

The digest runs as a nightly claude.ai routine (works with your machine off). See
[routines/](routines/) for the routine and the exact fields to fill in.

Notes are written to your notes repo, not into this one:

```
<your-notes-repo>/
└── Pulse/
    ├── Daily/
    │   ├── Pulse Index.md
    │   └── 2026-06/
    │       ├── Pulse 2026-06.md   # month hub
    │       └── 2026-06-25.md      # a daily note
    └── Projects/
```

## Configuration

Copy [`config.example.yaml`](config.example.yaml) to `~/.pulse/config.yaml` and set
where your notes live:

| Key | Meaning |
|---|---|
| `timezone` | your timezone, for grouping a day's work |
| `notes_repo` | path to your notes git repo |
| `vault_subfolder` | folder inside it for daily notes (default `Pulse/Daily`) |
| `hub_prefix` | name prefix for the monthly index |

## Status

Pulse is early (0.x). Capture and the daily-note digest are built. The weekly
synthesizer, per-project notes, and other outputs (devlog, standup, brag document)
are planned. Expect rough edges and breaking changes until 1.0.

## License

[MIT](LICENSE).
