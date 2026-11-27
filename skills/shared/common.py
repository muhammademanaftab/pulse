"""Shared helpers for the Pulse skill scripts (digest, projects, synth, posts, recall).

Config, timezone, the existence-based linking rule, reading daily notes, and
the month hub + index wiring. Stdlib only. Each skill script adds this folder to sys.path and imports
what it needs.
"""
from __future__ import annotations

import json
import os
import re
import sys
from datetime import date, datetime, timedelta, timezone
from urllib.request import Request

MONTHS = ["January", "February", "March", "April", "May", "June", "July",
          "August", "September", "October", "November", "December"]

DASH_RE = re.compile(r"[—–]")
FENCE_RE = re.compile(r"```.*?```", re.S)
CODE_RE = re.compile(r"`[^`\n]*`")
MONTH_DIR_RE = re.compile(r"^\d{4}-\d{2}$")
UNSAFE_LABEL_RE = re.compile(r'[\\/:*?"<>|#^\[\]]')
DATE_FILE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}\.md$")
BANNED_WORDS = ["non-trivial", "leveraging", "baked into", "kicked off", "blast radius",
                "key finding", "non-negotiable", "iteratively", "front-of-mind",
                "underweighted", "pushed through", "delve", "seamlessly"]
BANNED_RE = re.compile(r"\b(?:" + "|".join(re.escape(w) for w in BANNED_WORDS) + r")\b", re.I)

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
    for stream in (sys.stdin, sys.stdout):
        stream.reconfigure(encoding="utf-8")


def pulse_home() -> str:
    return os.path.expanduser(os.environ.get("PULSE_HOME", "~/.pulse"))


def read_config(path: str) -> dict:
    cfg: dict = {}
    if not os.path.isfile(path):
        return cfg
    try:
        for line in open(path, encoding="utf-8"):
            if line.lstrip().startswith("#") or ":" not in line:
                continue
            k, v = line.split(":", 1)
            k, v = k.strip(), v.strip()
            if v[:1] in ("\"", "'") and v.find(v[0], 1) > 0:
                v = v[1:v.find(v[0], 1)]
            else:
                v = re.split(r"(?:^|\s)#", v, 1)[0].strip()
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


def notes_repo_dir(cfg: dict) -> str:
    """Absolute path of the notes repo, or "" when none is configured."""
    repo = cfg_get(cfg, "notes_repo", "NOTES_REPO", "")
    return os.path.abspath(os.path.expanduser(repo)) if repo else ""


def get_tz(cfg: dict):
    name = cfg_get(cfg, "timezone", "PULSE_TZ", "UTC")
    if name and name != "UTC":
        try:
            from zoneinfo import ZoneInfo
            return ZoneInfo(name)
        except Exception:
            print(f"warning: unknown timezone {name!r}, using UTC "
                  "(on Windows: pip install tzdata)", file=sys.stderr)
    return timezone.utc


def resolve_week_end(arg: str | None, tz) -> date:
    """Sunday of the most recently completed calendar week, or the given date."""
    if arg:
        try:
            day = datetime.strptime(arg, "%Y-%m-%d").date()
        except ValueError:
            print(f"ERROR: --week-end must be YYYY-MM-DD, got {arg!r}", file=sys.stderr)
            sys.exit(1)
        if day.weekday() != 6:
            sunday = day + timedelta(days=6 - day.weekday())
            print(f"ERROR: --week-end must be a Sunday; {arg} is not. "
                  f"The week containing it ends {sunday.isoformat()}.", file=sys.stderr)
            sys.exit(1)
        return day
    today = datetime.now(tz).date()
    return today - timedelta(days=today.weekday() + 1)


def render_label(label: str, projects_dir: str | None) -> str:
    """Wikilink iff the project note exists, else bold. No dead links possible."""
    if projects_dir and os.path.isfile(
            os.path.join(os.path.expanduser(projects_dir), f"{label}.md")):
        return f"[[{label}]]"
    return f"**{label}**"


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
    try:
        d = datetime.strptime(args.date, "%Y-%m-%d")
    except ValueError:
        print(f"ERROR: --date is not a real date: {args.date!r}", file=sys.stderr)
        return 1
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
    link = f"- [[{sub}/{ym}/{args.date}|{'Week ending ' + day if per_week else day}]]"
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
    section = None

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
        if ANY_H3_RE.match(line):
            if current:
                blocks.append(current)
                current = None
            continue
        if current is not None and (b := BULLET_RE.match(line)):
            current["bullets"].append(b.group(1).strip())

    if current:
        blocks.append(current)
    return " ".join(summary_lines).strip(), blocks


def _unq(s: str) -> str:
    return s[1:-1] if len(s) >= 2 and s[0] == s[-1] and s[0] in "\"'" else s


def strip_comment(line: str) -> str:
    quote = None
    for i, ch in enumerate(line):
        if quote:
            quote = None if ch == quote else quote
        elif ch in "\"'" and line[:i].rstrip()[-1:] in ("", ":", "-"):
            quote = ch
        elif ch == "#" and (i == 0 or line[i - 1] in " \t"):
            return line[:i]
    return line


