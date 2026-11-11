#!/usr/bin/env python3
"""Tests for the weekly synth (skills/synth/synth.py).

Stdlib only, no test framework: plain asserts, runnable directly.

    python3 tests/test_synth.py

Covers that the synth parses the digest's daily-note layout and reports each
open loop's latest state for the week.
"""
from __future__ import annotations

import contextlib
import io
import json
import os
import sys
import tempfile

from test_digest import GOOD, REPO, load, note_path

sy = load("synth", os.path.join(REPO, "skills", "synth", "synth.py"))


def test_synth_parses_new_layout():
    summary, blocks = sy.parse_note(GOOD)
    assert summary.startswith("Made the home page faster"), summary
    assert [(b["project"], b["bold"]) for b in blocks] == [("Web App", False), ("Notifications", True)]
    assert blocks[0]["bullets"][0].startswith("Outcome: "), blocks[0]["bullets"]
    assert len(blocks[1]["bullets"]) == 2, blocks[1]["bullets"]


def test_synth_reports_latest_loop_state_for_the_week():
    root = tempfile.mkdtemp()
    days = {"2026-06-08": "- [ ] Ship it. (Web App (beta), since Jun 8)\n- [ ] Call Sam. (Web App, since Jun 8)",
            "2026-06-09": "- [x] Ship it. (Web App (beta), since Jun 8, done Jun 9)\n"
                          "- [ ] Call Sam. (Web App, since Jun 8)",
            "2026-06-10": "- [ ] Call Sam. (Web App, since Jun 8; tried Jun 10)"}
    for date, loops in days.items():
        os.makedirs(os.path.join(root, date[:7]), exist_ok=True)
        with open(note_path(root, date), "w", encoding="utf-8") as f:
            f.write(GOOD.split("## Open loops")[0] + "## Open loops\n\n" + loops + "\n")
    week = os.path.join(root, "week.json")
    with open(week, "w", encoding="utf-8") as f:
        json.dump({"notes_repo_dir": root, "notes": [f"{d[:7]}/{d}.md" for d in days]}, f)
    with contextlib.redirect_stdout(io.StringIO()) as out:
        sy.cmd_buckets(type("A", (), {"week_json": week, "projects_dir": None}))
    assert json.loads(out.getvalue())["open_loops"] == [
        "- [x] Ship it. (Web App (beta), since Jun 8, done Jun 9)",
        "- [ ] Call Sam. (Web App, since Jun 8; tried Jun 10)"]


def buckets_of(notes: dict[str, str | bytes]) -> tuple[int, dict | None]:
    root = tempfile.mkdtemp()
    for date, text in notes.items():
        os.makedirs(os.path.join(root, date[:7]), exist_ok=True)
        with open(note_path(root, date), "wb") as f:
            f.write(text if isinstance(text, bytes) else text.encode("utf-8"))
    week = os.path.join(root, "week.json")
    with open(week, "w", encoding="utf-8") as f:
        json.dump({"notes_repo_dir": root, "notes": [f"{d[:7]}/{d}.md" for d in notes]}, f)
    with contextlib.redirect_stdout(io.StringIO()) as out, contextlib.redirect_stderr(io.StringIO()):
        code = sy.cmd_buckets(type("A", (), {"week_json": week, "projects_dir": None}))
    return code, json.loads(out.getvalue()) if code == 0 else None


def test_buckets_ignores_fenced_code():
    fenced = GOOD.replace("- Added a preview button. Deployed.",
                          "- Added a preview button. Deployed.\n```\n### **Ghost**\n- ghost bullet\n"
                          "## Summary\nfake summary\n```")
    _, out = buckets_of({"2026-06-09": fenced})
    assert sorted(out["buckets"]) == ["Notifications", "Web App"], sorted(out["buckets"])
    assert out["daily_summaries"][0]["summary"] == "Made the home page faster and fixed dropped alerts."


def test_buckets_reads_a_note_with_bad_bytes():
    code, out = buckets_of({"2026-06-09": GOOD.encode("utf-8").replace(b"faster", b"fast\xe9r")})
    assert code == 0 and "Web App" in out["buckets"], out


def test_buckets_fails_when_a_listed_note_is_missing():
    root = tempfile.mkdtemp()
    week = os.path.join(root, "week.json")
    with open(week, "w", encoding="utf-8") as f:
        json.dump({"notes_repo_dir": root, "notes": ["2026-06/2026-06-09.md"]}, f)
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()) as err:
        assert sy.cmd_buckets(type("A", (), {"week_json": week, "projects_dir": None})) == 1
    assert "were not found" in err.getvalue(), err.getvalue()


def coverage(labels: list[str], body: str) -> int:
    root = tempfile.mkdtemp()
    with open(os.path.join(root, "b.json"), "w", encoding="utf-8") as f:
        json.dump({"buckets": {label: {} for label in labels}}, f)
    with open(os.path.join(root, "w.md"), "w", encoding="utf-8") as f:
        f.write("---\ntype: weekly\n---\n\n# Week\n\nHeadline about June.\n\n" + body +
                "\n## Sources\n\nx\n\n---\n\nPart of [[Pulse Weekly 2026-06|June 2026]]\n")
    args = type("A", (), {"buckets": os.path.join(root, "b.json"),
                          "weekly_note": os.path.join(root, "w.md"), "ignore": None})
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        return sy.cmd_coverage(args)


def test_coverage_needs_the_project_at_the_start_of_a_bullet():
    worked = "## What you worked on\n\n- **Web App** (2 days): it now talks to the Billing API.\n"
    assert coverage(["Web App", "Billing API"], worked) == 1
    assert coverage(["Web App", "Pulse"], worked) == 1
    assert coverage(["Web App", "June"], worked) == 1
    skipped = worked + "\n## What I skipped (and why)\n\n- Billing API (1 day): one quiet mention\n"
    assert coverage(["Web App", "Billing API", "Misc"], skipped) == 0
    assert coverage(["Infra (Terraform)"], "## What you worked on\n\n- [[Infra (Terraform)]] (1 day): x\n") == 0


def test_default_week_is_the_last_finished_one_even_on_a_sunday():
    import datetime as real
    common = sys.modules["common"]

    class FakeDatetime(real.datetime):
        today = None

        @classmethod
        def now(cls, tz=None):
            return cls.today

    old = common.datetime
    common.datetime = FakeDatetime
    try:
        for today, want in ((real.datetime(2026, 7, 5, 23), "2026-06-28"),
                            (real.datetime(2026, 7, 6, 8), "2026-07-05"),
                            (real.datetime(2026, 7, 9, 8), "2026-07-05")):
            FakeDatetime.today = today
            assert sy.resolve_week_end(None, None).isoformat() == want, (today, want)
    finally:
        common.datetime = old


def test_week_end_must_be_a_sunday():
    assert sy.resolve_week_end("2026-06-14", None).isoformat() == "2026-06-14"
    with contextlib.redirect_stderr(io.StringIO()) as err:
        try:
            sy.resolve_week_end("2026-07-01", None)
            raise AssertionError("a Wednesday was accepted")
        except SystemExit:
            pass
    assert "ends 2026-07-05" in err.getvalue(), err.getvalue()


def main() -> int:
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print(f"OK {t.__name__}")
    print(f"\n{len(tests)} passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
