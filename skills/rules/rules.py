#!/usr/bin/env python3
"""Collect project Rule: bullets for review as CLAUDE.md suggestions."""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "shared"))
from common import (  # noqa: E402
    cfg_get, list_dated_notes, load_config, notes_repo_dir, parse_note,
    pulse_home, read_note, strip_code_blocks, utf8_stdio,
)

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "digest"))
import digest as digest_helpers  # noqa: E402


def resolve_project(cwd: str, labels: dict) -> str | None:
    """Resolve only explicitly configured folder mappings or path patterns."""
    folder = os.path.basename(os.path.normpath(cwd))
    mappings = labels.get("mappings", {})

    if folder in mappings:
        return mappings[folder]

    return digest_helpers.path_label(cwd, labels)


def collect_rules(daily_dir: str, project_label: str) -> list[dict]:
    """Collect dated Rule: bullets for one project. Learned: is intentionally excluded."""
    rules = []

    for path in list_dated_notes(daily_dir):
        date = os.path.splitext(os.path.basename(path))[0]
        note = strip_code_blocks(read_note(path))

        _, blocks = parse_note(note)
        for block in blocks:
            if (block.get("project") or "").casefold() != project_label.casefold():
                continue

            for bullet in block.get("bullets", []):
                if bullet.startswith("Rule: "):
                    rule = bullet[len("Rule: "):].strip()
                    if rule:
                        rules.append({"date": date, "rule": rule})

    return rules


def select_target_file(project_dir: str) -> str:
    """Choose the initial target. Kept separate for future target support."""
    return os.path.join(project_dir, "CLAUDE.md")


def build_payload(daily_dir: str, project_label: str, project_dir: str) -> dict:
    target = select_target_file(project_dir)
    existing = ""
    if os.path.isfile(target):
        existing = read_note(target)

    return {
        "project": project_label,
        "rules": collect_rules(daily_dir, project_label),
        "target_file": target,
        "existing_content": existing,
    }


def main() -> int:
    utf8_stdio()
    cfg = load_config()
    notes_repo = notes_repo_dir(cfg)

    if not notes_repo:
        print(
            "warning: notes_repo is not configured; no daily rules will be collected.",
            file=sys.stderr,
        )
        notes_repo = ""

    vault_subfolder = cfg_get(
        cfg, "vault_subfolder", "PULSE_VAULT_SUBFOLDER", "Pulse/Daily"
    )
    daily_dir = os.path.join(notes_repo, vault_subfolder)

    labels_path = os.path.expanduser(cfg_get(
        cfg, "project_labels", None,
        os.path.join(pulse_home(), "project-labels.yaml"),
    ))
    labels = digest_helpers.load_labels(labels_path)

    cwd = os.getcwd()
    project = resolve_project(cwd, labels)
    if not project:
        print(
            f"error: folder '{cwd}' has no project mapping. "
            f"Add its folder name or path pattern to {labels_path}.",
            file=sys.stderr,
        )
        return 1

    payload = build_payload(daily_dir, project, cwd)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
