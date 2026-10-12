#!/usr/bin/env python3
"""Pulse weekly synthesizer (L4): the one script the synth skill calls.

Subcommands (run `synth.py <cmd> -h` for each):
  collect     resolve a Mon..Sun week, list the daily notes in it, print JSON
  buckets     group the week's Work-log bullets by project, print JSON
  week-links  wire the weekly note into its month hub + weekly index (idempotent)
  lint        gate: required sections present, no em dash in body
  coverage    gate: every project that appeared in the week is named in the note

Stdlib only. No LLM (the writing step lives in skills/synth/SKILL.md). The
synthesizer reads the daily notes the digest already wrote; it never touches
Convex. Config comes from ~/.pulse/config.yaml (env vars win). A project links
as [[Project]] only when its note exists in projects_dir, else plain **bold**
(no dead links), the same existence rule the digest uses.
"""
import argparse
import json
import os
import re
import sys
from datetime import date, datetime, timedelta, timezone

MONTHS = ["January", "February", "March", "April", "May", "June", "July",
          "August", "September", "October", "November", "December"]
MON_ABBR = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep",
            "Oct", "Nov", "Dec"]

DASH_RE = re.compile(r"[—–]")
FENCE_RE = re.compile(r"```.*?```", re.S)
CODE_RE = re.compile(r"`[^`\n]*`")
# Work-log headings the digest writes: `### [[Project]]` or `### **Project**`.
HEADING_RE = re.compile(
    r"^###\s+(?:\[\[(?P<link>[^\]#|]+)(?:[#|][^\]]*)?\]\]|\*\*(?P<bold>[^*]+)\*\*)")
ANY_H3_RE = re.compile(r"^###\s")
H2_RE = re.compile(r"^##\s")
BULLET_RE = re.compile(r"^\s*-\s+(.*)$")


def strip_code(text: str) -> str:
    return CODE_RE.sub("", FENCE_RE.sub("", text))


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


def cfg_get(cfg: dict, key: str, env: str | None, default: str) -> str:
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
            pass
    return timezone.utc


# --- linking rule (existence-based, same as the digest) ---------------------

def render_label(label: str, projects_dir: str | None) -> str:
    if projects_dir and os.path.isfile(
            os.path.join(os.path.expanduser(projects_dir), f"{label}.md")):
        return f"[[{label}]]"
    return f"**{label}**"


# --- collect (subcommand) ---------------------------------------------------

def resolve_week_end(arg: str | None, tz) -> date:
    """Sunday of the most recently completed calendar week, or the given date."""
    if arg:
        try:
            return datetime.strptime(arg, "%Y-%m-%d").date()
        except ValueError:
            print(f"ERROR: --week-end must be YYYY-MM-DD, got {arg!r}", file=sys.stderr)
            sys.exit(1)
    today = datetime.now(tz).date()
    # weekday(): Monday=0 .. Sunday=6. Days back to the most recent Sunday.
    return today - timedelta(days=(today.weekday() - 6) % 7)


