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
    LOOP_TAG_RE, MONTHS, TASK_RE, UNSAFE_LABEL_RE, cfg_get, h2_body, list_dated_notes, load_config,
    loop_text, parse_note, read_note, strip_code_blocks, utf8_stdio)

ABOUT_TODO = "About: not written yet."
SECTIONS = [("Decided", "## Decisions"), ("Bug", "## Bugs"),
            ("Rule", "## Rules and lessons"), ("Learned", "## Rules and lessons")]
FRONTMATTER_RE = re.compile(r"^---\n(.*?)\n---\n", re.S)
PAGE_TAGS = "tags: [pulse, project]"
ABOUT_RE = re.compile(r"^# [^\n]*\n(.*?)(?=^## |\Z)", re.M | re.S)


def pretty(date: str) -> str:
    d = datetime.strptime(date, "%Y-%m-%d")
    return f"{MONTHS[d.month - 1][:3]} {d.day}, {d.year}"


def is_pulse_page(text: str) -> bool:
    fm = FRONTMATTER_RE.match(text)
    return bool(fm) and "type: project" in fm.group(1).splitlines() and PAGE_TAGS in fm.group(1).splitlines()


def collect(daily_dir: str, vault: str, ignore: set[str], names: dict[str, str]):
    """Read every daily note, oldest first. Returns (projects, unsafe) where
    projects maps a label to {days, items, open} and unsafe lists labels that
    cannot be a file name. `names` maps a lowercased label to the spelling to
    use, so labels that differ only by case share one page."""
    projects: dict[str, dict] = {}
    unsafe: list[str] = []
    notes = list_dated_notes(daily_dir)
    texts = [strip_code_blocks(read_note(path)) for path in notes]
    for path, text in zip(notes, texts):
        date = os.path.splitext(os.path.basename(path))[0]
        target = os.path.splitext(os.path.relpath(path, vault))[0].replace("\\", "/")
        for blk in parse_note(text)[1]:
            if blk["project"] in ignore:
                continue
            if UNSAFE_LABEL_RE.search(blk["project"]):
                if blk["project"] not in unsafe:
                    unsafe.append(blk["project"])
                continue
            label = names.setdefault(blk["project"].lower(), blk["project"])
            proj = projects.setdefault(label, {"days": [], "items": {}, "open": []})
            if (date, target) not in proj["days"]:
                proj["days"].append((date, target))
            for bullet in blk["bullets"]:
                for prefix, section in SECTIONS:
                    if bullet.startswith(prefix + ": "):
                        text_ = bullet[len(prefix) + 2:].strip()
                        line = (f"- {pretty(date)}: {text_}" if section != "## Rules and lessons"
                                else f"- {prefix}: {text_} ({pretty(date)})")
                        proj["items"].setdefault(section, []).append(line)
    ledger = next((h2_body(t, "## Open loops") for t in reversed(texts)
                   if h2_body(t, "## Open loops") is not None), "")
    for ln in ledger.splitlines():
        t, tag = TASK_RE.match(ln), LOOP_TAG_RE.search(ln)
        label = names.get(tag.group("project").strip().lower()) if tag else None
        if t and t.group(1) == " " and label in projects:
            projects[label]["open"].append(f"- {loop_text(ln)} (since {tag.group('since')})")
    return projects, unsafe


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


def relink(path: str, names: dict[str, str]) -> bool:
    """Point a daily note's Work log headings and frontmatter entries at the
    project pages in `names` (lowercased label -> page name), bold or already
    linked. Keeps line endings; skips fenced code."""
    raw = open(path, encoding="utf-8", errors="replace", newline="").read()
    nl = "\r\n" if "\r\n" in raw else "\n"
    lines, fenced, dashes, changed = raw.split(nl), False, 0, False
    for i, ln in enumerate(lines):
        new = ln
        if ln.startswith("```"):
            fenced = not fenced
        elif fenced:
            continue
        elif ln.strip() == "---" and dashes < 2:
            dashes += 1
        elif dashes == 1 and (m := re.match(r'^(\s*-\s*)"(?:\[\[)?([^"\[\]]+)(?:\]\])?"\s*$', ln)):
            if (name := names.get(m.group(2).strip().lower())):
                new = f'{m.group(1)}"[[{name}]]"'
        elif (m := re.match(r"^###\s+(?:\*\*([^*]+)\*\*|\[\[([^\]#|]+)\]\])\s*$", ln)):
            if (name := names.get((m.group(1) or m.group(2)).strip().lower())):
                new = f"### [[{name}]]"
        if new != ln:
            lines[i], changed = new, True
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

    existing = {os.path.splitext(f)[0].lower(): os.path.splitext(f)[0]
                for f in (os.listdir(projects_dir) if os.path.isdir(projects_dir) else [])
                if f.endswith(".md")}
    names = dict(existing)
    projects, unsafe = collect(daily_dir, vault, ignore, names)
    for label in unsafe:
        print(f"SKIPPED {label!r} (the name cannot be a file name, so it gets no page)")

    pages: dict[str, str] = {}
    for label, proj in sorted(projects.items()):
        path = os.path.join(projects_dir, f"{label}.md")
        old = read_note(path) if label.lower() in existing else None
        if old is None and len(proj["days"]) < args.min_days:
            continue
        pages[label.lower()] = label
        if old is not None and not is_pulse_page(old):
            print(f"SKIPPED {path} (not a Pulse project page, left as written)")
            continue
        about = ABOUT_RE.search(old) if old else None
        text = render_page(label, proj, (about.group(1).strip() if about else "") or ABOUT_TODO)
        if text != old:
            os.makedirs(projects_dir, exist_ok=True)
            with open(path, "w", encoding="utf-8", newline="\n") as f:
                f.write(text)
            print(f"{'UPDATED' if old else 'NEW'} {path}")
    for note in list_dated_notes(daily_dir):
        if relink(note, pages):
            print(f"RELINKED {note}")
    print(f"OK {len(pages)} project page(s)")
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
