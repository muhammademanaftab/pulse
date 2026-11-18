#!/usr/bin/env python3
"""Collect a date range of daily notes and check a sourced brag document.

collect --from YYYY-MM-DD --to YYYY-MM-DD prints project evidence as JSON.
lint --evidence evidence.json draft.md checks layout and project citations.
Writing and factual review live in SKILL.md. No network access or note writes.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import date

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "shared"))
from common import (
    BANNED_RE, DASH_RE, cfg_get, list_dated_notes, load_config, notes_repo_dir,
    parse_note, read_note, render_label, strip_code_blocks, utf8_stdio)

CATEGORIES = ["### Outcomes", "### Decisions and reasons", "### Hard bugs fixed"]
EMPTY = "No supported accomplishments recorded for this period."
LINK_RE = re.compile(r"\[\[([^\]\n]+)\]\]")


def collect(cfg: dict, start: str, end: str) -> dict:
    for value in (start, end):
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
            raise ValueError("dates must use YYYY-MM-DD")
    first, last = date.fromisoformat(start), date.fromisoformat(end)
    if first > last:
        raise ValueError("--from must be on or before --to")
    repo = notes_repo_dir(cfg)
    if not repo or not os.path.isdir(repo):
        raise ValueError("no readable notes repo; configure notes_repo or NOTES_REPO")
    daily = cfg_get(cfg, "vault_subfolder", "PULSE_VAULT_SUBFOLDER", "Pulse/Daily")
    projects_dir = os.path.join(repo, cfg_get(
        cfg, "projects_subfolder", "PULSE_PROJECTS_SUBFOLDER", "Pulse/Projects"))
    output_dir = cfg_get(cfg, "brag_subfolder", "PULSE_BRAG_SUBFOLDER", "Pulse/Brag")
    notes, projects = [], {}
    for path in list_dated_notes(os.path.join(repo, daily)):
        stamp = os.path.basename(path)[:-3]
        try:
            day = date.fromisoformat(stamp)
        except ValueError:
            continue
        if not first <= day <= last:
            continue
        text = strip_code_blocks(read_note(path))
        _, blocks = parse_note(text)
        relative = os.path.relpath(path, repo).replace("\\", "/")
        source = f"[[{relative[:-3]}|{stamp}]]"
        notes.append({"date": stamp, "path": relative, "text": text})
        for block in blocks:
            if not block["bullets"]:
                continue
            label = block["project"]
            project = projects.setdefault(label, {
                "rendered": render_label(label, projects_dir), "entries": []})
            project["entries"].append({"date": stamp, "source": source, "bullets": block["bullets"]})
    return {"start": start, "end": end, "notes_repo_dir": repo,
            "output_path": os.path.join(repo, output_dir, f"{start}_to_{end}.md"),
            "note_count": len(notes), "notes": notes, "projects": projects}


def lint_document(raw: str, evidence: dict) -> list[str]:
    text = raw.lstrip("\ufeff").strip()
    title = f"# Brag document: {evidence['start']} to {evidence['end']}"
    lines = text.splitlines()
    if not lines or lines[0] != title:
        return [f"start with {title}"]
    if text == title + "\n\n" + EMPTY:
        return []
    projects = {"## " + value["rendered"]: value for value in evidence["projects"].values()}
    problems, seen_projects, seen_categories = [], set(), set()
    project, category, claims = None, None, 0
    project_claims = 0
    for number, line in enumerate(lines[1:], 2):
        if not line.strip():
            continue
        if DASH_RE.search(line) or BANNED_RE.search(line):
            problems.append(f"line {number}: use plain language without em/en dashes")
        if line.startswith("## "):
            if category and claims == 0:
                problems.append(f"{category} is empty")
            if project is not None and project_claims == 0:
                problems.append("project section has no claims")
            if line not in projects or line in seen_projects:
                problems.append(f"line {number}: unknown or repeated project heading")
            project = projects.get(line)
            seen_projects.add(line)
            category, claims, project_claims, seen_categories = None, 0, 0, set()
        elif line.startswith("### "):
            if category and claims == 0:
                problems.append(f"{category} is empty")
            if project is None or line not in CATEGORIES or line in seen_categories:
                problems.append(f"line {number}: unknown or repeated category")
            elif any(CATEGORIES.index(previous) > CATEGORIES.index(line)
                     for previous in seen_categories if previous in CATEGORIES):
                problems.append(f"line {number}: categories are out of order")
            category, claims = line, 0
            seen_categories.add(line)
        elif line.startswith("- ") and project is not None and category in CATEGORIES:
            claims += 1
            project_claims += 1
            links = list(LINK_RE.finditer(line))
            allowed = {entry["source"] for entry in project["entries"]}
            if not links or links[-1].end() != len(line):
                problems.append(f"line {number}: end each claim with its daily-note citation")
            if any(link.group(0) not in allowed for link in links):
                problems.append(f"line {number}: citation is not a collected source for this project")
            if not LINK_RE.sub("", line[2:]).strip():
                problems.append(f"line {number}: citation has no claim")
        else:
            problems.append(f"line {number}: expected a project, category or one-line claim")
    if category and claims == 0:
        problems.append(f"{category} is empty")
    if project is not None and project_claims == 0:
        problems.append("project section has no claims")
    if not seen_projects:
        problems.append("include a project section, or the empty-period statement")
    return problems


def cmd_collect(args) -> int:
    try:
        result = collect(load_config(), args.start, args.end)
    except (OSError, ValueError) as error:
        print(json.dumps({"error": str(error)}, ensure_ascii=False), file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False))
    return 0


def cmd_lint(args) -> int:
    try:
        with open(args.evidence, encoding="utf-8") as file:
            evidence = json.load(file)
        with open(args.draft, encoding="utf-8") as file:
            problems = lint_document(file.read(), evidence)
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as error:
        problems = [f"cannot check draft and evidence: {error}"]
    if problems:
        for problem in problems:
            print(f"FAIL: {problem}", file=sys.stderr)
        return 1
    print("OK: layout and citations; factual review is still required")
    return 0


def main() -> int:
    utf8_stdio()
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)
    collector = sub.add_parser("collect", help="read daily notes in an inclusive date range")
    collector.add_argument("--from", dest="start", required=True)
    collector.add_argument("--to", dest="end", required=True)
    collector.set_defaults(fn=cmd_collect)
    lint = sub.add_parser("lint", help="check a draft against collected project sources")
    lint.add_argument("--evidence", required=True)
    lint.add_argument("draft")
    lint.set_defaults(fn=cmd_lint)
    args = parser.parse_args()
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
