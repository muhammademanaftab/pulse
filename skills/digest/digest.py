#!/usr/bin/env python3
"""Pulse digester (L3): the one script the digest skill calls.

Subcommands (run `digest.py <cmd> -h` for each):
  fetch         pull a day's rows from Convex, bucket by project, print JSON
  render-block  render one Work-log project heading + bullets (correct linking)
  month-links   wire the dated note into its month hub + folder index (idempotent)
  open-loops    list the previous note's open items to carry into this one
  lint          gate: note layout, typed bullets, open loops carried, no em dash
  coverage      gate: every digest bucket has a block in the note
  check-links   gate: no dead [[links]] and no orphan notes

Stdlib only. No LLM (the writing step lives in skills/digest/SKILL.md). Config
comes from ~/.pulse/config.yaml (env vars win); Convex creds from ~/.pulse/.env.
The daily note is regenerate-and-overwrite, so a project links as [[Project]]
only when its note exists in projects_dir, else plain **bold** (no dead links).
"""
import argparse
import json
import os
import re
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from urllib.request import Request, urlopen

ENV_FILE = os.path.expanduser("~/.pulse/.env")
TRIVIAL_PROMPTS = {
    "hi", "hello", "hey", "yo", "thanks", "thank you", "ty", "ok", "okay", "k",
    "yes", "no", "yep", "yup", "nope", "sure", "cool", "nice", "great", "go",
    "go ahead", "continue", "next", "done", "good", "perfect",
}
MONTHS = ["January", "February", "March", "April", "May", "June", "July",
          "August", "September", "October", "November", "December"]

DASH_RE = re.compile(r"[—–]")
LINK_RE = re.compile(r"\[\[([^\]\|#]+)")
FENCE_RE = re.compile(r"```.*?```", re.S)
CODE_RE = re.compile(r"`[^`\n]*`")
SKIP_DIRS = {".git", ".obsidian", "node_modules", "__pycache__", ".trash"}

SECTIONS = ["## Summary", "## Work log", "## Open loops"]
BLOCK_HEADING_RE = re.compile(
    r"^###\s+(?:\[\[(?P<link>[^\]#|]+)(?:[#|][^\]]*)?\]\]|\*\*(?P<bold>[^*]+)\*\*)\s*$")
TASK_RE = re.compile(r"^- \[( |x|X)\] (.+)$")
LOOP_TAG_RE = re.compile(
    r"\s*\((?P<project>(?:[^()]|\([^()]*\))*?),\s*since (?P<since>[A-Z][a-z]{2} \d{1,2})[^()]*\)\s*$")
MONTH_DIR_RE = re.compile(r"^\d{4}-\d{2}$")
PREFIX_RE = re.compile(r"^- (\*\*)?(outcome|decided|bug|rule|learned|open|refs)(\*\*)?:", re.I)
CLOSED_RE = re.compile(r",\s*(?:done [A-Z][a-z]{2} \d{1,2}|dropped [A-Z][a-z]{2} \d{1,2}:)")
DATE_FILE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}\.md$")
BANNED_WORDS = ["non-trivial", "leveraging", "baked into", "kicked off", "blast radius",
                "key finding", "non-negotiable", "iteratively", "front-of-mind",
                "underweighted", "pushed through", "delve", "seamlessly"]
BANNED_RE = re.compile(r"\b(?:" + "|".join(re.escape(w) for w in BANNED_WORDS) + r")\b", re.I)


def strip_code(text: str) -> str:
    return CODE_RE.sub("", FENCE_RE.sub("", text))


def strip_code_blocks(text: str) -> str:
    return FENCE_RE.sub(lambda m: "\n" * m.group(0).count("\n"), text)


# --- config + creds ---------------------------------------------------------

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


def cfg_get(cfg: dict, key: str, env: str | None, default: str) -> str:
    if env and os.environ.get(env):
        return os.environ[env]
    return cfg.get(key, default)


