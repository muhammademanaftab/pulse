#!/usr/bin/env python3
"""Standup collection and lint tests, stdlib only. Run this file directly."""
from __future__ import annotations

import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
from datetime import date, datetime, timedelta, timezone
from unittest.mock import patch

from test_digest import GOOD, REPO, load

SCRIPT = os.path.join(REPO, "skills", "standup", "standup.py")
st = load("standup", SCRIPT)
DRAFT = """## Yesterday

- Web App: the home page opens in about 1 second instead of 4.
- Notifications: alerts no longer get lost.

## Today

- Web App: add the preview button to mobile.

## Blockers

- No blockers recorded.
"""


def write_note(root, day, text=GOOD, subfolder="Pulse/Daily"):
    path = os.path.join(root, subfolder, day[:7], day + ".md")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as note:
        note.write(text)
    return path


def collect(root, requested=None, today=date(2026, 6, 3), cfg=None):
    with patch.dict(os.environ, {"NOTES_REPO": root, "PULSE_VAULT_SUBFOLDER": ""}):
        return st.collect(cfg or {}, requested, today)


def test_normal_day_preserves_outcomes_and_only_unchecked_items():
    with tempfile.TemporaryDirectory() as root:
        text = GOOD + "- [x] Fixed a blocked alert. Done. (Notifications, since Jun 2)\n" \
            "- [ ] Waiting for review. (Web App, since Jun 2)\n- [ ] Untagged task.\n"
        write_note(root, "2026-06-02", text)
        got = collect(root)
        assert got["source_date"] == "2026-06-02" and got["today"] == "2026-06-03", got
        assert got["note"] == "Pulse/Daily/2026-06/2026-06-02.md", got
        assert got["projects"][0]["bullets"][0] == "Outcome: The home page opens in about 1 second instead of 4.", got
        assert got["open_items"] == [
            {"project": "Web App", "text": "Add the preview button to mobile."},
            {"project": "Web App", "text": "Waiting for review."},
            {"project": None, "text": "Untagged task."}], got
        assert "Fixed a blocked alert. Done." in got["note_text"], got


def test_day_without_open_items():
    with tempfile.TemporaryDirectory() as root:
        write_note(root, "2026-06-02", GOOD.split("## Open loops")[0] + "## Open loops\n\n- None.\n")
        assert collect(root)["open_items"] == []
        quiet = DRAFT.replace("- Web App: add the preview button to mobile.", "- No open items recorded.")
        assert st.lint_standup(quiet) == []


def test_latest_completed_note_skips_today_future_and_invalid_dates():
    with tempfile.TemporaryDirectory() as root:
        for day in ("2026-05-29", "2026-05-32", "2026-06-01", "2026-06-02"):
            write_note(root, day)
        got = collect(root, today=date(2026, 6, 1))
        assert got["source_date"] == "2026-05-29", got
        assert collect(root, "2026-06-02")["source_date"] == "2026-06-02"


def test_missing_note_and_exact_date_never_fall_back():
    with tempfile.TemporaryDirectory() as root:
        for requested in (None, "2026-06-01"):
            try:
                collect(root, requested)
                assert False, "missing note accepted"
            except ValueError as error:
                assert "no daily note" in str(error), error
        write_note(root, "2026-06-02")
        try:
            collect(root, "2026-06-01")
            assert False, "wrong date accepted"
        except ValueError as error:
            assert "for 2026-06-01" in str(error), error


def test_invalid_dates_and_missing_repo():
    with tempfile.TemporaryDirectory() as root:
        for requested in ("2026-02-30", "2026-6-2", "../2026-06-02", ""):
            try:
                collect(root, requested)
                assert False, requested
            except ValueError as error:
                assert "YYYY-MM-DD" in str(error), error
        try:
            collect(os.path.join(root, "missing"))
            assert False, "missing repo accepted"
        except ValueError as error:
            assert "notes repo" in str(error), error


