#!/usr/bin/env python3
"""Collect dated Rule bullets for the current mapped project."""
from __future__ import annotations

import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "shared"))

from common import (  # noqa: E402
    cfg_get, load_config, list_dated_notes, notes_repo_dir,
    parse_note, pulse_home, read_note, strip_code_blocks,
)


class RulesError(Exception):
    pass


def load_project_mapping(path: str) -> dict[str, str]:
    """Read the simple mappings section of project-labels.yaml."""
    mappings = {}
    if not os.path.isfile(path):
        raise RulesError(
            f"Project label map not found: {path}. "
            "Configure Pulse notes first and add this folder under mappings."
        )

    in_mappings = False
    with open(path, encoding="utf-8") as file:
        for raw in file:
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            if not raw.startswith((" ", "\t")):
                in_mappings = line == "mappings:"
                continue
            if in_mappings and ":" in line:
                key, value = line.split(":", 1)
                key, value = key.strip().strip("'\""), value.strip().strip("'\"")
                if key and value:
                    mappings[key] = value
    return mappings


def select_target_file(project_dir: str) -> str:
    """Select the supported instruction file. Extend here for future formats."""
    return os.path.join(project_dir, "CLAUDE.md")


def collect(project_dir: str | None = None) -> dict:
    project_dir = os.path.abspath(project_dir or os.getcwd())
    folder = os.path.basename(os.path.normpath(project_dir))
    labels_path = os.path.join(pulse_home(), "project-labels.yaml")
    mappings = load_project_mapping(labels_path)

    if folder not in mappings:
        raise RulesError(
            f"Folder '{folder}' is not mapped in {labels_path}. "
            f"Add '{folder}: Your Project Name' under mappings, then retry."
        )
    project = mappings[folder]

    cfg = load_config()
    repo = notes_repo_dir(cfg)
    if not repo:
        raise RulesError(
            "Pulse notes repository is not configured. Set notes_repo in "
            "~/.pulse/config.yaml or NOTES_REPO."
        )

    daily_subfolder = cfg_get(
        cfg, "vault_subfolder", "PULSE_VAULT_SUBFOLDER", "Pulse/Daily"
    )
    daily_dir = os.path.join(repo, daily_subfolder)
    entries = []

    for path in list_dated_notes(daily_dir):
        date = os.path.splitext(os.path.basename(path))[0]
        _, blocks = parse_note(strip_code_blocks(read_note(path)))
        for block in blocks:
            if block["project"].casefold() != project.casefold():
                continue
            for bullet in block["bullets"]:
                if bullet.startswith("Rule:"):
                    rule = bullet[len("Rule:"):].strip()
                    if rule:
                        entries.append({"date": date, "rule": rule})

    target = select_target_file(project_dir)
    existing = ""
    if os.path.isfile(target):
        with open(target, encoding="utf-8") as file:
            existing = file.read()

    return {
        "project": project,
        "project_dir": project_dir,
        "target_file": target,
        "existing_content": existing,
        "rules": entries,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-dir", default=os.getcwd())
    args = parser.parse_args()
    try:
        result = collect(args.project_dir)
    except (RulesError, OSError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
