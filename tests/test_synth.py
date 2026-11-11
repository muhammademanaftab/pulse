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


def main() -> int:
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print(f"OK {t.__name__}")
    print(f"\n{len(tests)} passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
