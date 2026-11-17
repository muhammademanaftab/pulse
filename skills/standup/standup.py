#!/usr/bin/env python3
"""Pulse standup: collect a daily note and lint a short draft.

collect reads the latest daily note before today, or exactly --date YYYY-MM-DD.
lint checks Yesterday, Today and Blockers sections. Writing lives in SKILL.md.
Stdlib only. No network access, publishing or changes to the source notes.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import date, datetime

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "shared"))
from common import (
    BANNED_RE, DASH_RE, LOOP_TAG_RE, TASK_RE, cfg_get, get_tz, h2_body,
    list_dated_notes, load_config, loop_text, notes_repo_dir, parse_note,
    read_note, strip_code_blocks, utf8_stdio)

SECTIONS = ["## Yesterday", "## Today", "## Blockers"]
PLACEHOLDER_RE = re.compile(r"<[^<>\n]+>")


def parse_date(value: str) -> date:
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise ValueError("--date must be a valid date as YYYY-MM-DD")
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise ValueError("--date must be a valid date as YYYY-MM-DD") from None


def collect(cfg: dict, requested: str | None, today: date) -> dict:
    target = parse_date(requested) if requested is not None else None
    repo = notes_repo_dir(cfg)
    if not repo or not os.path.isdir(repo):
        raise ValueError("no readable notes repo; configure notes_repo or NOTES_REPO")
    daily = cfg_get(cfg, "vault_subfolder", "PULSE_VAULT_SUBFOLDER", "Pulse/Daily")
    candidates = []
    for path in list_dated_notes(os.path.join(repo, daily)):
        try:
            day = parse_date(os.path.basename(path)[:-3])
        except ValueError:
            continue
        if (target is not None and day == target) or (target is None and day < today):
            candidates.append((day, path))
    if not candidates:
        scope = f"for {target.isoformat()}" if target else f"before {today.isoformat()}"
        raise ValueError(f"no daily note {scope}; run the digest first")
    source_date, path = max(candidates)
    text = strip_code_blocks(read_note(path))
    summary, projects = parse_note(text)
    open_items = []
    for line in (h2_body(text, "## Open loops") or "").splitlines():
        task = TASK_RE.match(line)
        if task and task.group(1) == " ":
            tag = LOOP_TAG_RE.search(line)
            open_items.append({"project": tag.group("project").strip() if tag else None,
                               "text": loop_text(line)})
    return {"notes_repo_dir": repo, "source_date": source_date.isoformat(),
            "today": today.isoformat(), "note": os.path.relpath(path, repo).replace("\\", "/"),
            "summary": summary, "projects": projects, "open_items": open_items,
            "note_text": text}


def cmd_collect(args) -> int:
    cfg = load_config()
    try:
        result = collect(cfg, args.date, datetime.now(get_tz(cfg)).date())
    except (OSError, ValueError) as error:
        print(json.dumps({"error": str(error)}, ensure_ascii=False), file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False))
    return 0


def lint_standup(raw: str) -> list[str]:
    raw = raw.lstrip("\ufeff").strip()
    headings = re.findall(r"^## .*$", raw, re.M)
    if headings != SECTIONS:
        return [f"sections must be exactly {SECTIONS} in that order"]
    problems = []
    if not raw.startswith(SECTIONS[0] + "\n"):
        problems.append("start with ## Yesterday, without a preamble")
    for heading in SECTIONS:
        body = (h2_body(raw + "\n", heading) or "").strip()
        if not body:
            problems.append(f"{heading} is empty; state when nothing is recorded")
        elif any(not re.match(r"^- \S", line) for line in body.splitlines() if line.strip()):
            problems.append(f"{heading} needs one bullet per line")
    for number, line in enumerate(raw.splitlines(), 1):
        if PLACEHOLDER_RE.search(line):
            problems.append(f"line {number}: template placeholder")
        if DASH_RE.search(line):
            problems.append(f"line {number}: em/en dash")
        if BANNED_RE.search(line):
            problems.append(f"line {number}: AI-tell phrase (see humanizer.md)")
    return problems


def cmd_lint(args) -> int:
    failed = False
    for path in args.drafts:
        try:
            with open(path, encoding="utf-8") as draft:
                problems = lint_standup(draft.read())
        except (OSError, UnicodeError) as error:
            problems = [f"cannot read: {error}"]
        if problems:
            failed = True
            print(f"FAIL {path}", file=sys.stderr)
            for problem in problems:
                print(f"  - {problem}", file=sys.stderr)
        else:
            print(f"OK {path}")
    return 1 if failed else 0


def main() -> int:
    utf8_stdio()
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("collect", help="read the latest completed daily note")
    c.add_argument("--date", help="read exactly this daily note: YYYY-MM-DD")
    c.set_defaults(fn=cmd_collect)
    lint = sub.add_parser("lint", help="check the three draft sections and style")
    lint.add_argument("drafts", nargs="+")
    lint.set_defaults(fn=cmd_lint)
    args = parser.parse_args()
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
