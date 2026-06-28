#!/usr/bin/env python3
"""Pulse digester (L3): the one script the digest skill calls.

Subcommands (run `digest.py <cmd> -h` for each):
  fetch         pull a day's rows from Convex, bucket by project, print JSON
  render-block  render one Work-log project heading + bullets (correct linking)
  month-links   wire the dated note into its month hub + folder index (idempotent)
  lint          gate: required sections present, no em dash in body
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


def strip_code(text: str) -> str:
    return CODE_RE.sub("", FENCE_RE.sub("", text))


# --- config + creds ---------------------------------------------------------

def pulse_home() -> str:
    return os.path.expanduser(os.environ.get("PULSE_HOME", "~/.pulse"))


def read_config(path: str) -> dict:
    cfg: dict = {}
    if not os.path.isfile(path):
        return cfg
    try:
        for line in open(path):
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
            for line in open(ENV_FILE):
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
            pass
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


def load_labels(path: str) -> dict:
    result = {"mappings": {}, "fallback": None, "path_patterns": []}
    if not path or not os.path.isfile(path):
        return result
    section, item = None, None
    try:
        for raw in open(path):
            line = raw.split("#", 1)[0].rstrip()
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
            elif section == "path_patterns":
                if s.startswith("- "):
                    item = {}
                    result["path_patterns"].append(item)
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


def canonical_project(event: dict, labels: dict) -> str:
    project, cwd = event.get("project") or "", event.get("cwd") or ""
    mappings = labels.get("mappings", {})
    if project and project in mappings:
        return mappings[project]
    if cwd:
        base = os.path.basename(cwd.rstrip("/"))
        if base in mappings:
            return mappings[base]
        for entry in labels.get("path_patterns", []):
            rx, label = entry.get("regex"), entry.get("label")
            if rx and label and re.search(rx, cwd):
                return label
    if project and project not in ("", "unknown"):
        return project
    return labels.get("fallback") or "Misc"


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
        "cwd": row.get("projectPath", "") or row.get("project_path", "") or "",
    }


def cmd_fetch(args) -> int:
    cfg = read_config(os.path.join(pulse_home(), "config.yaml"))
    tz = get_tz(cfg)
    date = resolve_date(args.date, tz)
    url, token = load_convex_env()
    if not url or not token:
        print(json.dumps({"error": "no CONVEX_URL/CONVEX_TOKEN; run skills/setup/install.py",
                          "date": date}), file=sys.stderr)
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

    events = [e for e in (normalize(r) for r in rows) if not is_noise(e["prompt"])]
    events.sort(key=lambda e: (e.get("ts", 0), e.get("timestamp", "")))
    grouped: dict[str, list] = {}
    for e in events:
        grouped.setdefault(canonical_project(e, labels), []).append(
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
        open(hub_path, "w", encoding="utf-8").write(
            f"---\ntype: month-hub\nmonth: \"{ym}\"\ntags: [pulse, hub]\n---\n\n"
            f"# {args.hub_prefix} notes, {mname}\n\nPart of [[{index_stem}]].\n\n## Days\n")
        print(f"CREATED hub {hub_path}")
    d = datetime.strptime(args.date, "%Y-%m-%d")
    day_link = f"- [[{sub}/{ym}/{args.date}|{d.strftime('%b')} {d.day}]]"
    text, changed = _upsert_list(open(hub_path, encoding="utf-8").read(), "## Days", day_link)
    if changed:
        open(hub_path, "w", encoding="utf-8").write(text)
        print(f"LINKED {args.date} in {os.path.basename(hub_path)}")

    if not os.path.isfile(index_path):
        os.makedirs(os.path.dirname(index_path), exist_ok=True)
        open(index_path, "w", encoding="utf-8").write(
            f"---\ntype: index\ntags: [pulse, index]\n---\n\n# {args.hub_prefix} notes\n\n"
            f"Auto-maintained index of monthly note hubs.\n\n## Months\n")
        print(f"CREATED index {index_path}")
    text, changed = _upsert_list(open(index_path, encoding="utf-8").read(),
                                 "## Months", f"- [[{hub_name}|{mname}]]", reverse=True)
    if changed:
        open(index_path, "w", encoding="utf-8").write(text)
        print(f"LINKED {hub_name} in {os.path.basename(index_path)}")
    print("OK")
    return 0


# --- lint (subcommand) ------------------------------------------------------

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
            for sec in ("## Summary", "## Work log"):
                if sec not in raw:
                    problems.append(f"missing section: {sec}")
            for i, line in enumerate(raw.splitlines(), 1):
                if DASH_RE.search(strip_code(line)):
                    problems.append(f"line {i}: em/en dash in body")
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
                rel = os.path.relpath(os.path.join(dirpath, fn), vault)
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
    p = argparse.ArgumentParser(description="Pulse digester (L3).")
    sub = p.add_subparsers(dest="cmd", required=True)

    f = sub.add_parser("fetch", help="fetch a day's rows from Convex -> JSON")
    f.add_argument("--date", default="yesterday")
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

    li = sub.add_parser("lint", help="gate: sections + no em dash")
    li.add_argument("notes", nargs="+")
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
