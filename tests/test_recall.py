#!/usr/bin/env python3
"""Tests for recall search (skills/recall/recall.py).

Stdlib only, no test framework: plain asserts, runnable directly.

    python3 tests/test_recall.py
"""
from __future__ import annotations

import contextlib
import io
import json
import os
import tempfile

from test_digest import GOOD, REPO, load

rc = load("recall", os.path.join(REPO, "skills", "recall", "recall.py"))

DAY2 = GOOD.replace('date: "2026-06-02"', 'date: "2026-06-09"').replace(
    "- Decided: keep sessions for 30 days. Why: logins were the top complaint. Rejected: 7 days.\n",
    "- Learned: the CI cache key hashes the lockfile.\n").replace(
    "- [ ] Add the preview button to mobile. (Web App, since Jun 2)",
    "- [x] Add the preview button to mobile. (Web App, since Jun 2, done Jun 9)").replace(
    "- Open: Add the preview button to mobile.\n", "")


def vault() -> str:
    root = tempfile.mkdtemp()
    for date, text in (("2026-06-02", GOOD), ("2026-06-09", DAY2)):
        os.makedirs(os.path.join(root, "Pulse", "Daily", date[:7]), exist_ok=True)
        with open(os.path.join(root, "Pulse", "Daily", date[:7], f"{date}.md"), "w", encoding="utf-8") as f:
            f.write(text)
    return root


ROOT = vault()


def search(*query, **kw) -> dict:
    args = type("A", (), {"query": list(query), "vault": ROOT, "project": kw.get("project"),
                          "type": kw.get("type"), "since": kw.get("since"),
                          "until": kw.get("until"), "limit": kw.get("limit", 20)})
    with contextlib.redirect_stdout(io.StringIO()) as out:
        assert rc.cmd_search(args) == 0
    return json.loads(out.getvalue())


def test_finds_the_decision_with_its_date_and_note():
    hit = search("why", "keep", "sessions", type=["decided"])["hits"][0]
    assert hit["text"].startswith("Decided: keep sessions for 30 days."), hit
    assert (hit["date"], hit["project"], hit["note"]) == (
        "2026-06-02", "Web App", "Pulse/Daily/2026-06/2026-06-02.md"), hit


def test_word_forms_match_and_best_hit_comes_first():
    got = search("alert", "arrive")
    assert got["hits"][0]["type"] == "bug" and "alerts never arrived" in got["hits"][0]["text"], got


def test_type_and_project_filters():
    assert {h["type"] for h in search(type=["learned"])["hits"]} == {"learned"}
    hits = search(project="notif")["hits"]
    assert hits and {h["project"] for h in hits} == {"Notifications"}, hits


def test_date_range_and_newest_first():
    assert {h["date"] for h in search(since="2026-06-05")["hits"]} == {"2026-06-09"}
    assert {h["date"] for h in search(until="2026-06-05")["hits"]} == {"2026-06-02"}
    dates = [h["date"] for h in search("preview", "button", type=["result"])["hits"]]
    assert dates == ["2026-06-09", "2026-06-02"], dates


def test_open_items_report_their_latest_state_once():
    hits = search("preview", "mobile", type=["open"])["hits"]
    loops = [h for h in hits if "state" in h]
    assert len(loops) == 1 and loops[0]["state"] == "closed" and loops[0]["date"] == "2026-06-09", hits


def test_no_match_returns_no_hits_and_stopwords_are_ignored():
    got = search("kubernetes")
    assert got["total_hits"] == 0 and got["notes_searched"] == 2, got
    assert search("what", "did", "we", "the")["query_terms"] == []


def search_error(*query, **kw) -> str:
    args = type("A", (), {"query": list(query), "vault": kw.get("vault", ROOT), "project": None,
                          "type": None, "since": kw.get("since"), "until": kw.get("until"),
                          "limit": kw.get("limit", 20)})
    with contextlib.redirect_stderr(io.StringIO()) as err, contextlib.redirect_stdout(io.StringIO()):
        assert rc.cmd_search(args) == 2
    return json.loads(err.getvalue())["error"]


def test_a_missing_vault_is_an_error_not_an_empty_answer():
    assert "no daily notes folder" in search_error("alert", vault="/does/not/exist")


def test_bad_dates_and_limits_are_rejected():
    for bad in ("2026-9-1", "yesterday", "2026-10", "2026-02-31"):
        assert "--since must be a real date" in search_error(since=bad), bad
    assert "--until must be a real date" in search_error(until="June")
    assert "--limit" in search_error("alert", limit=0)
    assert "--limit" in search_error("alert", limit=-1)


def test_words_that_cannot_be_searched_match_nothing():
    assert search("?")["total_hits"] == 0
    assert search("the", "what")["total_hits"] == 0
    assert search("the", project="notif")["total_hits"] > 0
    assert search("caf\u00e9")["query_terms"] == ["caf\u00e9"]


def test_notes_searched_counts_only_the_date_range():
    got = search(since="2026-06-05")
    assert (got["notes_in_vault"], got["notes_searched"]) == (2, 1), got


def test_project_name_alone_scores_lower_than_a_text_match():
    hits = search("notifications", "lock")["hits"]
    assert "lock each job" in hits[0]["text"], hits[0]


def main() -> int:
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print(f"OK {t.__name__}")
    print(f"\n{len(tests)} passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
