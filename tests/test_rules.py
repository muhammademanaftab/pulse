import os
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "skills" / "rules"))
import rules


def make_environment(
    root, notes, claude="", project_label="Demo App", labels_content=None
):
    root = Path(root)
    project = root / "demo"
    project.mkdir(parents=True)

    pulse = root / "pulse"
    pulse.mkdir()
    (pulse / "project-labels.yaml").write_text(
        labels_content or "mappings:\n  demo: Demo App\n", encoding="utf-8"
    )

    vault = root / "vault"
    for date, bullets in notes.items():
        daily = vault / "Pulse" / "Daily" / date[:7]
        daily.mkdir(parents=True, exist_ok=True)
        content = (
            "# Daily note\n\n"
            "## Summary\n\nWork completed.\n\n"
            "## Work log\n\n"
            f"### **{project_label}**\n"
            + "".join(f"- {bullet}\n" for bullet in bullets)
        )
        (daily / f"{date}.md").write_text(content, encoding="utf-8")

    (project / "CLAUDE.md").write_text(claude, encoding="utf-8")

    return project, pulse, vault


def collect_in(
    root,
    notes,
    claude="",
    labels_path=None,
    project_label="Demo App",
    labels_content=None,
    git_subfolder=False,
):
    project, pulse, vault = make_environment(
        root, notes, claude, project_label, labels_content
    )
    start_dir = project
    if git_subfolder:
        subprocess.run(
            ["git", "init", str(project)],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        start_dir = project / "src"
        start_dir.mkdir()
    with patch.object(rules, "pulse_home", return_value=str(pulse)):
        with patch.object(rules, "load_config", return_value={}):
            with patch.object(rules, "notes_repo_dir", return_value=str(vault)):
                with patch.object(
                    rules, "cfg_get",
                    side_effect=lambda cfg, key, env, default: (
                        labels_path if key == "project_labels" and labels_path else default
                    ),
                ):
                    return rules.collect(str(start_dir))


def test_collects_rules_and_excludes_learned():
    with tempfile.TemporaryDirectory() as tmp:
        result = collect_in(tmp, {
            "2026-11-21": [
                "Rule: Add tests for every bug fix.",
                "Learned: The test suite uses pytest.",
            ]
        })
        assert result["project"] == "Demo App"
        assert result["rules"] == [{
            "date": "2026-11-21",
            "rule": "Add tests for every bug fix.",
        }]



def test_configured_project_labels_path_and_path_pattern():
    with tempfile.TemporaryDirectory() as tmp:
        custom_labels = Path(tmp) / "custom-labels.yaml"
        custom_labels.write_text(
            "path_patterns:\n  - regex: 'demo$'\n    label: Demo Path\n",
            encoding="utf-8",
        )
        result = collect_in(
            tmp,
            {"2026-11-21": ["Rule: Keep functions small."]},
            labels_path=str(custom_labels),
            project_label="Demo Path",
        )
        assert result["project"] == "Demo Path"
        assert result["rules"] == [{
            "date": "2026-11-21",
            "rule": "Keep functions small.",
        }]


def test_subfolder_uses_git_repository_label():
    with tempfile.TemporaryDirectory() as tmp:
        result = collect_in(
            tmp,
            {"2026-11-21": ["Rule: Keep functions small."]},
            git_subfolder=True,
        )
        assert result["project"] == "Demo App"
        assert result["project_dir"] == str(Path(tmp) / "demo")


def test_unmapped_folder_uses_its_folder_name():
    with tempfile.TemporaryDirectory() as tmp:
        result = collect_in(
            tmp,
            {"2026-11-21": ["Rule: Keep functions small."]},
            project_label="demo",
            labels_content="mappings: {}" + "\n",
        )
        assert result["project"] == "demo"


def test_missing_project_block_lists_available_labels():
    with tempfile.TemporaryDirectory() as tmp:
        try:
            collect_in(
                tmp,
                {"2026-11-21": ["Rule: Keep functions small."]},
                project_label="Other Project",
            )
        except rules.RulesError as error:
            assert "Other Project" in str(error)
            assert "Available project labels: Other Project" in str(error)
        else:
            raise AssertionError("Expected RulesError for a missing project block")


def test_project_with_no_rules():
    with tempfile.TemporaryDirectory() as tmp:
        result = collect_in(tmp, {
            "2026-11-21": ["Learned: The project uses Python."]
        })
        assert result["rules"] == []


def test_same_rule_on_two_days_keeps_both_dates():
    with tempfile.TemporaryDirectory() as tmp:
        result = collect_in(tmp, {
            "2026-11-20": ["Rule: Keep functions small."],
            "2026-11-21": ["Rule: Keep functions small."],
        })
        assert result["rules"] == [
            {"date": "2026-11-20", "rule": "Keep functions small."},
            {"date": "2026-11-21", "rule": "Keep functions small."},
        ]


def test_existing_claude_file_is_returned_unchanged():
    existing = "# Project instructions\n\n- Keep functions small.\n"
    with tempfile.TemporaryDirectory() as tmp:
        result = collect_in(
            tmp,
            {"2026-11-21": ["Rule: Keep functions small."]},
            claude=existing,
        )
        assert result["existing_content"] == existing
        assert result["rules"] == [{
            "date": "2026-11-21",
            "rule": "Keep functions small.",
        }]


def main() -> int:
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for test in tests:
        test()
        print(f"OK {test.__name__}")
    print(f"\n{len(tests)} passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
