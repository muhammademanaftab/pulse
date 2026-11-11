#!/usr/bin/env python3
"""Tests for project pages (skills/projects/projects.py).

Stdlib only, no test framework: plain asserts, runnable directly.

    python3 tests/test_projects.py

Covers page creation and refresh, the kept About paragraph, relinking daily
notes, and that the result still passes the digest's lint and link gates.
"""
from __future__ import annotations

import contextlib
import io
import os
import tempfile

from test_digest import GOOD, REPO, dg, load

pj = load("projects", os.path.join(REPO, "skills", "projects", "projects.py"))

DAY2 = GOOD.replace('date: "2026-06-02"', 'date: "2026-06-03"').replace(
    "- Decided: keep sessions for 30 days. Why: logins were the top complaint. Rejected: 7 days.\n",
    "- Rule: anything that deletes data asks first.\n").replace(
    "- Open: Add the preview button to mobile.\n", "").replace(
    '  - "Notifications"\n', "").replace(
    GOOD[GOOD.index("### **Notifications**"):GOOD.index("## Open loops")], "")


def vault() -> str:
    root = tempfile.mkdtemp()
    os.makedirs(os.path.join(root, "Pulse", "Daily", "2026-06"))
    for date, text in (("2026-06-02", GOOD), ("2026-06-03", DAY2)):
        with open(daily(root, date), "w", encoding="utf-8") as f:
            f.write(text.replace("[[Web App]]", "**Web App**").replace('"**Web App**"', '"Web App"'))
    return root


def daily(root: str, date: str) -> str:
    return os.path.join(root, "Pulse", "Daily", date[:7], f"{date}.md")


def page(root: str, label: str) -> str:
    return os.path.join(root, "Pulse", "Projects", f"{label}.md")


def sync(root: str, **kw) -> str:
    args = type("A", (), {"vault": root, "min_days": kw.get("min_days", 2), "ignore": None})
    with contextlib.redirect_stdout(io.StringIO()) as out:
        assert pj.cmd_sync(args) == 0
    return out.getvalue()


def test_page_is_built_from_the_daily_notes():
    root = vault()
    out = sync(root)
    assert f"NEW {page(root, 'Web App')}" in out, out
    text = open(page(root, "Web App"), encoding="utf-8").read()
    assert 'first_day: "2026-06-02"' in text and "days_worked: 2" in text, text
    assert pj.ABOUT_TODO in text, text
    assert "- Jun 2, 2026: keep sessions for 30 days. Why: logins were the top complaint. Rejected: 7 days." in text
    assert "- Rule: anything that deletes data asks first. (Jun 3, 2026)" in text, text
    assert "- Add the preview button to mobile. (since Jun 2)" in text, text
    assert text.index("2026-06-03|Jun 3, 2026") < text.index("2026-06-02|Jun 2, 2026"), text
    assert "## Bugs" not in text, text


def test_one_day_project_waits_for_min_days():
    root = vault()
    sync(root)
    assert not os.path.exists(page(root, "Notifications"))
    sync(root, min_days=1)
    assert "- Jun 2, 2026: some alerts never arrived." in open(
        page(root, "Notifications"), encoding="utf-8").read()


def test_sync_is_idempotent_and_keeps_the_about_paragraph():
    root = vault()
    sync(root)
    path = page(root, "Web App")
    text = open(path, encoding="utf-8").read()
    with open(path, "w", encoding="utf-8") as f:
        f.write(text.replace(pj.ABOUT_TODO, "The customer site.\n\nSecond line."))
    assert sync(root).strip() == "OK 1 project page(s)"
    assert "The customer site.\n\nSecond line.\n\n## Open" in open(path, encoding="utf-8").read()


def test_daily_notes_are_relinked_and_still_pass_the_gates():
    root = vault()
    out = sync(root)
    assert out.count("RELINKED") == 2, out
    for date in ("2026-06-02", "2026-06-03"):
        text = open(daily(root, date), encoding="utf-8").read()
        assert "### [[Web App]]" in text and '  - "[[Web App]]"' in text, text
        problems = dg.lint_structure(text, daily(root, date))
        assert problems == [], (date, problems)
    assert "### **Notifications**" in open(daily(root, "2026-06-02"), encoding="utf-8").read()
    args = type("A", (), {"vault": root, "subfolder": "Pulse"})
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()) as err:
        dg.cmd_month_links(type("A", (), {"vault": root, "subfolder": "Pulse/Daily", "date": "2026-06-02",
                                          "hub_prefix": "Pulse", "index": "Pulse Index.md"}))
        dg.cmd_month_links(type("A", (), {"vault": root, "subfolder": "Pulse/Daily", "date": "2026-06-03",
                                          "hub_prefix": "Pulse", "index": "Pulse Index.md"}))
        assert dg.cmd_check_links(args) == 0, err.getvalue()


def test_closed_item_leaves_the_open_list():
    root = vault()
    with open(daily(root, "2026-06-03"), encoding="utf-8") as f:
        text = f.read()
    with open(daily(root, "2026-06-03"), "w", encoding="utf-8") as f:
        f.write(text.replace("- [ ] Add the preview button to mobile. (Web App, since Jun 2)",
                             "- [x] Add the preview button to mobile. (Web App, since Jun 2, done Jun 3)"))
    sync(root)
    assert "## Open\n\n- None.\n" in open(page(root, "Web App"), encoding="utf-8").read()


def test_hand_written_note_is_left_alone_but_still_linked():
    root = vault()
    os.makedirs(os.path.dirname(page(root, "Web App")))
    with open(page(root, "Web App"), "w", encoding="utf-8") as f:
        f.write("# Web App\n\nMy own notes.\n")
    out = sync(root)
    assert "SKIPPED" in out, out
    assert open(page(root, "Web App"), encoding="utf-8").read() == "# Web App\n\nMy own notes.\n"
    assert "### [[Web App]]" in open(daily(root, "2026-06-02"), encoding="utf-8").read()


def test_misc_and_unsafe_labels_get_no_page():
    root = vault()
    for date in ("2026-06-02", "2026-06-03"):
        with open(daily(root, date), encoding="utf-8") as f:
            text = f.read()
        with open(daily(root, date), "w", encoding="utf-8") as f:
            f.write(text.replace("## Open loops", "### **Misc**\n\n- Outcome: x.\n\n"
                                 "### **a/b**\n\n- Outcome: y.\n\n## Open loops"))
    sync(root)
    assert sorted(os.listdir(os.path.join(root, "Pulse", "Projects"))) == ["Web App.md"]


def main() -> int:
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print(f"OK {t.__name__}")
    print(f"\n{len(tests)} passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
