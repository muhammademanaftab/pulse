# Pulse

Turn your Claude Code sessions into a daily work journal, automatically.

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
([skills/setup/SKILL.md](skills/setup/SKILL.md)): it deploys your Convex backend,
stores your credentials, wires the capture hook, and verifies it. The only thing you
do yourself is log in to Convex in your browser once, when Claude asks.

Prefer to run it yourself? The same work is in one script:

```
python3 skills/setup/install.py
```

It is re-runnable: the first run tells you to run `npx convex login` and
`npx convex dev --once --dev-deployment cloud`, then you run it again to finish.

After setup, capture is on. Every session is recorded from then on.

## Daily notes

The digest runs as a nightly cloud routine (works with your machine off). See
[routines/](routines/) for a paste-ready Claude routine and its setup.

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
