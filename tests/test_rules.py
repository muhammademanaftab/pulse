import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "skills" / "rules"))
import rules


def make_environment(root, notes, claude=""):
    root = Path(root)
    project = root / "demo"
    project.mkdir(parents=True)

    pulse = root / "pulse"
    pulse.mkdir()
    (pulse / "project-labels.yaml").write_text(
        "mappings:\n  demo: Demo App\n", encoding="utf-8"
    )

    vault = root / "vault"
    for date, bullets in notes.items():
        daily = vault / "Pulse" / "Daily" / date[:7]
        daily.mkdir(parents=True, exist_ok=True)
        content = (
            "# Daily note\n\n"
            "## Summary\n\nWork completed.\n\n"
            "## Work log\n\n"
            "### **Demo App**\n"
            + "".join(f"- {bullet}\n" for bullet in bullets)
        )
        (daily / f"{date}.md").write_text(content, encoding="utf-8")

    (project / "CLAUDE.md").write_text(claude, encoding="utf-8")

    return project, pulse, vault


def collect_in(root, notes, claude=""):
    project, pulse, vault = make_environment(root, notes, claude)
    with (
        patch.object(rules, "pulse_home", return_value=str(pulse)),
        patch.object(rules, "load_config", return_value={}),
        patch.object(rules, "notes_repo_dir", return_value=str(vault)),
        patch.object(
            rules, "cfg_get",
            side_effect=lambda cfg, key, env, default: default
        ),
    ):
        return rules.collect(str(project))


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


if __name__ == "__main__":
    tests = [
        test_collects_rules_and_excludes_learned,
        test_project_with_no_rules,
        test_same_rule_on_two_days_keeps_both_dates,
        test_existing_claude_file_is_returned_unchanged,
    ]
    for test in tests:
        test()
        print(f"PASS {test.__name__}")
    print(f"OK {len(tests)} tests")
