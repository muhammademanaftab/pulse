#!/usr/bin/env python3
"""Tests for the digest's note structure (skills/digest/digest.py).

Stdlib only, no test framework: plain asserts, runnable directly.

    python3 skills/digest/test_digest.py

Covers the typed-bullet lint, open-loop carry-forward, scratch-folder label
folding, the before-noon deferral, and that the weekly synth still parses the
new layout.
"""
import contextlib
import importlib.util
import io
import json
import os
import re
import tempfile
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


dg = load("digest", os.path.join(HERE, "digest.py"))
sy = load("synth", os.path.join(REPO, "skills", "synth", "synth.py"))

GOOD = """---
date: "2026-06-02"
tags: [pulse, daily]
source: claude-code
projects:
  - "[[Web App]]"
  - "Notifications"
---

# Tuesday, June 2, 2026

## Summary

Made the home page faster and fixed dropped alerts.

## Work log

### [[Web App]]

- Outcome: The home page opens in about 1 second instead of 4.
- Added a preview button. Deployed.
- Decided: keep sessions for 30 days. Why: logins were the top complaint. Rejected: 7 days.
- [ ] Add the preview button to mobile.
- Refs: PR #41, `home.tsx`

### **Notifications**

- Outcome: Alerts no longer get lost.
- Bug: some alerts never arrived. Cause: two workers took one job. Fix: lock each job (PR #42).

## Open loops

- [ ] Add the preview button to mobile. (Web App, since Jun 2)
"""


def vault_with(notes: dict[str, str]) -> str:
    """A temp daily folder; notes maps YYYY-MM-DD to note text. Returns the root."""
    root = tempfile.mkdtemp()
    for date, text in notes.items():
        d = os.path.join(root, date[:7])
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, f"{date}.md"), "w", encoding="utf-8") as f:
            f.write(text)
    return root


def note_path(root: str, date: str) -> str:
    return os.path.join(root, date[:7], f"{date}.md")


def lint(text: str, root: str | None = None, date: str = "2026-06-02") -> list[str]:
    root = root or vault_with({})
    return dg.lint_structure(text, note_path(root, date))


def assert_fails(text: str, needle: str, **kw):
    problems = lint(text, **kw)
    assert any(needle in p for p in problems), (needle, problems)


# --- lint: layout and typed bullets -----------------------------------------

def test_good_note_passes():
    assert lint(GOOD) == [], lint(GOOD)


def test_readme_example_passes_lint():
    readme = open(os.path.join(REPO, "README.md"), encoding="utf-8").read()
    example = re.search(r"```markdown\n(---\ndate:.*?)```", readme, re.S).group(1)
    assert lint(example) == [], lint(example)


def test_missing_outcome_fails():
    assert_fails(GOOD.replace("- Outcome: Alerts no longer get lost.\n", ""),
                 "first bullet must be `- Outcome: ...`")


def test_decided_needs_why():
    assert_fails(GOOD.replace(" Why: logins were the top complaint.", ""), "no `Why:`")


def test_bug_needs_cause_and_fix():
    assert_fails(GOOD.replace(" Cause: two workers took one job.", ""), "`Cause:` and `Fix:`")


def test_work_log_open_item_must_be_in_open_loops():
    assert_fails(GOOD.replace("- [ ] Add the preview button to mobile. (Web App, since Jun 2)",
                              "- None."), "open item not in ## Open loops")


def test_open_loop_needs_tag():
    assert_fails(GOOD.replace(" (Web App, since Jun 2)", ""), "has no `(Project, since Mon D)` tag")


def test_open_loops_cannot_be_empty():
    text = GOOD.replace("- [ ] Add the preview button to mobile.\n", "")
    text = text.replace("- [ ] Add the preview button to mobile. (Web App, since Jun 2)\n", "")
    assert_fails(text, "## Open loops is empty")


def test_label_must_be_in_frontmatter():
    assert_fails(GOOD.replace('  - "Notifications"\n', ""), "missing from frontmatter `projects:`")


def test_sections_in_order():
    work = GOOD[GOOD.index("## Work log"):GOOD.index("## Open loops")]
    loops = GOOD[GOOD.index("## Open loops"):]
    swapped = GOOD[:GOOD.index("## Work log")] + loops + "\n" + work
    assert_fails(swapped, "sections out of order")


def test_refs_must_be_last():
    assert_fails(GOOD.replace("- Refs: PR #41, `home.tsx`\n", "")
                 .replace("- Added a preview button. Deployed.\n",
                          "- Refs: PR #41\n- Added a preview button. Deployed.\n"),
                 "`- Refs:` must be the last bullet")


def test_hand_typed_heading_fails():
    assert_fails(GOOD.replace("### **Notifications**", "### Notifications"), "Work log heading")


def test_banned_phrase_and_dash_fail_full_lint():
    with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False, encoding="utf-8") as f:
        f.write(GOOD.replace("Added a preview button.", "Added a non-trivial preview button \u2014 nice."))
    args = type("A", (), {"notes": [f.name]})
    with contextlib.redirect_stderr(io.StringIO()) as err:
        assert dg.cmd_lint(args) == 1
    os.unlink(f.name)
    assert "non-trivial" in err.getvalue() and "em/en dash" in err.getvalue(), err.getvalue()


def test_banned_phrase_inside_code_is_fine():
    assert not dg.BANNED_RE.search(dg.strip_code("Renamed `non-trivial-check.sh`"))


# --- open loops carry forward -------------------------------------------------

