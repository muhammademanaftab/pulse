#!/usr/bin/env python3
"""Collect dated Rule bullets for the current Git project."""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from typing import Optional

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "shared"))

from common import (  # noqa: E402
    cfg_get,
    load_config,
    list_dated_notes,
    load_labels,
    notes_repo_dir,
    parse_note,
    path_label,
    pulse_home,
    read_note,
    strip_code_blocks,
    utf8_stdio,
)


class RulesError(Exception):
    pass


def git_root(project_dir: str) -> str:
    """Return the Git repository root, or project_dir outside a Git repo."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=project_dir,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            check=True,
        )
        return os.path.abspath(result.stdout.strip())
    except (OSError, subprocess.CalledProcessError):
        return project_dir


def select_target_file(project_dir: str) -> str:
    """Select the supported instruction file; keep this separate from collection."""
    return os.path.join(project_dir, "CLAUDE.md")


def collect(project_dir: Optional[str] = None) -> dict:
    project_dir = os.path.abspath(project_dir or os.getcwd())
    project_dir = git_root(project_dir)

    folder = os.path.basename(os.path.normpath(project_dir))
    cfg = load_config()
    labels_path = cfg_get(
        cfg, "project_labels", None,
        os.path.join(pulse_home(), "project-labels.yaml")
    )
    labels = load_labels(os.path.expanduser(labels_path))

    # Prefer an explicit mapping, then a matching path pattern, then the
    # repository folder name. Unmapped projects must still work.
    project = labels.get("mappings", {}).get(folder)
    if not project:
        project = path_label(project_dir, labels)
    if not project:
        project = folder

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
    available_labels = set()
    matching_block_found = False

    for path in list_dated_notes(daily_dir):
        date = os.path.splitext(os.path.basename(path))[0]
        _, blocks = parse_note(strip_code_blocks(read_note(path)))

        for block in blocks:
            label = block["project"]
            available_labels.add(label)

            if label.casefold() != project.casefold():
                continue

            matching_block_found = True
            for bullet in block["bullets"]:
                if bullet.startswith("Rule:"):
                    rule = bullet[len("Rule:"):].strip()
                    if rule:
                        entries.append({"date": date, "rule": rule})

    if not matching_block_found:
        available = ", ".join(sorted(available_labels)) or "(none found)"
        raise RulesError(
            f"No daily-note project blocks found for '{project}'. "
            f"Available project labels: {available}"
        )

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
        "available_labels": sorted(available_labels),
    }


def main() -> int:
    utf8_stdio()
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