def load_convex_env() -> tuple[str | None, str | None]:
    url, token = os.environ.get("CONVEX_URL"), os.environ.get("CONVEX_TOKEN")
    if url and token:
        return url, token
    if os.path.isfile(ENV_FILE):
        try:
            for line in open(ENV_FILE, encoding="utf-8"):
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


# --- label map (optional) ---------------------------------------------------

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


# --- fetch (subcommand) -----------------------------------------------------

def resolve_date(arg: str | None, tz) -> str:
    now = datetime.now(tz)
    if not arg or arg == "yesterday":
        return (now - timedelta(days=1)).strftime("%Y-%m-%d")
    if arg == "today":
        return now.strftime("%Y-%m-%d")
    datetime.strptime(arg, "%Y-%m-%d")
    return arg


def is_noise(prompt: str) -> bool:
    s = (prompt or "").strip().lower().rstrip("!.?")
    return s == "" or s in TRIVIAL_PROMPTS


def normalize(row: dict) -> dict:
    return {
        "id": row.get("_id") or row.get("id") or "",
        "ts": row.get("ts", 0),
        "timestamp": row.get("timestamp", ""),
        "prompt": row.get("message", "") or "",
        "response": row.get("response", "") or "",
        "project": row.get("project", "") or "",
        "cwd": (row.get("projectPath", "") or row.get("project_path", "") or "").replace("\\", "/"),
        "session": row.get("sessionId", "") or "",
    }


def defer_today(date: str, now: datetime, include_today: bool) -> bool:
    """Before noon the day has barely started; leave its rows for the next run."""
    return not include_today and date == now.strftime("%Y-%m-%d") and now.hour < 12