def cmd_collect(args) -> int:
    cfg = read_config(os.path.join(pulse_home(), "config.yaml"))
    tz = get_tz(cfg)
    week_end = resolve_week_end(args.week_end, tz)
    week_start = week_end - timedelta(days=6)

    notes_repo = os.path.expanduser(cfg_get(cfg, "notes_repo", "NOTES_REPO", ""))
    vault_subfolder = cfg_get(cfg, "vault_subfolder", "PULSE_VAULT_SUBFOLDER", "Pulse/Daily")
    projects_subfolder = cfg_get(cfg, "projects_subfolder", "PULSE_PROJECTS_SUBFOLDER", "Pulse/Projects")
    weekly_subfolder = cfg_get(cfg, "weekly_subfolder", "PULSE_WEEKLY_SUBFOLDER", "Pulse/Weekly")
    hub_prefix = cfg_get(cfg, "hub_prefix", "PULSE_HUB_PREFIX", "Pulse")
    weekly_hub_prefix = cfg_get(cfg, "weekly_hub_prefix", "PULSE_WEEKLY_HUB_PREFIX", f"{hub_prefix} Weekly")
    weekly_index = cfg_get(cfg, "weekly_index", "PULSE_WEEKLY_INDEX", f"{weekly_hub_prefix} Index.md")

    if not notes_repo:
        print(json.dumps({"error": "no notes_repo; run skills/setup/install.py notes",
                          "week_end": week_end.isoformat()}), file=sys.stderr)
        return 2

    daily_dir = os.path.join(notes_repo, vault_subfolder)
    notes = []
    d = week_start
    while d <= week_end:
        iso = d.isoformat()
        cand = os.path.join(daily_dir, iso[:7], f"{iso}.md")
        if os.path.isfile(cand):
            notes.append(os.path.relpath(cand, notes_repo))
        d += timedelta(days=1)

    ym = week_end.isoformat()[:7]
    weekly_note = os.path.join(notes_repo, weekly_subfolder, ym, f"{week_end.isoformat()}.md")
    out = {
        "week_start": week_start.isoformat(),
        "week_end": week_end.isoformat(),
        "timezone": cfg_get(cfg, "timezone", "PULSE_TZ", "UTC"),
        "notes_repo_dir": notes_repo,
        "vault_subfolder": vault_subfolder,
        "weekly_subfolder": weekly_subfolder,
        "projects_dir": os.path.join(notes_repo, projects_subfolder),
        "weekly_hub_prefix": weekly_hub_prefix,
        "weekly_index": weekly_index,
        "weekly_note_path": weekly_note,
        "note_count": len(notes),
        "notes": notes,
    }
    print(json.dumps(out, ensure_ascii=False))
    return 0


# --- buckets (subcommand) ---------------------------------------------------

def parse_note(text: str):
    """Return (summary, blocks). summary is the ## Summary text; blocks is a
    list of {project, bold, bullets} from the ## Work log section."""
    summary_lines: list[str] = []
    blocks: list[dict] = []
    current: dict | None = None
    section = None  # None | "summary" | "worklog"

    for raw in text.splitlines():
        line = raw.rstrip()
        low = line.strip().lower()
        if H2_RE.match(line):
            if current:
                blocks.append(current)
                current = None
            if low == "## summary":
                section = "summary"
            elif low == "## work log":
                section = "worklog"
            else:
                section = None
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
            bold = m.group("bold")
            current = {"project": (linked or bold).strip(),
                       "bold": linked is None, "bullets": []}
            continue
        if ANY_H3_RE.match(line):  # an H3 with no recognizable label ends the block
            if current:
                blocks.append(current)
                current = None
            continue
        if current is None:
            continue
        b = BULLET_RE.match(line)
        if b:
            current["bullets"].append(b.group(1).strip())

    if current:
        blocks.append(current)
    return " ".join(summary_lines).strip(), blocks


def cmd_buckets(args) -> int:
    with open(args.week_json, encoding="utf-8") as f:
        week = json.load(f)
    repo = week.get("notes_repo_dir", "")
    projects_dir = week.get("projects_dir") or args.projects_dir

    buckets: dict[str, dict] = {}
    daily_summaries = []
    scanned = 0
    for rel in week.get("notes", []):
        full = os.path.join(repo, rel) if repo else rel
        if not os.path.isfile(full):
            continue
        scanned += 1
        note_date = os.path.splitext(os.path.basename(rel))[0]
        summary, blocks = parse_note(open(full, encoding="utf-8").read())
        if summary:
            daily_summaries.append({"date": note_date, "summary": summary})
        for blk in blocks:
            label = blk["project"]
            bkt = buckets.setdefault(label, {
                "days": [], "bold": blk["bold"],
                "rendered": render_label(label, projects_dir), "entries": []})
            if note_date not in bkt["days"]:
                bkt["days"].append(note_date)
            bkt["entries"].append({"date": note_date, "bullets": blk["bullets"]})

    out = {
        "week_start": week.get("week_start"),
        "week_end": week.get("week_end"),
        "notes_scanned": scanned,
        "daily_summaries": daily_summaries,
        "buckets": buckets,
    }
    print(json.dumps(out, ensure_ascii=False))
    return 0


# --- week-links (subcommand) ------------------------------------------------

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


