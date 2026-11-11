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
MONTH_DIR_RE = re.compile(r"^\d{4}-\d{2}$")
DATE_FILE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}\.md$")
BANNED_WORDS = ["non-trivial", "leveraging", "baked into", "kicked off", "blast radius",
                "key finding", "non-negotiable", "iteratively", "front-of-mind",
                "underweighted", "pushed through", "delve", "seamlessly"]
BANNED_RE = re.compile(r"\b(?:" + "|".join(re.escape(w) for w in BANNED_WORDS) + r")\b", re.I)

# The daily-note layout the digest writes (skills/digest/references/note-structure.md).
HEADING_RE = re.compile(
    r"^###\s+(?:\[\[(?P<link>[^\]#|]+)(?:[#|][^\]]*)?\]\]|\*\*(?P<bold>[^*]+)\*\*)")
ANY_H3_RE = re.compile(r"^###\s")
H2_RE = re.compile(r"^##\s")
BULLET_RE = re.compile(r"^\s*-\s+(.*)$")
TASK_RE = re.compile(r"^- \[( |x|X)\] (.+)$")
LOOP_TAG_RE = re.compile(
    r"\s*\((?P<project>(?:[^()]|\([^()]*\))*?),\s*since (?P<since>[A-Z][a-z]{2} \d{1,2})[^()]*\)\s*$")


def strip_code(text: str) -> str:
    return CODE_RE.sub("", FENCE_RE.sub("", text))


def strip_code_blocks(text: str) -> str:
    """Blank out fenced code but keep the line count."""
    return FENCE_RE.sub(lambda m: "\n" * m.group(0).count("\n"), text)


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


# kind: (hub frontmatter type, list heading, one entry per week?, index blurb)
HUB_KINDS = {
    "daily": ("month-hub", "## Days", False, "monthly note hubs"),
    "weekly": ("weekly-hub", "## Weeks", True, "weekly note hubs"),
    "posts": ("posts-hub", "## Posts", True, "monthly hubs of post drafts"),
}


def link_into_hubs(args, kind: str) -> int:
    """Link the dated note into its month hub, and the hub into the index.
    Idempotent; creates either file if missing. kind is a HUB_KINDS key; args
    carries vault, subfolder, date, hub_prefix, index."""
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", args.date):
        print(f"ERROR: --date must be YYYY-MM-DD, got {args.date!r}", file=sys.stderr)
        return 1
    hub_type, list_heading, per_week, blurb = HUB_KINDS[kind]
    d = datetime.strptime(args.date, "%Y-%m-%d")
    ym = args.date[:7]
    mname = f"{MONTHS[d.month - 1]} {d.year}"
    day = f"{MONTHS[d.month - 1][:3]} {d.day}"
    vault = os.path.abspath(os.path.expanduser(args.vault))
    sub = args.subfolder.strip("/")
    hub_name = f"{args.hub_prefix} {ym}"
    hub_path = os.path.join(vault, sub, ym, f"{hub_name}.md")
    index_path = os.path.join(vault, sub, args.index)
    index_stem = os.path.splitext(args.index)[0]

    if not os.path.isfile(hub_path):
        os.makedirs(os.path.dirname(hub_path), exist_ok=True)
        _write(hub_path,
               f"---\ntype: {hub_type}\nmonth: \"{ym}\"\n"
               f"tags: [pulse, hub]\n---\n\n# {args.hub_prefix} notes, {mname}\n\n"
               f"Part of [[{index_stem}]].\n\n{list_heading}\n")
        print(f"CREATED hub {hub_path}")
    link = f"- [[{sub}/{ym}/{args.date}|{'Week of ' + day if per_week else day}]]"
    text, changed = upsert_list(open(hub_path, encoding="utf-8").read(), list_heading, link)
    if changed:
        _write(hub_path, text)
        print(f"LINKED {args.date} in {os.path.basename(hub_path)}")

    if not os.path.isfile(index_path):
        os.makedirs(os.path.dirname(index_path), exist_ok=True)
        _write(index_path,
               f"---\ntype: index\ntags: [pulse, index]\n---\n\n# {args.hub_prefix} notes\n\n"
               f"Auto-maintained index of {blurb}.\n\n"
               f"## Months\n")
        print(f"CREATED index {index_path}")
    text, changed = upsert_list(open(index_path, encoding="utf-8").read(),
                                "## Months", f"- [[{hub_name}|{mname}]]", reverse=True)
    if changed:
        _write(index_path, text)
        print(f"LINKED {hub_name} in {os.path.basename(index_path)}")
    print("OK")
    return 0


# --- reading daily notes ----------------------------------------------------

def list_dated_notes(daily_dir: str) -> list[str]:
    """Every YYYY-MM-DD.md in the YYYY-MM folders under daily_dir, oldest first."""
    if not os.path.isdir(daily_dir):
        return []
    notes = []
    for month in os.listdir(daily_dir):
        mdir = os.path.join(daily_dir, month)
        if MONTH_DIR_RE.match(month) and os.path.isdir(mdir):
            notes += [os.path.join(mdir, f) for f in os.listdir(mdir) if DATE_FILE_RE.match(f)]
    return sorted(notes, key=os.path.basename)


def read_note(path: str) -> str:
    return open(path, encoding="utf-8", errors="replace").read()


def h2_body(text: str, heading: str) -> str | None:
    m = re.search(rf"^{re.escape(heading)}[ \t]*\n(.*?)(?=^## |\Z)", text, re.M | re.S)
    return m.group(1) if m else None


def loop_text(line: str) -> str:
    """An Open loops line without its checkbox and `(Project, since ...)` tag."""
    m = TASK_RE.match(line)
    return LOOP_TAG_RE.sub("", m.group(2) if m else line).strip()


def parse_note(text: str):
    """Return (summary, blocks). summary is the ## Summary text; blocks is a
    list of {project, bold, bullets} from the ## Work log section."""
    summary_lines: list[str] = []
    blocks: list[dict] = []
    current: dict | None = None
    section = None  # None | "summary" | "worklog"

    for raw in text.splitlines():
        line = raw.rstrip()
        if H2_RE.match(line):
            if current:
                blocks.append(current)
                current = None
            low = line.strip().lower()
            section = {"## summary": "summary", "## work log": "worklog"}.get(low)
            continue
        if section == "summary":
            if line.strip():
                summary_lines.append(line.strip())
            continue
        if section != "worklog":
            continue
        m = HEADING_RE.match(line)
        if m:
            if current:
                blocks.append(current)
            linked = m.group("link")
            current = {"project": (linked or m.group("bold")).strip(),
                       "bold": linked is None, "bullets": []}
            continue
        if ANY_H3_RE.match(line):  # an H3 with no recognizable label ends the block
            if current:
                blocks.append(current)
                current = None
            continue
        if current is not None and (b := BULLET_RE.match(line)):
            current["bullets"].append(b.group(1).strip())

    if current:
        blocks.append(current)
    return " ".join(summary_lines).strip(), blocks