def cmd_fetch(args) -> int:
    cfg = read_config(os.path.join(pulse_home(), "config.yaml"))
    tz = get_tz(cfg)
    date = resolve_date(args.date, tz)
    url, token = load_convex_env()
    if not url or not token:
        print(json.dumps({"error": "no CONVEX_URL/CONVEX_TOKEN; run skills/setup/install.py",
                          "date": date}), file=sys.stderr)
        return 2
    if not url.startswith("https://"):
        print(json.dumps({"error": "CONVEX_URL must start with https:// (refusing to send "
                          "the token over cleartext)", "date": date}), file=sys.stderr)
        return 2

    start = datetime.strptime(date, "%Y-%m-%d").replace(tzinfo=tz)
    start_ms, end_ms = int(start.timestamp() * 1000), int((start + timedelta(days=1)).timestamp() * 1000)
    endpoint = f"{url.rstrip('/')}/unprocessed?startTs={start_ms}&endTs={end_ms}"
    try:
        with urlopen(Request(endpoint, headers={"Authorization": f"Bearer {token}"}), timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        print(json.dumps({"error": f"fetch failed: {e}", "date": date}), file=sys.stderr)
        return 1
    rows = data.get("rows", []) if isinstance(data, dict) else (data if isinstance(data, list) else [])

    labels = load_labels(os.path.expanduser(
        cfg_get(cfg, "project_labels", None, os.path.join(pulse_home(), "project-labels.yaml"))))
    notes_repo = os.path.expanduser(cfg_get(cfg, "notes_repo", "NOTES_REPO", ""))
    vault_subfolder = cfg_get(cfg, "vault_subfolder", "PULSE_VAULT_SUBFOLDER", "Pulse/Daily")
    projects_subfolder = cfg_get(cfg, "projects_subfolder", "PULSE_PROJECTS_SUBFOLDER", "Pulse/Projects")
    hub_prefix = cfg_get(cfg, "hub_prefix", "PULSE_HUB_PREFIX", "Pulse")
    index_name = cfg_get(cfg, "index_name", "PULSE_INDEX", f"{hub_prefix} Index.md")

    deferred = defer_today(date, datetime.now(tz), args.include_today)
    if deferred:
        rows = []
    events = [e for e in (normalize(r) for r in rows) if not is_noise(e["prompt"])]
    events.sort(key=lambda e: (e.get("ts", 0), e.get("timestamp", "")))
    grouped: dict[str, list] = {}
    for e, label in zip(events, resolve_labels(events, labels)):
        grouped.setdefault(label, []).append(
            {"ts": e["ts"], "timestamp": e["timestamp"], "prompt": e["prompt"],
             "response": e["response"], "id": e["id"]})

    note_dir = os.path.join(notes_repo, vault_subfolder, date[:7]) if notes_repo else ""
    out = {
        "date": date,
        "timezone": cfg_get(cfg, "timezone", "PULSE_TZ", "UTC"),
        "notes_repo_dir": notes_repo,
        "vault_subfolder": vault_subfolder,
        "projects_dir": os.path.join(notes_repo, projects_subfolder) if notes_repo else "",
        "hub_prefix": hub_prefix,
        "index_name": index_name,
        "note_path": os.path.join(note_dir, f"{date}.md") if notes_repo else "",
        "event_count": len(events),
        "deferred_today": deferred,
        "project_count": len(grouped),
        "buckets": [{"project": p, "events": evs} for p, evs in grouped.items()],
        # All fetched rows get marked processed after a verified push, including
        # noise we filtered, so trivial rows do not pile up unprocessed forever.
        "row_ids": [r.get("_id") or r.get("id") for r in rows if (r.get("_id") or r.get("id"))],
    }
    print(json.dumps(out, ensure_ascii=False))
    return 0


# --- render-block (subcommand) ----------------------------------------------

def cmd_render_block(args) -> int:
    bullets = (open(args.bullets_file, encoding="utf-8").read() if args.bullets_file
               else sys.stdin.read()).strip("\n")
    print(f"### {render_label(args.project, args.projects_dir)}")
    print()
    if bullets.strip():
        print(bullets)
    print()
    return 0


# --- month-links (subcommand) -----------------------------------------------

def _upsert_list(text: str, heading: str, new_line: str, reverse: bool = False):
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


def cmd_month_links(args) -> int:
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", args.date):
        print(f"ERROR: --date must be YYYY-MM-DD, got {args.date!r}", file=sys.stderr)
        return 1
    vault = os.path.abspath(os.path.expanduser(args.vault))
    ym = args.date[:7]
    y, m = ym.split("-")
    mname = f"{MONTHS[int(m) - 1]} {y}"
    sub = args.subfolder.strip("/")
    hub_name = f"{args.hub_prefix} {ym}"
    hub_path = os.path.join(vault, sub, ym, f"{hub_name}.md")
    index_path = os.path.join(vault, sub, args.index)
    index_stem = os.path.splitext(args.index)[0]

    if not os.path.isfile(hub_path):
        os.makedirs(os.path.dirname(hub_path), exist_ok=True)
        open(hub_path, "w", encoding="utf-8", newline="\n").write(
            f"---\ntype: month-hub\nmonth: \"{ym}\"\ntags: [pulse, hub]\n---\n\n"
            f"# {args.hub_prefix} notes, {mname}\n\nPart of [[{index_stem}]].\n\n## Days\n")
        print(f"CREATED hub {hub_path}")
    d = datetime.strptime(args.date, "%Y-%m-%d")
    day_link = f"- [[{sub}/{ym}/{args.date}|{d.strftime('%b')} {d.day}]]"
    text, changed = _upsert_list(open(hub_path, encoding="utf-8").read(), "## Days", day_link)
    if changed:
        open(hub_path, "w", encoding="utf-8", newline="\n").write(text)
        print(f"LINKED {args.date} in {os.path.basename(hub_path)}")

    if not os.path.isfile(index_path):
        os.makedirs(os.path.dirname(index_path), exist_ok=True)
        open(index_path, "w", encoding="utf-8", newline="\n").write(
            f"---\ntype: index\ntags: [pulse, index]\n---\n\n# {args.hub_prefix} notes\n\n"
            f"Auto-maintained index of monthly note hubs.\n\n## Months\n")
        print(f"CREATED index {index_path}")
    text, changed = _upsert_list(open(index_path, encoding="utf-8").read(),
                                 "## Months", f"- [[{hub_name}|{mname}]]", reverse=True)
    if changed:
        open(index_path, "w", encoding="utf-8", newline="\n").write(text)
        print(f"LINKED {hub_name} in {os.path.basename(index_path)}")
    print("OK")
    return 0


# --- note structure (shared by open-loops and lint) -------------------------

def h2_body(text: str, heading: str) -> str | None:
    m = re.search(rf"^{re.escape(heading)}[ \t]*\n(.*?)(?=^## |\Z)", text, re.M | re.S)
    return m.group(1) if m else None


def loop_text(line: str) -> str:
    m = TASK_RE.match(line)
    return LOOP_TAG_RE.sub("", m.group(2) if m else line).strip()


def loop_items(body: str) -> dict[str, str]:
    return {loop_text(ln): TASK_RE.match(ln).group(1).lower()
            for ln in body.splitlines() if TASK_RE.match(ln)}


def note_date(path: str) -> str | None:
    stem = os.path.splitext(os.path.basename(path))[0]
    return stem if DATE_FILE_RE.match(stem + ".md") else None


def previous_note(path: str) -> str | None:
    date = note_date(path)
    root = os.path.dirname(os.path.dirname(os.path.abspath(path)))
    if not date or not os.path.isdir(root):
        return None
    earlier = []
    for month in os.listdir(root):
        mdir = os.path.join(root, month)
        if MONTH_DIR_RE.match(month) and os.path.isdir(mdir):
            earlier += [os.path.join(mdir, f) for f in os.listdir(mdir)
                        if DATE_FILE_RE.match(f) and f[:-3] < date]
    return max(earlier, key=os.path.basename) if earlier else None


def read_note(path: str) -> str:
    return open(path, encoding="utf-8", errors="replace").read()


def since_age(since: str, date: str) -> int | None:
    """Tags carry no year: take the latest matching date on or before the note
    (up to 3 years back, so Feb 29 finds a leap year)."""
    nd = datetime.strptime(date, "%Y-%m-%d")
    for year in range(nd.year, nd.year - 4, -1):
        try:
            d = datetime.strptime(f"{since} {year}", "%b %d %Y")
        except ValueError:
            continue
        if d <= nd:
            return (nd - d).days
    return None


# --- open-loops (subcommand) ------------------------------------------------

def cmd_open_loops(args) -> int:
    date = note_date(args.note)
    if not date:
        print(f"ERROR: --note must be a dated note (YYYY-MM-DD.md), got {args.note!r}", file=sys.stderr)
        return 1
    prev = previous_note(args.note)
    out = {"previous_note": prev, "carry": [], "legacy_next": [], "closed_in_existing": []}
    if prev:
        text = read_note(prev)
        loops = h2_body(text, "## Open loops")
        if loops is None:
            out["legacy_next"] = [ln[2:].strip() for ln in (h2_body(text, "## Next") or "").splitlines()
                                  if ln.startswith("- ")]
        for ln in (loops or "").splitlines():
            t = TASK_RE.match(ln)
            if t and t.group(1) == " ":
                tag = LOOP_TAG_RE.search(ln)
                out["carry"].append({
                    "text": loop_text(ln),
                    "project": tag.group("project").strip() if tag else None,
                    "since": tag.group("since") if tag else None,
                    "age_days": since_age(tag.group("since"), date) if tag else None})
    if os.path.isfile(args.note):
        loops = h2_body(read_note(args.note), "## Open loops") or ""
        out["closed_in_existing"] = [ln for ln in loops.splitlines()
                                     if (t := TASK_RE.match(ln)) and t.group(1) != " "]
    print(json.dumps(out, ensure_ascii=False))
    return 0


# --- lint (subcommand) ------------------------------------------------------

def lint_structure(text: str, path: str, closed: list[str] = ()) -> list[str]:
    """See skills/digest/references/note-structure.md."""
    problems = []
    text = strip_code_blocks(text.lstrip())
    h2s = [m.group(1).rstrip() for m in re.finditer(r"^(## .*)$", text, re.M)]
    for s in SECTIONS:
        if s not in h2s:
            problems.append(f"missing section: {s}")
    extra = [h for h in h2s if h not in SECTIONS]
    if extra:
        problems.append(f"unexpected sections {extra} (only Summary, Work log, Open loops)")
    elif [h for h in h2s if h in SECTIONS] != SECTIONS:
        problems.append("sections out of order or repeated (Summary, Work log, Open loops)")
    if not (h2_body(text, "## Summary") or "").strip():
        problems.append("## Summary is empty")

    fm = re.match(r"^---\n(.*?)\n---\n", text, re.S)
    fm_block = re.search(r"^projects:(.*?)(?=^\S|\Z)", fm.group(1) + "\n", re.M | re.S) if fm else None
    if not fm_block:
        problems.append("frontmatter has no `projects:` list")
    fm_projects = re.findall(r'"([^"]+)"', fm_block.group(1)) if fm_block else []

    work = h2_body(text, "## Work log") or ""
    loops = h2_body(text, "## Open loops") or ""
    present = loop_items(loops)
    open_loops = {t for t, state in present.items() if state == " "}
    prev = previous_note(path)
    prev_loops = h2_body(strip_code_blocks(read_note(prev)), "## Open loops") if prev else None
    carried = {t for t, state in loop_items(prev_loops or "").items() if state == " "}

    blocks: list[tuple[str, str, list[str]]] = []
    for line in work.splitlines():
        m = BLOCK_HEADING_RE.match(line)
        if m:
            label = (m.group("link") or m.group("bold")).strip()
            blocks.append((label, f"[[{label}]]" if m.group("link") else label, []))
        elif line.startswith("### "):
            problems.append(f"Work log heading is not `### [[Project]]` or `### **Project**`: {line!r}")
        elif not line.strip():
            continue
        elif not line.startswith("- ") or not blocks:
            problems.append(f"## Work log: every line in a block is one `- ` bullet "
                            f"(one bullet per line, no wrapping): {line.strip()[:60]!r}")
        else:
            blocks[-1][2].append(line)
    if fm_block and fm_projects != [b[1] for b in blocks]:
        problems.append(f"frontmatter `projects:` must list each block once, in order, as written "
                        f"in its heading: expected {[b[1] for b in blocks]}, got {fm_projects}")
    for label, _, lines in blocks:
        where = f"block {label!r}"
        if not lines or not lines[0].startswith("- Outcome: "):
            problems.append(f"{where}: first bullet must be `- Outcome: ...`")
        if sum(ln.startswith("- Outcome:") for ln in lines) > 1:
            problems.append(f"{where}: more than one `- Outcome:`")
        refs = [i for i, ln in enumerate(lines) if ln.startswith("- Refs:")]
        if refs and refs[-1] != len(lines) - 1:
            problems.append(f"{where}: `- Refs:` must be the last bullet")
        for ln in lines:
            if (p := PREFIX_RE.match(ln)) and p.group(0) != f"- {p.group(2).capitalize()}:":
                problems.append(f"{where}: write the prefix exactly as `- {p.group(2).capitalize()}:`: "
                                f"{ln[:70]!r}")
            if ln.startswith("- Decided:") and "Why:" not in ln:
                problems.append(f"{where}: Decided bullet has no `Why:`: {ln[:70]!r}")
            if ln.startswith("- Bug:") and not ("Cause:" in ln and "Fix:" in ln):
                problems.append(f"{where}: Bug bullet needs `Cause:` and `Fix:`: {ln[:70]!r}")
            if TASK_RE.match(ln):
                problems.append(f"{where}: use `- Open: ...` in the Work log; checkboxes live "
                                f"only in ## Open loops: {ln[:70]!r}")
            if ln.startswith("- Open:") and ln[len("- Open:"):].strip() in carried:
                problems.append(f"{where}: carried items stay in ## Open loops only, not as "
                                f"`- Open:`: {ln[:70]!r}")
            elif ln.startswith("- Open:") and ln[len("- Open:"):].strip() not in open_loops:
                problems.append(f"{where}: `- Open:` item is not an open `- [ ]` item in "
                                f"## Open loops (same text): {ln[:70]!r}")

    items = [ln for ln in loops.splitlines() if ln.strip()]
    if not items:
        problems.append("## Open loops is empty (write `- None.` if nothing is open)")
    for ln in items:
        if ln.strip() == "- None.":
            if len(items) > 1:
                problems.append("## Open loops has `- None.` next to real items")
        elif not (t := TASK_RE.match(ln)):
            problems.append(f"## Open loops line is not a `- [ ]` / `- [x]` item "
                            f"(one item per line, no indent): {ln[:70]!r}")
        elif not (tag := LOOP_TAG_RE.search(ln)):
            problems.append(f"## Open loops item has no `(Project, since Mon D)` tag: {ln[:70]!r}")
        elif t.group(1) != " " and not CLOSED_RE.search(tag.group(0)):
            problems.append(f"## Open loops closed item needs `done Mon D` or `dropped Mon D: reason` "
                            f"in its tag: {ln[:70]!r}")

    for item in sorted(carried - present.keys()):
        problems.append(f"open loop from {os.path.basename(prev)} is missing; carry it with "
                        f"its exact text (open, done, or dropped): {item[:70]!r}")
    for ln in closed:
        if present.get(loop_text(ln)) != "x":
            problems.append(f"item already closed in this note must stay closed: {ln[:70]!r}")
    return problems


def cmd_lint(args) -> int:
    failed = False
    for note in args.notes:
        problems = []
        try:
            raw = open(note, encoding="utf-8").read()
        except Exception as e:
            problems = [f"cannot read: {e}"]
        else:
            if not raw.lstrip().startswith("---"):
                problems.append("missing YAML frontmatter")
            if not (args.allow_legacy and h2_body(raw, "## Open loops") is None):
                closed = (json.load(open(args.loops_json, encoding="utf-8"))["closed_in_existing"]
                          if args.loops_json else [])
                problems += lint_structure(raw, note, closed)
            for i, line in enumerate(raw.splitlines(), 1):
                body = strip_code(line)
                if DASH_RE.search(body):
                    problems.append(f"line {i}: em/en dash in body")
                if (w := BANNED_RE.search(body)):
                    problems.append(f"line {i}: AI-tell phrase {w.group(0)!r} (see humanizer.md)")
        if problems:
            failed = True
            print(f"FAIL {note}", file=sys.stderr)
            for pr in problems:
                print(f"  - {pr}", file=sys.stderr)
        else:
            print(f"OK {note}")
    return 1 if failed else 0


# --- coverage (subcommand) --------------------------------------------------

def cmd_coverage(args) -> int:
    raw = open(args.digest_json, encoding="utf-8").read() if args.digest_json else sys.stdin.read()
    buckets = json.loads(raw).get("buckets", [])
    try:
        note = open(args.note, encoding="utf-8").read()
    except Exception as e:
        print(f"FAIL cannot read note: {e}", file=sys.stderr)
        return 1
    missing = [b["project"] for b in buckets
               if f"### {render_label(b['project'], args.projects_dir)}" not in note]
    if missing:
        print(f"FAIL coverage: {len(missing)} bucket(s) missing from {args.note}", file=sys.stderr)
        for mproj in missing:
            print(f"  - {mproj}", file=sys.stderr)
        return 1
    print(f"OK coverage: {len(buckets)} bucket(s) present in {args.note}")
    return 0


# --- check-links (subcommand) -----------------------------------------------

def cmd_check_links(args) -> int:
    vault = os.path.abspath(os.path.expanduser(args.vault))
    scan_root = os.path.join(vault, args.subfolder) if args.subfolder else vault
    files, stem_to_rel = [], {}
    for dirpath, dirnames, filenames in os.walk(scan_root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for fn in filenames:
            if fn.endswith(".md"):
                rel = os.path.relpath(os.path.join(dirpath, fn), vault).replace("\\", "/")
                files.append(rel)
                stem_to_rel.setdefault(os.path.splitext(fn)[0], rel)

    def resolve(target: str):
        t = target.replace("\\", "").strip()
        if os.path.isfile(os.path.join(vault, f"{t}.md")):
            return f"{t}.md"
        if os.path.isfile(os.path.join(vault, t)):
            return t
        return stem_to_rel.get(t)

    outgoing, incoming, dead = {}, defaultdict(int), []
    for rel in files:
        targets = {t.strip() for t in LINK_RE.findall(
            strip_code(open(os.path.join(vault, rel), encoding="utf-8", errors="ignore").read()))}
        outgoing[rel] = targets
        for t in targets:
            r = resolve(t)
            if r is not None:
                incoming[r] += 1
            else:
                dead.append((rel, t))
    orphans = [rel for rel in files
               if not any(resolve(t) for t in outgoing[rel]) and incoming.get(rel, 0) == 0]

    if dead or orphans:
        print(f"VAULT HEALTH FAIL: {len(dead)} dead links, {len(orphans)} orphans", file=sys.stderr)
        for src, t in sorted(dead):
            print(f"  DEAD LINK  [[{t}]]  in  {src}", file=sys.stderr)
        for o in sorted(orphans):
            print(f"  ORPHAN     {o}", file=sys.stderr)
        return 1
    print(f"VAULT HEALTH OK: {len(files)} notes, 0 dead links, 0 orphans")
    return 0


# --- dispatch ---------------------------------------------------------------

def main() -> int:
    # Piped stdio uses the console codepage on Windows; JSON and notes are UTF-8.
    for stream in (sys.stdin, sys.stdout):
        stream.reconfigure(encoding="utf-8")
    p = argparse.ArgumentParser(description="Pulse digester (L3).")
    sub = p.add_subparsers(dest="cmd", required=True)

    f = sub.add_parser("fetch", help="fetch a day's rows from Convex -> JSON")
    f.add_argument("--date", default="yesterday")
    f.add_argument("--include-today", action="store_true",
                   help="digest today even before noon (by default those rows wait)")
    f.set_defaults(fn=cmd_fetch)

    r = sub.add_parser("render-block", help="render one Work-log project block")
    r.add_argument("--project", required=True)
    r.add_argument("--bullets-file", default=None)
    r.add_argument("--projects-dir", default=None)
    r.set_defaults(fn=cmd_render_block)

    ml = sub.add_parser("month-links", help="wire the note into its month hub + index")
    ml.add_argument("--vault", required=True)
    ml.add_argument("--subfolder", required=True)
    ml.add_argument("--date", required=True)
    ml.add_argument("--hub-prefix", required=True)
    ml.add_argument("--index", required=True)
    ml.set_defaults(fn=cmd_month_links)

    ol = sub.add_parser("open-loops", help="open items to carry from the previous note")
    ol.add_argument("--note", required=True, help="the note being written (its note_path)")
    ol.set_defaults(fn=cmd_open_loops)

    li = sub.add_parser("lint", help="gate: layout, typed bullets, open loops, no em dash")
    li.add_argument("notes", nargs="+")
    li.add_argument("--loops-json", default=None,
                    help="open-loops output: items closed before regeneration must stay closed")
    li.add_argument("--allow-legacy", action="store_true",
                    help="only check frontmatter and dashes on notes written before Open loops")
    li.set_defaults(fn=cmd_lint)

    co = sub.add_parser("coverage", help="gate: every bucket present in the note")
    co.add_argument("--digest-json", default=None)
    co.add_argument("--note", required=True)
    co.add_argument("--projects-dir", default=None)
    co.set_defaults(fn=cmd_coverage)

    cl = sub.add_parser("check-links", help="gate: no dead links / orphans")
    cl.add_argument("--vault", required=True)
    cl.add_argument("--subfolder", default=None)
    cl.set_defaults(fn=cmd_check_links)

    args = p.parse_args()
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
