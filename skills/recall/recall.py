#!/usr/bin/env python3
"""Pulse recall: the one script the recall skill calls.

Subcommands (run `recall.py <cmd> -h` for each):
  search   find daily-note lines that match a question, print JSON

Stdlib only. No LLM (the answering step lives in skills/recall/SKILL.md). Reads
the daily notes in the notes repo; never touches Convex. Each hit is one Work
log bullet, one day Summary, or one Open loops item, with its date, project,
type and the note it came from.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "shared"))
from common import (  # noqa: E402
    LOOP_TAG_RE, TASK_RE, cfg_get, h2_body, list_dated_notes, load_config, loop_text,
    parse_note, read_note, strip_code_blocks, utf8_stdio)

TYPES = ["outcome", "decided", "bug", "rule", "learned", "open", "refs", "result", "summary"]
PREFIX_RE = re.compile(r"^(Outcome|Decided|Bug|Rule|Learned|Open|Refs): ")
WORD_RE = re.compile(r"[^\W_][\w.#/-]*")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
STOPWORDS = set("""a about an and are as at be been by did do does for from had has have how i in
is it me my of on or our that the then this to was we were what when where which who why
with you""".split())


def terms(text: str) -> list[str]:
    seen = dict.fromkeys(w.rstrip(".") for w in WORD_RE.findall(text.lower()))
    return [w for w in seen if w and w not in STOPWORDS]


def stem(word: str) -> str:
    """Crude plural/tense fold so "fixed" finds "fix" and "alerts" finds "alert"."""
    for suffix in ("ing", "ed", "es", "s"):
        if word.endswith(suffix) and len(word) - len(suffix) >= 3:
            word = word[:-len(suffix)]
            break
    return word[:-1] if word.endswith("e") and len(word) > 3 else word


def entries(path: str, vault: str):
    """Yield every searchable line of one daily note."""
    date = os.path.splitext(os.path.basename(path))[0]
    note = os.path.relpath(path, vault).replace("\\", "/")
    text = strip_code_blocks(read_note(path))
    summary, blocks = parse_note(text)
    base = {"date": date, "note": note}
    if summary:
        yield {**base, "project": None, "type": "summary", "text": summary}
    for blk in blocks:
        for bullet in blk["bullets"]:
            m = PREFIX_RE.match(bullet)
            yield {**base, "project": blk["project"],
                   "type": m.group(1).lower() if m else "result", "text": bullet}
    for ln in (h2_body(text, "## Open loops") or "").splitlines():
        t, tag = TASK_RE.match(ln), LOOP_TAG_RE.search(ln)
        if t and tag:
            yield {**base, "project": tag.group("project").strip(), "type": "open",
                   "text": loop_text(ln), "state": "open" if t.group(1) == " " else "closed"}


def score(entry: dict, query: list[str]) -> int:
    """Query terms found in the line (2 each) or only in its project name (1 each)."""
    words = {stem(w) for w in terms(entry["text"])}
    name = {stem(w) for w in terms(entry["project"] or "")}
    return sum(2 if stem(q) in words else 1 if stem(q) in name else 0 for q in query)


def valid_date(value: str | None) -> bool:
    if value is None:
        return True
    try:
        return bool(DATE_RE.match(value)) and bool(datetime.strptime(value, "%Y-%m-%d"))
    except ValueError:
        return False


def fail(message: str) -> int:
    print(json.dumps({"error": message}), file=sys.stderr)
    return 2


def cmd_search(args) -> int:
    cfg = load_config()
    repo = args.vault or cfg_get(cfg, "notes_repo", "NOTES_REPO", "")
    if not repo:
        return fail("no notes_repo; run skills/setup/install.py notes")
    for flag, value in (("--since", args.since), ("--until", args.until)):
        if not valid_date(value):
            return fail(f"{flag} must be a real date as YYYY-MM-DD, got {value!r}")
    if args.limit < 1:
        return fail("--limit must be 1 or more")
    vault = os.path.abspath(os.path.expanduser(repo))
    daily_dir = os.path.join(vault, cfg_get(cfg, "vault_subfolder", "PULSE_VAULT_SUBFOLDER", "Pulse/Daily"))
    if not os.path.isdir(daily_dir):
        return fail(f"no daily notes folder at {daily_dir}; check notes_repo and "
                    "vault_subfolder in ~/.pulse/config.yaml")
    query = terms(" ".join(args.query))
    project = args.project.lower() if args.project else None
    filtered = bool(args.type or project or args.since or args.until)
    unusable = bool(args.query) and not query and not filtered

    notes, hits, searched = list_dated_notes(daily_dir), [], 0
    for path in notes:
        date = os.path.splitext(os.path.basename(path))[0]
        if (args.since and date < args.since) or (args.until and date > args.until) or unusable:
            continue
        searched += 1
        for e in entries(path, vault):
            if args.type and e["type"] not in args.type:
                continue
            if project and project not in (e["project"] or "").lower():
                continue
            s = score(e, query)
            if query and s == 0:
                continue
            hits.append({**e, "score": s})
    hits.sort(key=lambda h: h["date"], reverse=True)
    hits.sort(key=lambda h: h["score"], reverse=True)
    seen, unique = set(), []
    for h in hits:
        key = (h["type"], h["project"], h["text"]) if h["type"] == "open" else id(h)
        if key not in seen:
            seen.add(key)
            unique.append(h)
    out = {"vault": vault, "notes_in_vault": len(notes), "notes_searched": searched,
           "query_terms": query,
           "total_hits": len(unique), "hits": unique[:args.limit]}
    print(json.dumps(out, ensure_ascii=False))
    return 0


def main() -> int:
    utf8_stdio()
    p = argparse.ArgumentParser(description="Pulse recall.")
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("search", help="find daily-note lines that match a question")
    s.add_argument("query", nargs="*", help="words to look for (any order)")
    s.add_argument("--project", default=None, help="only this project (substring, any case)")
    s.add_argument("--type", action="append", choices=TYPES, default=None,
                   help="only this kind of line (repeatable)")
    s.add_argument("--since", default=None, help="YYYY-MM-DD, inclusive")
    s.add_argument("--until", default=None, help="YYYY-MM-DD, inclusive")
    s.add_argument("--limit", type=int, default=20)
    s.add_argument("--vault", default=None, help="notes repo (default: notes_repo from config)")
    s.set_defaults(fn=cmd_search)
    args = p.parse_args()
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
