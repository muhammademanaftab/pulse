#!/usr/bin/env python3
"""Pulse project pages: the one script the projects skill calls.

Subcommands (run `projects.py <cmd> -h` for each):
  sync   build or refresh one page per project from the daily notes, then turn
         that project's bold headings in the daily notes into [[links]]

Stdlib only. No LLM. A project page is derived from the daily notes and is
rewritten on every run, except its About paragraph (the text between the title
and the first section), which is kept as written. A page is created once a
project has shown up on --min-days days; a hand-written note with the same name
is never touched.
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "shared"))
from common import (  # noqa: E402
    LOOP_TAG_RE, MONTHS, TASK_RE, cfg_get, h2_body, list_dated_notes, load_config,
    loop_text, parse_note, read_note, strip_code_blocks, utf8_stdio)

ABOUT_TODO = "About: not written yet."
# Bullet prefix -> page section, in page order.
SECTIONS = [("Decided", "## Decisions"), ("Bug", "## Bugs"),
            ("Rule", "## Rules and lessons"), ("Learned", "## Rules and lessons")]
UNSAFE_NAME_RE = re.compile(r'[\\/:*?"<>|#^\[\]]')
ABOUT_RE = re.compile(r"^# [^\n]*\n(.*?)(?=^## |\Z)", re.M | re.S)


def pretty(date: str) -> str:
    d = datetime.strptime(date, "%Y-%m-%d")
    return f"{MONTHS[d.month - 1][:3]} {d.day}, {d.year}"


def collect(daily_dir: str, vault: str, ignore: set[str]) -> dict[str, dict]:
    """label -> {days: [(date, vault-relative link target)], items: {section: [lines]},
    open: [lines]}, read from every daily note, oldest first."""
    projects: dict[str, dict] = {}
    notes = list_dated_notes(daily_dir)
    for path in notes:
        date = os.path.splitext(os.path.basename(path))[0]
        target = os.path.splitext(os.path.relpath(path, vault))[0].replace("\\", "/")
        _, blocks = parse_note(strip_code_blocks(read_note(path)))
        for blk in blocks:
            label = blk["project"]
            if label in ignore or UNSAFE_NAME_RE.search(label):
                continue
            proj = projects.setdefault(label, {"days": [], "items": {}, "open": []})
            if (date, target) not in proj["days"]:
                proj["days"].append((date, target))
            for bullet in blk["bullets"]:
                for prefix, section in SECTIONS:
                    if bullet.startswith(prefix + ": "):
                        text = bullet[len(prefix) + 2:].strip()
                        line = (f"- {pretty(date)}: {text}" if section != "## Rules and lessons"
                                else f"- {prefix}: {text} ({pretty(date)})")
                        proj["items"].setdefault(section, []).append(line)
    if notes:  # the newest note's Open loops is the current ledger
        loops = h2_body(strip_code_blocks(read_note(notes[-1])), "## Open loops") or ""
        for ln in loops.splitlines():
            t, tag = TASK_RE.match(ln), LOOP_TAG_RE.search(ln)
            if t and t.group(1) == " " and tag and tag.group("project").strip() in projects:
                projects[tag.group("project").strip()]["open"].append(
                    f"- {loop_text(ln)} (since {tag.group('since')})")
    return projects


def render_page(label: str, proj: dict, about: str) -> str:
    days = sorted(proj["days"], reverse=True)
    out = ["---", "type: project", "tags: [pulse, project]",
           f'first_day: "{days[-1][0]}"', f'last_day: "{days[0][0]}"',
           f"days_worked: {len(days)}", "---", "", f"# {label}", "", about, "",
           "## Open", "", *(proj["open"] or ["- None."]), ""]
    for section in dict.fromkeys(s for _, s in SECTIONS):
        if proj["items"].get(section):
            out += [section, "", *reversed(proj["items"][section]), ""]
    out += ["## Days worked", "", *(f"- [[{target}|{pretty(date)}]]" for date, target in days)]
    return "\n".join(out) + "\n"


def relink(path: str, labels: set[str]) -> bool:
    """Turn `### **Label**` and its frontmatter entry into links, for labels that
    now have a page. Keeps line endings; skips fenced code."""
    raw = open(path, encoding="utf-8", errors="replace", newline="").read()
    nl = "\r\n" if "\r\n" in raw else "\n"
    lines, fenced, dashes, changed = raw.split(nl), False, 0, False
    for i, ln in enumerate(lines):
        if ln.startswith("```"):
            fenced = not fenced
        elif fenced:
            continue
        elif ln.strip() == "---" and dashes < 2:
            dashes += 1
        elif dashes == 1 and (m := re.match(r'^(\s*-\s*)"([^"\[\]]+)"\s*$', ln)):
            if m.group(2) in labels:
                lines[i], changed = f'{m.group(1)}"[[{m.group(2)}]]"', True
        elif (m := re.match(r"^###\s+\*\*([^*]+)\*\*\s*$", ln)) and m.group(1).strip() in labels:
            lines[i], changed = f"### [[{m.group(1).strip()}]]", True
    if changed:
        with open(path, "w", encoding="utf-8", newline="") as f:
            f.write(nl.join(lines))
    return changed


def cmd_sync(args) -> int:
    cfg = load_config()
    vault = os.path.abspath(os.path.expanduser(
        args.vault or cfg_get(cfg, "notes_repo", "NOTES_REPO", "")))
    if not args.vault and not cfg_get(cfg, "notes_repo", "NOTES_REPO", ""):
        print("ERROR: no notes_repo; run skills/setup/install.py notes", file=sys.stderr)
        return 2
    daily_dir = os.path.join(vault, cfg_get(cfg, "vault_subfolder", "PULSE_VAULT_SUBFOLDER", "Pulse/Daily"))
    projects_dir = os.path.join(
        vault, cfg_get(cfg, "projects_subfolder", "PULSE_PROJECTS_SUBFOLDER", "Pulse/Projects"))
    ignore = set(args.ignore) if args.ignore else {"Misc"}

    have_page = set()
    for label, proj in sorted(collect(daily_dir, vault, ignore).items()):
        path = os.path.join(projects_dir, f"{label}.md")
        old = read_note(path) if os.path.isfile(path) else None
        if old is None and len(proj["days"]) < args.min_days:
            continue
        if old is not None and not re.match(r"^---\n(?:.*\n)*?type: project\n", old):
            print(f"SKIPPED {path} (not a Pulse project page, left as written)")
            have_page.add(label)  # it exists, so headings may link to it
            continue
        about = ABOUT_RE.search(old) if old else None
        text = render_page(label, proj, (about.group(1).strip() if about else "") or ABOUT_TODO)
        have_page.add(label)
        if text != old:
            os.makedirs(projects_dir, exist_ok=True)
            with open(path, "w", encoding="utf-8", newline="\n") as f:
                f.write(text)
            print(f"{'UPDATED' if old else 'NEW'} {path}")
    for note in list_dated_notes(daily_dir):
        if relink(note, have_page):
            print(f"RELINKED {note}")
    print(f"OK {len(have_page)} project page(s)")
    return 0


def main() -> int:
    utf8_stdio()
    p = argparse.ArgumentParser(description="Pulse project pages.")
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("sync", help="build or refresh project pages from the daily notes")
    s.add_argument("--vault", default=None, help="notes repo (default: notes_repo from config)")
    s.add_argument("--min-days", type=int, default=2,
                   help="days a project must appear on before it gets a page (default 2)")
    s.add_argument("--ignore", action="append", default=None,
                   help="label that never gets a page (default: Misc)")
    s.set_defaults(fn=cmd_sync)
    args = p.parse_args()
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
