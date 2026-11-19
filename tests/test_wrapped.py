#!/usr/bin/env python3
"""Wrapped statistics tests using synthetic notes. Run this file directly."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from datetime import date, datetime, timedelta, timezone
from unittest.mock import patch

from test_digest import REPO, load

SCRIPT = os.path.join(REPO, "skills", "wrapped", "wrapped.py")
wrapped = load("wrapped", SCRIPT)


def note(root, day, body, folder="Pulse/Daily"):
    path = os.path.join(root, folder, day[:7], day + ".md")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as file:
        file.write(body)
    return path


def work(project="Web App", bullets="- Outcome: Shipped a smaller page."):
    return f"## Work log\n\n### **{project}**\n\n{bullets}\n"


def collect(root, month="2026-06", year=None, cfg=None):
    with patch.dict(os.environ, {"NOTES_REPO": root, "PULSE_VAULT_SUBFOLDER": "",
                                 "PULSE_WRAPPED_SUBFOLDER": ""}):
        return wrapped.collect(cfg or {}, month, year)


def test_month_and_year_boundaries_and_invalid_periods():
    assert wrapped.resolve_period("2024-02", None, date.today())[:2] == (date(2024, 2, 1), date(2024, 2, 29))
    assert wrapped.resolve_period(None, "2026", date.today())[:2] == (date(2026, 1, 1), date(2026, 12, 31))
    assert wrapped.resolve_period(None, None, date(2026, 1, 10))[2] == "2025-12"
    assert wrapped.resolve_period(None, "9999", date.today())[1] == date(9999, 12, 31)
    for month, year in (("2026-6", None), ("2026-13", None), ("", None), (None, "0000"),
                        (None, "26"), (None, "x"), ("2026-06", "2026")):
        try:
            wrapped.resolve_period(month, year, date.today())
            assert False, (month, year)
        except ValueError:
            pass


def test_counts_projects_once_per_day_and_ignores_other_sections_and_fences():
    with tempfile.TemporaryDirectory() as root:
        text = "## Summary\n- Outcome: Not a work bullet.\n" + work(bullets=(
            "- Outcome: Caf\u00e9 opens.\n- Decided: Use CSV. Why: simple.\n- Bug: fixed.\n"
            "- Rule: Check dates.\n- Learned: Leap years matter.\n- Untyped result.\n- Outcome:   "))
        text += "\n### [[Web App]]\n- Outcome: A second result.\n### **API**\n- Built a route.\n"
        text += "\n```\n### **Fake**\n- Outcome: Ignore.\n```\n## Other\n- Rule: Ignore.\n"
        note(root, "2026-06-01", text)
        note(root, "2026-06-02", work())
        note(root, "2026-06-03", "## Summary\nQuiet day.\n## Work log\n### **Empty**\n")
        got = collect(root)
        assert got["notes_scanned"] == 3 and got["recorded_work_days"] == 2, got
        assert [(p["project"], p["day_count"]) for p in got["projects"]] == [("Web App", 2), ("API", 1)], got
        assert got["typed_bullets"] == {"Outcome": 3, "Decided": 1, "Bug": 1, "Rule": 1, "Learned": 1}, got
        assert len(got["outcome_candidates"]) == 3, got
        assert got["outcome_candidates"][0]["citation"] == "[[Pulse/Daily/2026-06/2026-06-01|2026-06-01]]", got
        assert got["longest_streak_days"] == 2, got


def test_year_streaks_cross_months_but_do_not_include_outside_period():
    with tempfile.TemporaryDirectory() as root:
        for day in ("2025-12-31", "2026-01-01", "2026-01-30", "2026-01-31", "2026-02-01", "2026-02-02", "2027-01-01"):
            note(root, day, work())
        note(root, "2026-02-30", work())
        got = collect(root, None, "2026")
        assert got["recorded_work_days"] == 5 and got["longest_streak_days"] == 4, got
        assert got["days_by_month"]["2026-01"] == 3 and got["days_by_month"]["2026-02"] == 2, got
        assert got["busiest_months"] == ["2026-01"] and len(got["days_by_month"]) == 12, got
        assert got["busiest_weekdays"] == ["Monday", "Thursday", "Friday", "Saturday", "Sunday"], got
        assert collect(root, "2026-02")["recorded_work_days"] == 2


def test_ties_are_stable_and_project_totals_can_overlap():
    with tempfile.TemporaryDirectory() as root:
        for day in ("2026-01-01", "2026-02-01"):
            note(root, day, work("Zebra") + "\n### **Alpha**\n- Built something.\n")
        got = collect(root, None, "2026")
        assert got["busiest_months"] == ["2026-01", "2026-02"], got
        assert [p["project"] for p in got["projects"]] == ["Alpha", "Zebra"], got
        assert sum(p["day_count"] for p in got["projects"]) == 4 and got["recorded_work_days"] == 2, got


def test_loop_observations_deduplicate_repeats_and_keep_projects_separate():
    with tempfile.TemporaryDirectory() as root:
        loops = "## Open loops\n- [ ] Review. (Web App, since Jun 1)\n- [x] Earlier work. (API, since May 30)\n"
        note(root, "2026-06-01", work() + loops)
        note(root, "2026-06-02", work() + loops + "- [ ] Review. (API, since Jun 1)\n")
        note(root, "2026-06-03", work() + loops.replace("[ ]", "[X]") + "- [ ] Untagged.\n")
        note(root, "2026-06-04", work() + loops + "\n```\n- [ ] Fake loop.\n```\n")
        got = collect(root)["loops"]
        assert {k: v for k, v in got.items() if k != "observations"} == {
            "first_seen_open": 3, "first_seen_closed": 1, "closed_after_open": 1,
            "reopened": 1, "last_seen_open": 3}, got
        assert len(got["observations"]) == 6 and got["observations"][4]["event"] == "first_seen_open", got
        assert all(event["note"].startswith("Pulse/Daily/") for event in got["observations"])


def test_empty_period_and_missing_repository():
    with tempfile.TemporaryDirectory() as root:
        got = collect(root)
        assert got["recorded_work_days"] == got["notes_scanned"] == got["longest_streak_days"] == 0, got
        assert not got["busiest_months"] and not got["busiest_weekdays"] and not got["projects"], got
        assert not got["outcome_candidates"] and not got["loops"]["observations"], got
        try:
            collect(os.path.join(root, "missing"))
            assert False, "missing repository accepted"
        except ValueError as error:
            assert "notes repo" in str(error)


def test_configured_folders_and_safe_output_path():
    with tempfile.TemporaryDirectory() as root:
        path = note(root, "2026-06-01", work(), "Journal/Days")
        got = collect(root, cfg={"vault_subfolder": "Journal/Days", "wrapped_subfolder": "Reviews"})
        assert got["sources"][0]["note"] == "Journal/Days/2026-06/2026-06-01.md", got
        assert got["wrapped_note_path"] == os.path.realpath(os.path.join(root, "Reviews", "2026-06.md")), got
        assert not os.path.exists(os.path.join(root, "Reviews"))
        with open(path, encoding="utf-8") as file:
            assert file.read() == work()
        try:
            collect(root, cfg={"wrapped_subfolder": "../outside"})
            assert False, "outside draft path accepted"
        except ValueError as error:
            assert "inside" in str(error), error


def test_default_period_uses_configured_timezone():
    with tempfile.TemporaryDirectory() as root:
        instant = datetime(2026, 3, 1, 1, tzinfo=timezone.utc)
        zone = timezone(timedelta(hours=-7))
        with patch.dict(os.environ, {"NOTES_REPO": root, "PULSE_WRAPPED_SUBFOLDER": ""}), \
                patch.object(wrapped, "get_tz", return_value=zone), patch.object(wrapped, "datetime") as clock:
            clock.now.side_effect = lambda tz: instant.astimezone(tz)
            assert wrapped.collect({})["period"] == "2026-01"


def test_cli_json_utf8_errors_and_no_writes():
    with tempfile.TemporaryDirectory() as root:
        note(root, "2026-06-01", work("Caf\u00e9"))
        env = {**os.environ, "NOTES_REPO": root, "PULSE_HOME": root, "PULSE_TZ": "UTC",
               "PULSE_VAULT_SUBFOLDER": "", "PULSE_WRAPPED_SUBFOLDER": "", "PYTHONIOENCODING": "cp1252"}
        def run(*args):
            return subprocess.run([sys.executable, SCRIPT, *args], env=env, capture_output=True)
        result = run("--month", "2026-06")
        assert result.returncode == 0, result.stderr
        got = json.loads(result.stdout.decode("utf-8"))
        assert got["projects"][0]["project"] == "Caf\u00e9" and not os.path.exists(got["wrapped_note_path"]), got
        for args in (("--month", "2026-13"), ("--year", "0000")):
            result = run(*args)
            assert result.returncode == 2 and not result.stdout and "error" in json.loads(result.stderr), result
        assert run("--month", "2026-06", "--year", "2026").returncode == 2


def main():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for test in tests:
        test()
        print(f"OK {test.__name__}")
    print(f"\n{len(tests)} passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