def load_labels(path: str) -> dict:
    result = {"mappings": {}, "fallback": None, "path_patterns": [], "noise_patterns": []}
    if not path or not os.path.isfile(path):
        return result
    section, item = None, None
    try:
        for raw in open(path, encoding="utf-8"):
            line = strip_comment(raw.rstrip("\n")).rstrip()
            if not line.strip():
                continue
            indent = len(line) - len(line.lstrip())
            s = line.strip()
            if indent == 0 and s.endswith(":"):
                section, item = s[:-1], None
            elif indent == 0 and ":" in s:
                k, _, v = s.partition(":")
                if k.strip() == "fallback":
                    result["fallback"] = _unq(v.strip())
                section = None
            elif section == "mappings" and ":" in s:
                k, _, v = s.partition(":")
                result["mappings"][_unq(k.strip())] = _unq(v.strip())
            elif section in ("path_patterns", "noise_patterns"):
                if s.startswith("- "):
                    item = {}
                    result[section].append(item)
                    rest = s[2:].strip()
                    if ":" in rest:
                        k, _, v = rest.partition(":")
                        item[k.strip()] = _unq(v.strip())
                elif item is not None and ":" in s:
                    k, _, v = s.partition(":")
                    item[k.strip()] = _unq(v.strip())
    except Exception:
        pass
    return result


def rx_search(rx: str, text: str) -> bool:
    try:
        return re.search(rx, text) is not None
    except re.error as e:
        print(f"warning: bad regex {rx!r} in project labels: {e}", file=sys.stderr)
        return False


def path_label(cwd: str, labels: dict) -> str | None:
    return next((p["label"] for p in labels.get("path_patterns", [])
                 if cwd and p.get("regex") and p.get("label") and rx_search(p["regex"], cwd)), None)


def load_convex_env() -> tuple[str | None, str | None]:
    url, token = os.environ.get("CONVEX_URL"), os.environ.get("CONVEX_TOKEN")
    if url and token:
        return url, token
    env_file = os.path.join(pulse_home(), ".env")
    if os.path.isfile(env_file):
        try:
            for line in open(env_file, encoding="utf-8"):
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                k, v = k.strip(), v.strip().strip('"').strip("'")
                if k == "CONVEX_URL" and not url:
                    url = v
                elif k == "CONVEX_TOKEN" and not token:
                    token = v
        except Exception:
            pass
    return url, token



def convex_creds() -> tuple[str | None, str | None, str | None]:
    """(url, token, error). error is set when the creds are missing or unsafe."""
    url, token = load_convex_env()
    if not url or not token:
        return None, None, "no CONVEX_URL/CONVEX_TOKEN; run skills/setup/install.py"
    if not url.startswith("https://"):
        return None, None, ("CONVEX_URL must start with https:// (refusing to send "
                            "the token over cleartext)")
    return url, token, None



def canonical_project(event: dict, labels: dict) -> str:
    project, cwd = event.get("project") or "", event.get("cwd") or ""
    mappings = labels.get("mappings", {})
    if project and project in mappings:
        return mappings[project]
    if cwd:
        base = os.path.basename(cwd.rstrip("/"))
        if base in mappings:
            return mappings[base]
        if (hit := path_label(cwd, labels)):
            return hit
    if project and project not in ("", "unknown"):
        return project
    return labels.get("fallback") or "Misc"



def is_noise_folder(event: dict, labels: dict) -> bool:
    folder = os.path.basename((event.get("cwd") or "").rstrip("/"))
    raw = event.get("project") or folder
    if raw in labels.get("mappings", {}) or folder in labels.get("mappings", {}):
        return False
    return bool(raw) and any(
        e.get("regex") and rx_search(e["regex"], raw) for e in labels.get("noise_patterns", []))



def clean_label(label: str) -> str:
    """A label becomes a heading, a link and a file name, so drop what breaks those."""
    return re.sub(r"\s+", " ", UNSAFE_LABEL_RE.sub(" ", label)).strip(" .") or "Misc"



def resolve_labels(events: list[dict], labels: dict) -> list[str]:
    """A scratch-folder event takes a path_patterns hit on its full path, else the
    label of the nearest-in-time real event in its session, else the fallback."""
    fallback = labels.get("fallback") or "Misc"
    real: dict[int, str] = {}
    by_session: dict[str, list] = {}
    for i, e in enumerate(events):
        if is_noise_folder(e, labels):
            continue
        real[i] = lab = canonical_project(e, labels)
        if e.get("session") and lab != fallback:
            by_session.setdefault(e["session"], []).append((e.get("ts", 0), lab))
    out = []
    for i, e in enumerate(events):
        if i in real:
            out.append(real[i])
            continue
        near = by_session.get(e.get("session") or "")
        out.append(path_label(e.get("cwd") or "", labels)
                   or (min(near, key=lambda c: abs(c[0] - e.get("ts", 0)))[1] if near else fallback))
    return out



def is_install_probe(event: dict) -> bool:
    """The row skills/setup/install.py posts to verify the deployment."""
    return event["session"] == "install-verify" and event["project"] == "pulse-install"



def row_id(row: dict) -> str:
    return row.get("_id") or row.get("id") or ""



def normalize(row: dict) -> dict:
    return {
        "id": row_id(row),
        "ts": row.get("ts", 0),
        "timestamp": row.get("timestamp", ""),
        "prompt": row.get("message", "") or "",
        "response": row.get("response", "") or "",
        "project": row.get("project", "") or "",
        "cwd": (row.get("projectPath", "") or row.get("project_path", "") or "").replace("\\", "/"),
        "session": row.get("sessionId", "") or "",
    }



def fetch_convex_range(url, token, start_ms, end_ms, opener):
    endpoint = f"{url.rstrip('/')}/all?startTs={start_ms}&endTs={end_ms}"
    with opener(Request(endpoint, headers={"Authorization": f"Bearer {token}"}), timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))
