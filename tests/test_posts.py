#!/usr/bin/env python3
"""Tests for the post writer (skills/posts/posts.py).

Stdlib only, no test framework: plain asserts, runnable directly.

    python3 tests/test_posts.py
"""
from __future__ import annotations

import contextlib
import io
import json
import os
import tempfile

from test_digest import GOOD, REPO, dg, load

po = load("posts", os.path.join(REPO, "skills", "posts", "posts.py"))

DRAFT = """---
type: posts
week_start: "2026-06-08"
week_end: "2026-06-14"
status: draft
tags: [pulse, posts]
---

# Post drafts, week of Jun 8 to Jun 14, 2026

## LinkedIn

Some of our alerts were never arriving. No error, nothing in the logs.

The cause was two workers picking up the same job.

#buildinpublic

## X

1/ Some of our alerts were never arriving. No error, nothing in the logs.

2/ Cause: two workers took the same job. Fix: one lock per job.

## Sources

Written from [[Pulse/Weekly/2026-06/2026-06-14|Week of Jun 14]].

---

Part of [[Pulse Posts 2026-06|June 2026]]
"""


def fails(text: str, needle: str):
    problems = po.lint_post(text)
    assert any(needle in p for p in problems), (needle, problems)


def test_good_draft_passes():
    assert po.lint_post(DRAFT) == [], po.lint_post(DRAFT)


def test_template_has_the_sections_lint_wants():
    template = open(os.path.join(REPO, "skills", "posts", "templates", "posts.md"), encoding="utf-8").read()
    problems = po.lint_post(template)
    assert not any("sections must be" in p or "status: draft" in p or "frontmatter" in p
                   for p in problems), problems


def test_length_limits():
    fails(DRAFT.replace("The cause was", "x" * 3001 + " The cause was"), "characters (max 3000)")
    fails(DRAFT.replace("2/ Cause:", "2/ " + "y" * 280 + " Cause:"), "## X post 2 is")
    ok = DRAFT.replace("2/ Cause: two workers took the same job. Fix: one lock per job.", "2/ " + "y" * 277)
    assert po.lint_post(ok) == [], po.lint_post(ok)


def test_thread_must_be_numbered_in_order():
    fails(DRAFT.replace("2/ Cause", "3/ Cause"), "must start with `2/ `")
    fails(DRAFT.replace("1/ Some", "Some"), "must start with `1/ `")


def test_drafts_are_plain_text():
    fails(DRAFT.replace("two workers picking", "**two workers** picking"), "plain text")
    fails(DRAFT.replace("2/ Cause:", "2/ See [[Web App]]. Cause:"), "plain text")
    fails(DRAFT.replace("nothing in the logs.\n\nThe cause", "nothing in `app.log`.\n\nThe cause"), "plain text")


def test_dash_banned_phrase_hashtags_and_status():
    fails(DRAFT.replace("No error, nothing", "No error — nothing"), "em/en dash")
    fails(DRAFT.replace("The cause was", "After leveraging logs, the cause was"), "AI-tell phrase")
    fails(DRAFT.replace("#buildinpublic", "#a1 #b2 #c3 #d4 #e5 #f6"), "hashtags")
    fails(DRAFT.replace("status: draft", "status: posted"), "status: draft")
    fails(DRAFT.replace("[[Pulse/Weekly/2026-06/2026-06-14|Week of Jun 14]]", "the weekly note"), "## Sources must link")


def test_sections_exact_and_not_empty():
    fails(DRAFT.replace("## X", "## Twitter"), "sections must be exactly")
    fails(DRAFT + "\n## Notes\n\nx\n", "sections must be exactly")
    empty = DRAFT[:DRAFT.index("## LinkedIn")] + "## LinkedIn\n\n## X\n\n## Sources\n\n[[x]]\n"
    fails(empty, "## LinkedIn is empty")
    fails(empty, "## X is empty")


