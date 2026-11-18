#!/usr/bin/env python3
"""Brag collection and citation tests using synthetic notes, stdlib only."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from unittest.mock import patch

from test_digest import GOOD, REPO, load

SCRIPT = os.path.join(REPO, "skills", "brag", "brag.py")
brag = load("brag", SCRIPT)


def write(root, relative, text):
    path = os.path.join(root, relative)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as file:
        file.write(text)
    return path


def note(root, day, text=GOOD, folder="Pulse/Daily"):
    return write(root, f"{folder}/{day[:7]}/{day}.md", text)


def collect(root, start="2026-05-31", end="2026-06-02", cfg=None):
    with patch.dict(os.environ, {"NOTES_REPO": root, "PULSE_VAULT_SUBFOLDER": "",
                                "PULSE_PROJECTS_SUBFOLDER": "", "PULSE_BRAG_SUBFOLDER": ""}):
        return brag.collect(cfg or {}, start, end)


def draft(evidence):
    source = evidence["projects"]["Web App"]["entries"][0]["source"]
    label = evidence["projects"]["Web App"]["rendered"]
    return (f"# Brag document: {evidence['start']} to {evidence['end']}\n\n"
            f"## {label}\n\n### Outcomes\n\n"
            f"- The home page opens in about 1 second instead of 4. {source}\n\n"
            f"### Decisions and reasons\n\n"
            f"- Kept sessions for 30 days because logins were the top complaint. {source}\n")


def test_inclusive_range_sources_and_project_grouping():
    with tempfile.TemporaryDirectory() as root:
        for day in ("2026-05-30", "2026-05-31", "2026-06-02", "2026-06-03", "2026-06-31"):
            note(root, day)
        write(root, "Pulse/Projects/Web App.md", "# Web App\n")
        got = collect(root)
        assert got["note_count"] == 2, got
        assert [n["date"] for n in got["notes"]] == ["2026-05-31", "2026-06-02"], got
        assert set(got["projects"]) == {"Web App", "Notifications"}, got
        project = got["projects"]["Web App"]
        assert project["rendered"] == "[[Web App]]", project
        assert got["projects"]["Notifications"]["rendered"] == "**Notifications**", got
        assert project["entries"][0]["source"] == "[[Pulse/Daily/2026-05/2026-05-31|2026-05-31]]", project
        assert "Decided: keep sessions for 30 days." in project["entries"][0]["bullets"][2], project
        assert "## Summary" in got["notes"][0]["text"], got
        assert got["output_path"] == os.path.join(root, "Pulse/Brag/2026-05-31_to_2026-06-02.md"), got
        assert not os.path.exists(got["output_path"])


def test_empty_period_and_notes_without_project_work():
    with tempfile.TemporaryDirectory() as root:
        got = collect(root)
        assert got["note_count"] == 0 and got["projects"] == {}, got
        empty = f"# Brag document: {got['start']} to {got['end']}\n\n{brag.EMPTY}\n"
        assert brag.lint_document(empty, got) == []
        note(root, "2026-06-01", "## Summary\n\nA quiet day.\n")
        got = collect(root)
        assert got["note_count"] == 1 and got["projects"] == {}, got
        assert brag.lint_document(empty, got) == []


def test_invalid_ranges_and_missing_repo_are_errors():
    with tempfile.TemporaryDirectory() as root:
        for start, end in [("2026-6-1", "2026-06-02"), ("2026-02-30", "2026-06-02"),
                           ("2026-06-03", "2026-06-02"), ("../2026-06-01", "2026-06-02")]:
            try:
                collect(root, start, end)
                assert False, (start, end)
            except ValueError:
                pass
        try:
            collect(os.path.join(root, "absent"))
            assert False, "missing repo accepted"
        except ValueError as error:
            assert "notes repo" in str(error), error


def test_custom_folders_unicode_and_fenced_examples():
    with tempfile.TemporaryDirectory() as root:
        text = GOOD.replace("Web App", "Caf\u00e9") + "\n```\n## Work log\n### **Fake**\n- Invented work.\n```\n"
        path = note(root, "2026-06-02", text, "Journal/Days")
        write(root, "Journal/Projects/Caf\u00e9.md", "# Caf\u00e9\n")
        got = collect(root, cfg={"vault_subfolder": "Journal/Days", "projects_subfolder": "Journal/Projects",
                                 "brag_subfolder": "Reviews"})
        assert got["projects"]["Caf\u00e9"]["rendered"] == "[[Caf\u00e9]]", got
        assert "Fake" not in got["projects"], got
        assert got["notes"][0]["path"] == "Journal/Days/2026-06/2026-06-02.md", got
        assert got["output_path"] == os.path.join(root, "Reviews/2026-05-31_to_2026-06-02.md")
        with open(path, encoding="utf-8") as file:
            assert file.read() == text


def test_valid_document_can_cite_multiple_days_and_omit_unsupported_categories():
    with tempfile.TemporaryDirectory() as root:
        note(root, "2026-05-31")
        note(root, "2026-06-02")
        got = collect(root)
        text = draft(got)
        assert brag.lint_document(text, got) == []
        entries = got["projects"]["Web App"]["entries"]
        text = text.replace(entries[0]["source"], entries[0]["source"] + " " + entries[1]["source"])
        assert brag.lint_document("\ufeff" + text, got) == []


def test_each_claim_needs_a_source_for_its_own_project():
    with tempfile.TemporaryDirectory() as root:
        note(root, "2026-05-31", GOOD.split("### **Notifications**")[0])
        note(root, "2026-06-02", "## Work log\n\n### **Notifications**\n\n- Fixed alerts.\n")
        got = collect(root)
        text = draft(got)
        source = got["projects"]["Web App"]["entries"][0]["source"]
        other = got["projects"]["Notifications"]["entries"][0]["source"]
        for changed in [text.replace(source, ""), text.replace(source, other),
                        text.replace(source, "[[Pulse/Daily/2026-05/2026-05-30|2026-05-30]]"),
                        text.replace(source, source + " Unsupported extra claim."),
                        text.replace(source, "[[https://example.com]]")]:
            assert brag.lint_document(changed, got), changed


def test_lint_rejects_unsourced_prose_empty_or_duplicate_sections_and_wrong_range():
    with tempfile.TemporaryDirectory() as root:
        note(root, "2026-06-02")
        got = collect(root)
        text = draft(got)
        source = got["projects"]["Web App"]["entries"][0]["source"]
        bad = [text.replace("# Brag document:", "# Review:"),
               text.replace("2026-05-31 to", "2026-05-30 to"),
               text.replace("### Outcomes", "### Plans"),
               text.replace("## **Web App**", "## **Unknown**"),
               text + "\nUnsourced achievement.\n", text + "\n### Hard bugs fixed\n",
               text + "\n## **Web App**\n", text + "\n### Outcomes\n",
               text.replace("### Outcomes", "### Hard bugs fixed"),
               text.replace("The home page opens in about 1 second instead of 4. ", ""),
               text.replace("The home page", "After leveraging data, the home page"),
               text.replace("about 1 second", "1 second\u2014measured")]
        for changed in bad:
            assert brag.lint_document(changed, got), changed
        assert source in text


def test_cli_collect_lint_errors_and_utf8():
    with tempfile.TemporaryDirectory() as root:
        path = note(root, "2026-06-02", GOOD + "\nCaf\u00e9.\n")
        env = {**os.environ, "NOTES_REPO": root, "PULSE_HOME": root, "PULSE_VAULT_SUBFOLDER": "",
               "PULSE_PROJECTS_SUBFOLDER": "", "PULSE_BRAG_SUBFOLDER": "", "PYTHONIOENCODING": "cp1252"}
        if sys.version_info < (3, 10):
            env["PYTHONWARNINGS"] = ",".join(rule for rule in env.get("PYTHONWARNINGS", "").split(",")
                                             if rule != "error::EncodingWarning")
        def run(*args):
            return subprocess.run([sys.executable, SCRIPT, *args], env=env, capture_output=True)
        result = run("collect", "--from", "2026-05-31", "--to", "2026-06-02")
        assert result.returncode == 0, result.stderr
        got = json.loads(result.stdout.decode("utf-8"))
        assert "Caf\u00e9" in got["notes"][0]["text"], got
        evidence = write(root, "evidence.json", json.dumps(got))
        document = write(root, "draft.md", draft(got))
        assert run("lint", "--evidence", evidence, document).returncode == 0
        assert run("lint", "--evidence", evidence, path).returncode == 1
        assert run("lint", "--evidence", evidence, root + "/missing.md").returncode == 1
        invalid = write(root, "bad.json", "not JSON")
        assert run("lint", "--evidence", invalid, document).returncode == 1
        for start in ("invalid", "2026-06-03"):
            result = run("collect", "--from", start, "--to", "2026-06-02")
            assert result.returncode == 2 and not result.stdout and "error" in json.loads(result.stderr), result


if __name__ == "__main__":
    tests = [value for name, value in sorted(globals().items()) if name.startswith("test_")]
    for test in tests:
        test()
        print(f"OK {test.__name__}")
    print(f"\n{len(tests)} passed")