PREV = GOOD.replace('date: "2026-06-02"', 'date: "2026-06-01"').replace(
    "- [ ] Add the preview button to mobile. (Web App, since Jun 2)",
    "- [ ] Add the preview button to mobile. (Web App, since Jun 2)\n"
    "- [ ] Write the release notes. (Web App, since May 20)\n"
    "- [x] Pick a session length. (Web App, since May 29, done Jun 1)")


def test_dropped_carry_item_fails():
    root = vault_with({"2026-06-01": PREV})
    assert_fails(GOOD, "open loop from 2026-06-01.md is missing", root=root)


def test_carry_item_kept_or_closed_passes():
    root = vault_with({"2026-06-01": PREV})
    kept = GOOD.replace("(Web App, since Jun 2)\n",
                        "(Web App, since Jun 2)\n- [ ] Write the release notes. (Web App, since May 20)\n", 1)
    assert lint(kept, root=root) == [], lint(kept, root=root)
    closed = kept.replace("- [ ] Write the release notes. (Web App, since May 20)",
                          "- [x] Write the release notes. (Web App, since May 20, dropped Jun 2: stale)")
    assert lint(closed, root=root) == [], lint(closed, root=root)


def run_open_loops(path: str) -> dict:
    args = type("A", (), {"note": path})
    with contextlib.redirect_stdout(io.StringIO()) as out:
        assert dg.cmd_open_loops(args) == 0
    return json.loads(out.getvalue())


def test_open_loops_json():
    root = vault_with({"2026-05-31": GOOD, "2026-06-01": PREV})
    out = run_open_loops(note_path(root, "2026-06-02"))
    assert out["previous_note"].endswith("2026-06-01.md"), out
    texts = {c["text"]: c for c in out["carry"]}
    assert set(texts) == {"Add the preview button to mobile.", "Write the release notes."}, texts
    assert texts["Write the release notes."]["age_days"] == 13, texts
    assert texts["Write the release notes."]["project"] == "Web App", texts
    assert out["legacy_next"] == [] and out["ticked_in_existing"] == [], out


def test_open_loops_keeps_hand_ticks_and_reads_legacy_next():
    legacy = "---\nx: 1\n---\n\n# Old\n\n## Summary\n\nS.\n\n## Work log\n\n## Next\n\n- Ship the beta\n"
    root = vault_with({"2026-06-01": legacy,
                       "2026-06-02": GOOD.replace("- [ ] Add the preview button to mobile. (",
                                                  "- [x] Add the preview button to mobile. (")})
    out = run_open_loops(note_path(root, "2026-06-02"))
    assert out["legacy_next"] == ["Ship the beta"], out
    assert out["carry"] == [], out
    assert out["ticked_in_existing"] == ["Add the preview button to mobile."], out


def test_since_age_wraps_the_year():
    assert dg.since_age("Dec 30", "2027-01-02") == 3
    assert dg.since_age("Jun 2", "2026-06-02") == 0
    assert dg.since_age("Foo 9", "2026-06-02") is None


# --- labels, noise folders, deferral ----------------------------------------

def test_load_labels_reads_noise_patterns():
    with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False, encoding="utf-8") as f:
        f.write('mappings:\n  web: Web App\nfallback: Misc\nnoise_patterns:\n'
                '  - regex: "^(tmp|scratch.*)$"\npath_patterns:\n'
                '  - regex: "/work/infra"\n    label: Infra\n')
    labels = dg.load_labels(f.name)
    os.unlink(f.name)
    assert labels["noise_patterns"] == [{"regex": "^(tmp|scratch.*)$"}], labels
    assert labels["path_patterns"] == [{"regex": "/work/infra", "label": "Infra"}], labels
    assert labels["mappings"] == {"web": "Web App"}, labels


def test_noise_folder_takes_session_label():
    labels = {"mappings": {"web": "Web App"}, "fallback": "Misc",
              "noise_patterns": [{"regex": "^(tmp|scratch.*)$"}],
              "path_patterns": [{"regex": "/work/infra/", "label": "Infra"}]}
    # Capture sets `project` to the folder (repo) name, as it does for real rows.
    ev = lambda ts, cwd, session: {"ts": ts, "cwd": cwd, "session": session,
                                   "project": re.split(r"[/\\]", cwd)[-1]}
    events = [
        ev(100, "/home/u/web", "s1"),
        ev(200, "/tmp", "s1"),                     # nearest real row in s1 -> Web App
        ev(300, "/home/u/api", "s2"),
        ev(900, "/home/u/scratch-2", "s2"),        # -> api
        ev(400, "/work/infra/tmp", "s3"),          # path_patterns on the full path wins
        ev(500, "C:\\Users\\u\\tmp", "s4"),        # Windows path, no real row -> fallback
    ]
    assert dg.resolve_labels(events, labels) == ["Web App", "Web App", "api", "api", "Infra", "Misc"]


def test_defer_today_before_noon_only():
    morning, evening = datetime(2026, 6, 2, 9), datetime(2026, 6, 2, 18)
    assert dg.defer_today("2026-06-02", morning, False)
    assert not dg.defer_today("2026-06-02", morning, True)
    assert not dg.defer_today("2026-06-02", evening, False)
    assert not dg.defer_today("2026-06-01", morning, False)


# --- the weekly synth still reads the new layout ----------------------------

def test_synth_parses_new_layout():
    summary, blocks = sy.parse_note(GOOD)
    assert summary.startswith("Made the home page faster"), summary
    assert [(b["project"], b["bold"]) for b in blocks] == [("Web App", False), ("Notifications", True)]
    assert blocks[0]["bullets"][0].startswith("Outcome: "), blocks[0]["bullets"]
    assert len(blocks[1]["bullets"]) == 2, blocks[1]["bullets"]


def main() -> int:
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print(f"OK {t.__name__}")
    print(f"\n{len(tests)} passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