def vault() -> str:
    root = tempfile.mkdtemp()
    for rel, text in {
        "Pulse/Daily/2026-06/2026-06-09.md": GOOD.replace('"2026-06-02"', '"2026-06-09"'),
        "Pulse/Weekly/2026-06/2026-06-14.md": "---\ntype: weekly\n---\n\n# Week\n\nFixed alerts.\n\n"
                                              "## Sources\n\n[[Pulse/Daily/2026-06/2026-06-09|Jun 9]]\n",
        "Pulse/Projects/Web App.md": "---\ntype: project\n---\n\n# Web App\n\nThe customer site.\n\n"
                                     "## Open\n\n- None.\n\n## Days worked\n\n"
                                     "- [[Pulse/Daily/2026-06/2026-06-09|Jun 9, 2026]]\n",
    }.items():
        os.makedirs(os.path.dirname(os.path.join(root, rel)), exist_ok=True)
        with open(os.path.join(root, rel), "w", encoding="utf-8") as f:
            f.write(text)
    return root


def collect(root: str, week_end: str) -> dict:
    old = {k: os.environ.get(k) for k in ("NOTES_REPO", "PULSE_HOME")}
    os.environ.update({"NOTES_REPO": root, "PULSE_HOME": tempfile.mkdtemp()})
    try:
        with contextlib.redirect_stdout(io.StringIO()) as out:
            assert po.cmd_collect(type("A", (), {"week_end": week_end})) == 0
    finally:
        for k, v in old.items():
            os.environ.pop(k) if v is None else os.environ.__setitem__(k, v)
    return json.loads(out.getvalue())


def test_collect_gathers_the_week():
    root = vault()
    got = collect(root, "2026-06-14")
    assert got["week_start"] == "2026-06-08" and got["weekly_note"] == "Pulse/Weekly/2026-06/2026-06-14.md", got
    assert "Fixed alerts." in got["weekly_note_text"], got
    assert got["daily_notes"] == ["Pulse/Daily/2026-06/2026-06-09.md"], got
    assert got["post_path"] == os.path.join(root, "Pulse/Posts", "2026-06", "2026-06-14.md"), got
    assert got["posts_hub_prefix"] == "Pulse Posts" and got["posts_index"] == "Pulse Posts Index.md", got
    assert got["projects"] == [
        {"project": "Web App", "page": "Pulse/Projects/Web App.md", "about": "The customer site."},
        {"project": "Notifications", "page": None, "about": ""}], got


def test_collect_without_a_weekly_note():
    got = collect(vault(), "2026-06-21")
    assert got["weekly_note"] is None and got["weekly_note_text"] == "" and got["daily_notes"] == [], got


def test_post_links_is_idempotent_and_the_graph_is_whole():
    root = vault()
    got = collect(root, "2026-06-14")
    os.makedirs(os.path.dirname(got["post_path"]))
    with open(got["post_path"], "w", encoding="utf-8") as f:
        f.write(DRAFT)
    args = type("A", (), {"vault": root, "subfolder": got["posts_subfolder"], "date": "2026-06-14",
                          "hub_prefix": got["posts_hub_prefix"], "index": got["posts_index"]})
    with contextlib.redirect_stdout(io.StringIO()) as first:
        assert po.cmd_post_links(args) == 0
    with contextlib.redirect_stdout(io.StringIO()) as second:
        assert po.cmd_post_links(args) == 0
    assert "CREATED hub" in first.getvalue() and second.getvalue().strip() == "OK", second.getvalue()
    hub = open(os.path.join(root, "Pulse/Posts/2026-06/Pulse Posts 2026-06.md"), encoding="utf-8").read()
    assert "## Posts\n\n- [[Pulse/Posts/2026-06/2026-06-14|Week ending Jun 14]]" in hub, hub
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()) as err:
        for kind, sub, prefix, index in (("daily", "Pulse/Daily", "Pulse", "Pulse Index.md"),
                                         ("weekly", "Pulse/Weekly", "Pulse Weekly", "Pulse Weekly Index.md")):
            dg.link_into_hubs(type("A", (), {"vault": root, "subfolder": sub, "date": "2026-06-14"
                                             if kind == "weekly" else "2026-06-09",
                                             "hub_prefix": prefix, "index": index}), kind)
        assert dg.cmd_check_links(type("A", (), {"vault": root, "subfolder": "Pulse"})) == 0, err.getvalue()


def main() -> int:
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print(f"OK {t.__name__}")
    print(f"\n{len(tests)} passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
