"""Shared helpers for the Pulse skill scripts (digest.py, synth.py).

Config, timezone, the existence-based linking rule, and the month hub + index
wiring. Stdlib only. Each skill script adds this folder to sys.path and imports
what it needs.
"""
from __future__ import annotations

import os
import re
import sys
from datetime import datetime, timezone

MONTHS = ["January", "February", "March", "April", "May", "June", "July",
          "August", "September", "October", "November", "December"]

DASH_RE = re.compile(r"[—–]")
FENCE_RE = re.compile(r"```.*?```", re.S)
CODE_RE = re.compile(r"`[^`\n]*`")


def strip_code(text: str) -> str:
    return CODE_RE.sub("", FENCE_RE.sub("", text))


def utf8_stdio() -> None:
    # Piped stdio uses the console codepage on Windows; JSON and notes are UTF-8.
    for stream in (sys.stdin, sys.stdout):
        stream.reconfigure(encoding="utf-8")


# --- config -----------------------------------------------------------------

def pulse_home() -> str:
    return os.path.expanduser(os.environ.get("PULSE_HOME", "~/.pulse"))


def read_config(path: str) -> dict:
    cfg: dict = {}
    if not os.path.isfile(path):
        return cfg
    try:
        for line in open(path, encoding="utf-8"):
            line = line.split("#", 1)[0].strip()
            if not line or ":" not in line:
                continue
            k, v = line.split(":", 1)
            k, v = k.strip(), v.strip().strip('"').strip("'")
            if v:
                cfg[k] = v
    except Exception:
        pass
    return cfg


def load_config() -> dict:
    return read_config(os.path.join(pulse_home(), "config.yaml"))


def cfg_get(cfg: dict, key: str, env: str | None, default: str) -> str:
    """Env var wins, then config.yaml, then the default."""
    if env and os.environ.get(env):
        return os.environ[env]
    return cfg.get(key, default)


def get_tz(cfg: dict):
    name = cfg_get(cfg, "timezone", "PULSE_TZ", "UTC")
    if name and name != "UTC":
        try:
            from zoneinfo import ZoneInfo
            return ZoneInfo(name)
        except Exception:
            # Windows Python ships no tz database; without this the day window
            # would silently shift to UTC.
            print(f"warning: unknown timezone {name!r}, using UTC "
                  "(on Windows: pip install tzdata)", file=sys.stderr)
    return timezone.utc


# --- linking rule (existence-based) -----------------------------------------

def render_label(label: str, projects_dir: str | None) -> str:
    """Wikilink iff the project note exists, else bold. No dead links possible."""
    if projects_dir and os.path.isfile(
            os.path.join(os.path.expanduser(projects_dir), f"{label}.md")):
        return f"[[{label}]]"
    return f"**{label}**"


# --- month hub + index wiring -----------------------------------------------

def upsert_list(text: str, heading: str, new_line: str, reverse: bool = False):
    """Add new_line to the sorted list under heading. Returns (text, changed)."""
    if new_line in text:
        return text, False
    lines = text.split("\n")
    try:
        h = lines.index(heading)
    except ValueError:
        return text.rstrip("\n") + f"\n\n{heading}\n\n{new_line}\n", True
    i = h + 1
    while i < len(lines) and lines[i].strip() == "":
        i += 1
    start = i
    while i < len(lines) and lines[i].startswith("- "):
        i += 1
    lines[start:i] = sorted(set(lines[start:i] + [new_line]), reverse=reverse)
    out = "\n".join(lines)
    return (out if out.endswith("\n") else out + "\n"), True


def _write(path: str, text: str) -> None:
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)


def link_into_hubs(args, kind: str) -> int:
    """Link the dated note into its month hub, and the hub into the index.
    Idempotent; creates either file if missing. kind is "daily" or "weekly";
    args carries vault, subfolder, date, hub_prefix, index."""
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", args.date):
        print(f"ERROR: --date must be YYYY-MM-DD, got {args.date!r}", file=sys.stderr)
        return 1
    weekly = kind == "weekly"
    d = datetime.strptime(args.date, "%Y-%m-%d")
    ym = args.date[:7]
    mname = f"{MONTHS[d.month - 1]} {d.year}"
    day = f"{MONTHS[d.month - 1][:3]} {d.day}"
    list_heading = "## Weeks" if weekly else "## Days"
    vault = os.path.abspath(os.path.expanduser(args.vault))
    sub = args.subfolder.strip("/")
    hub_name = f"{args.hub_prefix} {ym}"
    hub_path = os.path.join(vault, sub, ym, f"{hub_name}.md")
    index_path = os.path.join(vault, sub, args.index)
    index_stem = os.path.splitext(args.index)[0]

    if not os.path.isfile(hub_path):
        os.makedirs(os.path.dirname(hub_path), exist_ok=True)
        _write(hub_path,
               f"---\ntype: {'weekly-hub' if weekly else 'month-hub'}\nmonth: \"{ym}\"\n"
               f"tags: [pulse, hub]\n---\n\n# {args.hub_prefix} notes, {mname}\n\n"
               f"Part of [[{index_stem}]].\n\n{list_heading}\n")
        print(f"CREATED hub {hub_path}")
    link = f"- [[{sub}/{ym}/{args.date}|{'Week of ' + day if weekly else day}]]"
    text, changed = upsert_list(open(hub_path, encoding="utf-8").read(), list_heading, link)
    if changed:
        _write(hub_path, text)
        print(f"LINKED {args.date} in {os.path.basename(hub_path)}")

    if not os.path.isfile(index_path):
        os.makedirs(os.path.dirname(index_path), exist_ok=True)
        _write(index_path,
               f"---\ntype: index\ntags: [pulse, index]\n---\n\n# {args.hub_prefix} notes\n\n"
               f"Auto-maintained index of {'weekly' if weekly else 'monthly'} note hubs.\n\n"
               f"## Months\n")
        print(f"CREATED index {index_path}")
    text, changed = upsert_list(open(index_path, encoding="utf-8").read(),
                                "## Months", f"- [[{hub_name}|{mname}]]", reverse=True)
    if changed:
        _write(index_path, text)
        print(f"LINKED {hub_name} in {os.path.basename(index_path)}")
    print("OK")
    return 0