def cmd_week_links(args) -> int:
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
    d = datetime.strptime(args.date, "%Y-%m-%d")
    label = f"Week of {MON_ABBR[d.month - 1]} {d.day}"

    if not os.path.isfile(hub_path):
        os.makedirs(os.path.dirname(hub_path), exist_ok=True)
        open(hub_path, "w", encoding="utf-8").write(
            f"---\ntype: weekly-hub\nmonth: \"{ym}\"\ntags: [pulse, hub]\n---\n\n"
            f"# {args.hub_prefix} notes, {mname}\n\nPart of [[{index_stem}]].\n\n## Weeks\n")
        print(f"CREATED hub {hub_path}")
    week_link = f"- [[{sub}/{ym}/{args.date}|{label}]]"
    text, changed = _upsert_list(open(hub_path, encoding="utf-8").read(), "## Weeks", week_link)
    if changed:
        open(hub_path, "w", encoding="utf-8").write(text)
        print(f"LINKED {args.date} in {os.path.basename(hub_path)}")

    if not os.path.isfile(index_path):
        os.makedirs(os.path.dirname(index_path), exist_ok=True)
        open(index_path, "w", encoding="utf-8").write(
            f"---\ntype: index\ntags: [pulse, index]\n---\n\n# {args.hub_prefix} notes\n\n"
            f"Auto-maintained index of weekly note hubs.\n\n## Months\n")
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
            for sec in ("## What you worked on", "## Sources"):
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
    raw = open(args.buckets, encoding="utf-8").read() if args.buckets else sys.stdin.read()
    buckets = json.loads(raw).get("buckets", {})
    try:
        note = open(args.weekly_note, encoding="utf-8").read()
    except Exception as e:
        print(f"FAIL cannot read weekly note: {e}", file=sys.stderr)
        return 1
    ignore = set(args.ignore) if args.ignore else {"Misc"}
    # Word-boundary match so a label ("Auth") is not counted as present just
    # because a longer word ("Authentication") contains it. A label that is a
    # standalone word inside a longer phrase ("App" in "Web App") still counts.
    def named(label: str) -> bool:
        return re.search(rf"(?<!\w){re.escape(label)}(?!\w)", note) is not None
    missing = [label for label in buckets if label not in ignore and not named(label)]
    if missing:
        print(f"FAIL coverage: {len(missing)} project(s) that appeared this week are "
              f"not named in {args.weekly_note}", file=sys.stderr)
        for label in missing:
            print(f"  - {label}", file=sys.stderr)
        print("Do NOT push. Name every project in worked-on or skipped, then rerun.",
              file=sys.stderr)
        return 1
    print(f"OK coverage: all {len([l for l in buckets if l not in ignore])} "
          f"project(s) accounted for in {args.weekly_note}")
    return 0


# --- dispatch ---------------------------------------------------------------

def main() -> int:
    p = argparse.ArgumentParser(description="Pulse weekly synthesizer (L4).")
    sub = p.add_subparsers(dest="cmd", required=True)

    c = sub.add_parser("collect", help="resolve the week + list its daily notes")
    c.add_argument("--week-end", default=None)
    c.set_defaults(fn=cmd_collect)

    b = sub.add_parser("buckets", help="group the week's Work-log bullets by project")
    b.add_argument("week_json", help="path to JSON from `collect`")
    b.add_argument("--projects-dir", default=None)
    b.set_defaults(fn=cmd_buckets)

    wl = sub.add_parser("week-links", help="wire the weekly note into its hub + index")
    wl.add_argument("--vault", required=True)
    wl.add_argument("--subfolder", required=True)
    wl.add_argument("--date", required=True)
    wl.add_argument("--hub-prefix", required=True)
    wl.add_argument("--index", required=True)
    wl.set_defaults(fn=cmd_week_links)

    li = sub.add_parser("lint", help="gate: sections + no em dash")
    li.add_argument("notes", nargs="+")
    li.set_defaults(fn=cmd_lint)

    co = sub.add_parser("coverage", help="gate: every project named in the note")
    co.add_argument("--buckets", default=None)
    co.add_argument("--weekly-note", required=True)
    co.add_argument("--ignore", action="append", default=None)
    co.set_defaults(fn=cmd_coverage)

    args = p.parse_args()
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
