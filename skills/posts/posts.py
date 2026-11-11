#!/usr/bin/env python3
"""Pulse post writer: the one script the posts skill calls.

Subcommands (run `posts.py <cmd> -h` for each):
  collect     resolve the week, gather the weekly note and project pages, print JSON
  post-links  wire the drafts file into its month hub + posts index (idempotent)
  lint        gate: layout, LinkedIn and X length limits, plain text, no em dash

Stdlib only. No LLM (the writing step lives in skills/posts/SKILL.md). Reads the
weekly note the synth wrote, the week's daily notes and the project pages; never
touches Convex. It writes drafts for the user to review. Nothing here posts.
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
    BANNED_RE, DASH_RE, cfg_get, get_tz, h2_body, link_into_hubs, load_config, notes_repo_dir,
    parse_note, read_note, resolve_week_end, strip_code_blocks, utf8_stdio)

LINKEDIN_MAX = 3000
TWEET_MAX = 280
HASHTAG_MAX = 5
SECTIONS = ["## LinkedIn", "## X", "## Sources"]
ABOUT_RE = re.compile(r"^# [^\n]*\n(.*?)(?=^## |\Z)", re.M | re.S)
MARKUP_RE = re.compile(r"\[\[|\*\*|`|^#{1,6} ", re.M)
HASHTAG_RE = re.compile(r"(?<!\w)#[A-Za-z]\w*")
TWEET_RE = re.compile(r"^(\d+)/ \S")


def cmd_collect(args) -> int:
    cfg = load_config()
    week_end = resolve_week_end(args.week_end, get_tz(cfg))
    week_start = week_end - timedelta(days=6)
    repo = notes_repo_dir(cfg)
    if not repo:
        print(json.dumps({"error": "no notes_repo; run skills/setup/install.py notes",
                          "week_end": week_end.isoformat()}), file=sys.stderr)
        return 2
    daily = cfg_get(cfg, "vault_subfolder", "PULSE_VAULT_SUBFOLDER", "Pulse/Daily")
    weekly = cfg_get(cfg, "weekly_subfolder", "PULSE_WEEKLY_SUBFOLDER", "Pulse/Weekly")
    projects = cfg_get(cfg, "projects_subfolder", "PULSE_PROJECTS_SUBFOLDER", "Pulse/Projects")
    posts = cfg_get(cfg, "posts_subfolder", "PULSE_POSTS_SUBFOLDER", "Pulse/Posts")
    hub_prefix = cfg_get(cfg, "posts_hub_prefix", "PULSE_POSTS_HUB_PREFIX",
                         f"{cfg_get(cfg, 'hub_prefix', 'PULSE_HUB_PREFIX', 'Pulse')} Posts")
    index = cfg_get(cfg, "posts_index", "PULSE_POSTS_INDEX", f"{hub_prefix} Index.md")
    end, ym = week_end.isoformat(), week_end.isoformat()[:7]

    weekly_rel = f"{weekly}/{ym}/{end}.md"
    has_weekly = os.path.isfile(os.path.join(repo, weekly_rel))
    notes, summaries, labels = [], [], []
    for offset in range(7):
        iso = (week_start + timedelta(days=offset)).isoformat()
        rel = f"{daily}/{iso[:7]}/{iso}.md"
        if not os.path.isfile(os.path.join(repo, rel)):
            continue
        notes.append(rel)
        summary, blocks = parse_note(strip_code_blocks(read_note(os.path.join(repo, rel))))
        if summary:
            summaries.append({"date": iso, "summary": summary})
        labels += [b["project"] for b in blocks if b["project"] not in labels]
    pages = []
    for label in labels:
        rel = f"{projects}/{label}.md"
        if os.path.isfile(os.path.join(repo, rel)):
            about = ABOUT_RE.search(read_note(os.path.join(repo, rel)))
            pages.append({"project": label, "page": rel,
                          "about": about.group(1).strip() if about else ""})
        else:
            pages.append({"project": label, "page": None, "about": ""})

    print(json.dumps({
        "week_start": week_start.isoformat(),
        "week_end": end,
        "notes_repo_dir": repo,
        "posts_subfolder": posts,
        "posts_hub_prefix": hub_prefix,
        "posts_index": index,
        "post_path": os.path.join(repo, posts, ym, f"{end}.md"),
        "weekly_note": weekly_rel if has_weekly else None,
        "weekly_note_text": read_note(os.path.join(repo, weekly_rel)) if has_weekly else "",
        "daily_notes": notes,
        "daily_summaries": summaries,
        "projects": pages,
    }, ensure_ascii=False))
    return 0


def cmd_post_links(args) -> int:
    return link_into_hubs(args, "posts")


def tweets(body: str) -> list[str]:
    return [p.strip() for p in re.split(r"\n\s*\n", body.strip()) if p.strip()]


def lint_post(raw: str) -> list[str]:
    problems = []
    fm = re.match(r"^---\n(.*?)\n---\n", raw.lstrip(), re.S)
    if not fm:
        problems.append("missing YAML frontmatter")
    elif not re.search(r"^status: draft\s*$", fm.group(1), re.M):
        problems.append("frontmatter needs `status: draft` (Pulse only writes drafts)")
    h2s = [m.group(1).rstrip() for m in re.finditer(r"^(## .*)$", raw, re.M)]
    if h2s != SECTIONS:
        problems.append(f"sections must be exactly {SECTIONS} in that order, got {h2s}")
        return problems

    linkedin = (h2_body(raw, "## LinkedIn") or "").strip()
    if not linkedin:
        problems.append("## LinkedIn is empty")
    if len(linkedin) > LINKEDIN_MAX:
        problems.append(f"## LinkedIn is {len(linkedin)} characters (max {LINKEDIN_MAX})")
    if len(HASHTAG_RE.findall(linkedin)) > HASHTAG_MAX:
        problems.append(f"## LinkedIn has more than {HASHTAG_MAX} hashtags")

    thread = tweets(h2_body(raw, "## X") or "")
    if not thread:
        problems.append("## X is empty")
    for n, tweet in enumerate(thread, 1):
        m = TWEET_RE.match(tweet)
        if not m or int(m.group(1)) != n:
            problems.append(f"## X post {n} must start with `{n}/ ` "
                            f"(one post per paragraph, numbered in order): {tweet[:50]!r}")
        if len(tweet) > TWEET_MAX:
            problems.append(f"## X post {n} is {len(tweet)} characters (max {TWEET_MAX})")

    for name, body in (("## LinkedIn", linkedin), ("## X", "\n\n".join(thread))):
        if (m := MARKUP_RE.search(body)):
            problems.append(f"{name} must be plain text ready to paste, found {m.group(0).strip()!r}")
    if "[[" not in re.split(r"^---\s*$", h2_body(raw, "## Sources") or "", flags=re.M)[0]:
        problems.append("## Sources must link the weekly note it was written from")
    for i, line in enumerate(raw.splitlines(), 1):
        if DASH_RE.search(line):
            problems.append(f"line {i}: em/en dash")
        if (w := BANNED_RE.search(line)):
            problems.append(f"line {i}: AI-tell phrase {w.group(0)!r} (see humanizer.md)")
    return problems


def cmd_lint(args) -> int:
    failed = False
    for path in args.posts:
        try:
            problems = lint_post(open(path, encoding="utf-8").read())
        except Exception as e:
            problems = [f"cannot read: {e}"]
        if problems:
            failed = True
            print(f"FAIL {path}", file=sys.stderr)
            for pr in problems:
                print(f"  - {pr}", file=sys.stderr)
        else:
            print(f"OK {path}")
    return 1 if failed else 0


def main() -> int:
    utf8_stdio()
    p = argparse.ArgumentParser(description="Pulse post writer.")
    sub = p.add_subparsers(dest="cmd", required=True)

    c = sub.add_parser("collect", help="gather the week's weekly note and project pages")
    c.add_argument("--week-end", default=None)
    c.set_defaults(fn=cmd_collect)

    pl = sub.add_parser("post-links", help="wire the drafts file into its hub + index")
    pl.add_argument("--vault", required=True)
    pl.add_argument("--subfolder", required=True)
    pl.add_argument("--date", required=True)
    pl.add_argument("--hub-prefix", required=True)
    pl.add_argument("--index", required=True)
    pl.set_defaults(fn=cmd_post_links)

    li = sub.add_parser("lint", help="gate: layout, length limits, plain text")
    li.add_argument("posts", nargs="+")
    li.set_defaults(fn=cmd_lint)

    args = p.parse_args()
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