def test_custom_folder_and_code_fences():
    with tempfile.TemporaryDirectory() as root:
        text = GOOD + "\n```\n## Open loops\n- [ ] Fake task.\n```\n"
        write_note(root, "2026-06-02", text, "Journal/Days")
        got = collect(root, cfg={"vault_subfolder": "Journal/Days"})
        assert got["note"] == "Journal/Days/2026-06/2026-06-02.md", got
        assert len(got["open_items"]) == 1 and "Fake task" not in got["note_text"], got


def test_collect_uses_configured_timezone_and_returns_json():
    with tempfile.TemporaryDirectory() as root:
        write_note(root, "2026-06-02")
        write_note(root, "2026-06-03")
        tz = timezone(timedelta(hours=-7))
        instant = datetime(2026, 6, 3, 1, tzinfo=timezone.utc)
        with patch.dict(os.environ, {"NOTES_REPO": root, "PULSE_VAULT_SUBFOLDER": ""}), \
                patch.object(st, "load_config", return_value={}), \
                patch.object(st, "get_tz", return_value=tz), patch.object(st, "datetime") as clock, \
                contextlib.redirect_stdout(io.StringIO()) as out:
            clock.now.side_effect = lambda zone: instant.astimezone(zone)
            write_note(root, "2026-06-01")
            assert st.cmd_collect(type("A", (), {"date": None})) == 0
        got = json.loads(out.getvalue())
        assert got["today"] == "2026-06-02" and got["source_date"] == "2026-06-01", got


def test_lint_sections_bullets_placeholders_and_style():
    assert st.lint_standup(DRAFT) == []
    assert st.lint_standup("\ufeff" + DRAFT) == []
    for text, expected in (
        (DRAFT.replace("## Today", "## Tomorrow"), "sections must be exactly"),
        (DRAFT + "\n## Extra\n\n- x\n", "sections must be exactly"),
        (DRAFT.replace("- No blockers recorded.", ""), "## Blockers is empty"),
        (DRAFT.replace("- No blockers recorded.", "No blockers recorded."), "one bullet per line"),
        ("Preamble\n\n" + DRAFT, "without a preamble"),
        (DRAFT.replace("No blockers recorded.", "<blockers>"), "template placeholder"),
        (DRAFT.replace("No blockers recorded.", "Fixed\u2014done."), "em/en dash"),
        (DRAFT.replace("No blockers recorded.", "After leveraging logs."), "AI-tell phrase")):
        problems = st.lint_standup(text)
        assert any(expected in problem for problem in problems), (expected, problems)


def test_cli_success_errors_and_utf8():
    with tempfile.TemporaryDirectory() as root:
        path = write_note(root, "2026-06-02", GOOD.replace("Web App", "Caf\u00e9"))
        env = {**os.environ, "NOTES_REPO": root, "PULSE_HOME": root,
               "PULSE_VAULT_SUBFOLDER": "", "PULSE_TZ": "UTC", "PYTHONIOENCODING": "cp1252"}
        if sys.version_info < (3, 10):
            env["PYTHONWARNINGS"] = ",".join(rule for rule in env.get("PYTHONWARNINGS", "").split(",")
                                             if rule != "error::EncodingWarning")
        def run(*args):
            return subprocess.run([sys.executable, SCRIPT, *args], env=env, capture_output=True)
        result = run("collect", "--date", "2026-06-02")
        assert result.returncode == 0 and json.loads(result.stdout.decode("utf-8"))["projects"][0]["project"] == "Caf\u00e9", result
        result = run("collect", "--date", "2026-06-01")
        assert result.returncode == 2 and not result.stdout and "no daily note" in json.loads(result.stderr)["error"], result
        result = run("collect", "--date", "bad")
        assert result.returncode == 2 and "YYYY-MM-DD" in json.loads(result.stderr)["error"], result
        draft = os.path.join(root, "standup.md")
        with open(draft, "w", encoding="utf-8") as file:
            file.write(DRAFT)
        assert run("lint", draft).returncode == 0
        assert run("lint", path).returncode == 1
        assert run("lint", os.path.join(root, "missing.md")).returncode == 1
        with open(path, encoding="utf-8") as file:
            assert file.read() == GOOD.replace("Web App", "Caf\u00e9")


def main() -> int:
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for test in tests:
        test()
        print(f"OK {test.__name__}")
    print(f"\n{len(tests)} passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
