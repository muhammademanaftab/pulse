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
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import timedelta

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "shared"))
from common import (  # noqa: E402
    DASH_RE, cfg_get, get_tz, link_into_hubs, load_config, parse_note,
    render_label, resolve_week_end, strip_code, utf8_stdio)

LOOP_RE = re.compile(r"^- \[( |x|X)\] (.+?)\s*\([^()]*(?:\([^()]*\)[^()]*)*since [^()]*\)\s*$")


# --- collect (subcommand) ---------------------------------------------------

def cmd_collect(args) -> int:
    cfg = load_config()
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
            notes.append(os.path.relpath(cand, notes_repo).replace("\\", "/"))
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

def cmd_buckets(args) -> int:
    with open(args.week_json, encoding="utf-8") as f:
        week = json.load(f)
    repo = week.get("notes_repo_dir", "")
    projects_dir = week.get("projects_dir") or args.projects_dir

    buckets: dict[str, dict] = {}
    daily_summaries = []
    scanned = 0
    loop_state: dict[str, str] = {}
    for rel in week.get("notes", []):
        full = os.path.join(repo, rel) if repo else rel
        if not os.path.isfile(full):
            continue
        scanned += 1
        note_date = os.path.splitext(os.path.basename(rel))[0]
        text = open(full, encoding="utf-8").read()
        summary, blocks = parse_note(text)
        loops = re.search(r"^## Open loops[ \t]*\n(.*?)(?=^## |\Z)", text, re.M | re.S)
        for ln in (loops.group(1) if loops else "").splitlines():
            if (t := LOOP_RE.match(ln)):
                loop_state[t.group(2)] = ln
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
        "open_loops": list(loop_state.values()),
    }
    print(json.dumps(out, ensure_ascii=False))
    return 0


# --- week-links (subcommand) ------------------------------------------------

def cmd_week_links(args) -> int:
    return link_into_hubs(args, "weekly")


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
    utf8_stdio()
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
