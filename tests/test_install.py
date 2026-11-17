#!/usr/bin/env python3
"""Tests for Pulse uninstall, using temporary installations only.

    python3 tests/test_install.py
"""
from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch

REPO = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("install", REPO / "skills" / "setup" / "install.py")
setup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(setup)


@contextlib.contextmanager
def installation():
    with tempfile.TemporaryDirectory() as root:
        root = Path(root)
        claude = root / "a b" / ".claude"
        pulse = root / ".pulse"
        with patch.multiple(setup, CLAUDE_DIR=str(claude),
                            HOOKS_DIR=str(claude / "hooks"),
                            HOOK_DEST=str(claude / "hooks" / "pulse-capture.py"),
                            SETTINGS=str(claude / "settings.json"),
                            PULSE_HOME=str(pulse), ENV_FILE=str(pulse / ".env"),
                            CONFIG_FILE=str(pulse / "config.yaml")):
            yield root


def write(path, text):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def uninstall():
    with patch.object(sys, "argv", ["install.py", "uninstall"]), \
            contextlib.redirect_stdout(io.StringIO()) as out:
        assert setup.main() == 0
    return out.getvalue()


def test_uninstall_preserves_other_hooks_and_backs_up_settings():
    commands = (
        "python3 ~/.claude/hooks/pulse-capture.py || true",
        '"C:/Python/python.exe" "C:/Users/A B/.claude/hooks/pulse-capture.py" || true',
    )
    for command in commands:
        with installation():
            other = {"type": "command", "command": "notify", "timeout": 17}
            unrelated = {"matcher": "other", "hooks": [{"type": "prompt", "prompt": "done?"}]}
            settings = {
                "permissions": {"allow": ["Read"]},
                "hooks": {
                    "Stop": [
                        {"matcher": "", "timeout": 40, "hooks": [
                            {"type": "command", "command": command}, other]},
                        {"matcher": "", "hooks": [{"type": "command", "command": command}]},
                        unrelated,
                    ],
                    "SessionStart": [{"hooks": [{"type": "command", "command": "hello"}]}],
                },
            }
            original = json.dumps(settings, indent=4) + "\n"
            write(setup.SETTINGS, original)
            out = uninstall()
            settings["hooks"]["Stop"] = [
                {"matcher": "", "timeout": 40, "hooks": [other]}, unrelated]
            assert json.loads(Path(setup.SETTINGS).read_text(encoding="utf-8")) == settings
            assert Path(setup.SETTINGS + ".bak").read_text(encoding="utf-8") == original
            assert "nothing to remove" not in out, out


def test_uninstall_removes_installed_files_and_keeps_user_data():
    with installation() as root:
        recall = Path(setup.CLAUDE_DIR) / "skills" / "pulse-recall"
        write(setup.HOOK_DEST, "synthetic capture script")
        write(recall / "SKILL.md", "synthetic recall skill")
        write(recall / "nested" / "extra.txt", "installed extra")
        kept = [Path(setup.ENV_FILE), Path(setup.CONFIG_FILE),
                Path(setup.PULSE_HOME) / "capture.log", root / "notes" / "note.md",
                Path(setup.HOOKS_DIR) / "other.py",
                Path(setup.CLAUDE_DIR) / "skills" / "other" / "SKILL.md"]
        for path in kept:
            write(path, "keep this")
        out = uninstall()
        assert not Path(setup.HOOK_DEST).exists()
        assert not recall.exists()
        assert not Path(setup.SETTINGS).exists()
        assert all(path.read_text(encoding="utf-8") == "keep this" for path in kept)
        assert "Kept" in out and "Convex" in out and "manually" in out, out


def test_uninstall_twice_changes_nothing_the_second_time():
    with installation():
        original = json.dumps({"hooks": {"Stop": [{"hooks": [
            {"command": "python3 pulse-capture.py"}]}]}})
        write(setup.SETTINGS, original)
        write(setup.HOOK_DEST, "synthetic capture script")
        uninstall()
        paths = [Path(setup.SETTINGS), Path(setup.SETTINGS + ".bak")]
        before = [(p.read_bytes(), p.stat().st_mtime_ns) for p in paths]
        assert "nothing to remove" in uninstall()
        assert [(p.read_bytes(), p.stat().st_mtime_ns) for p in paths] == before


def test_uninstall_without_an_installation_creates_nothing():
    with installation() as root:
        assert "nothing to remove" in uninstall()
        assert list(root.iterdir()) == []


def test_uninstall_without_pulse_preserves_settings_bytes():
    for settings in ({"theme": "dark"}, {"hooks": {}}, {"hooks": {"Stop": []}},
                     {"hooks": {"Stop": ["unknown", {"hooks": "unknown"}, {"hooks": []}]}}):
        with installation():
            original = json.dumps(settings, indent=4) + "\n"
            write(setup.SETTINGS, original)
            assert "nothing to remove" in uninstall()
            assert Path(setup.SETTINGS).read_text(encoding="utf-8") == original
            assert not Path(setup.SETTINGS + ".bak").exists()


def test_uninstall_invalid_settings_leaves_installation_intact():
    for original in ("not JSON", "[]", '{"hooks": []}', '{"hooks": {"Stop": {}}}'):
        with installation():
            write(setup.SETTINGS, original)
            write(setup.HOOK_DEST, "synthetic capture script")
            with contextlib.redirect_stderr(io.StringIO()):
                try:
                    uninstall()
                except SystemExit as error:
                    assert error.code == 1, error.code
                else:
                    raise AssertionError("invalid settings must stop uninstall")
            assert Path(setup.SETTINGS).read_text(encoding="utf-8") == original
            assert Path(setup.HOOK_DEST).exists()
            assert not Path(setup.SETTINGS + ".bak").exists()


def test_uninstall_unlinks_recall_without_following_symlink():
    with installation() as root:
        target = root / "kept-skill"
        write(target / "SKILL.md", "keep this")
        recall = Path(setup.CLAUDE_DIR) / "skills" / "pulse-recall"
        recall.parent.mkdir(parents=True)
        try:
            recall.symlink_to(target, target_is_directory=True)
        except OSError:
            if os.name == "nt":
                return
            raise
        uninstall()
        assert not recall.is_symlink()
        assert (target / "SKILL.md").read_text(encoding="utf-8") == "keep this"


def main() -> int:
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for test in tests:
        test()
        print(f"OK {test.__name__}")
    print(f"\n{len(tests)} passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
