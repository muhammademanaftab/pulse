#!/usr/bin/env python3
"""Tests for Pulse hook install and uninstall, using temporary installations only.

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
                            HOOKS_DIR=str(pulse / "hooks"),
                            HOOK_DEST=str(pulse / "hooks" / "pulse-capture.py"),
                            LEGACY_HOOK=str(claude / "hooks" / "pulse-capture.py"),
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


def install_hook():
    with contextlib.redirect_stdout(io.StringIO()) as out:
        setup.install_hook()
    return out.getvalue()


def stop_commands():
    settings = json.loads(Path(setup.SETTINGS).read_text(encoding="utf-8"))
    return [h["command"] for group in settings["hooks"]["Stop"] for h in group["hooks"]]


def test_hook_command_names_the_shared_copy_and_the_source():
    assert "pulse-capture.py" in setup.HOOK_COMMAND, setup.HOOK_COMMAND
    assert "/.pulse/hooks/" in setup.HOOK_COMMAND.replace("\\", "/"), setup.HOOK_COMMAND
    assert "/.claude/" not in setup.HOOK_COMMAND.replace("\\", "/"), setup.HOOK_COMMAND
    assert setup.HOOK_COMMAND.endswith(" --source claude-code || true"), setup.HOOK_COMMAND


def test_install_hook_on_a_fresh_machine_and_again():
    with installation():
        install_hook()
        assert Path(setup.HOOK_DEST).is_file()
        assert stop_commands() == [setup.HOOK_COMMAND]
        before = Path(setup.SETTINGS).read_bytes()
        assert "no change" in install_hook()
        assert Path(setup.SETTINGS).read_bytes() == before
        assert stop_commands() == [setup.HOOK_COMMAND]


def test_install_hook_moves_an_older_install_to_the_shared_copy():
    for legacy in ("python3 ~/.claude/hooks/pulse-capture.py || true",
                   '"C:/Python/python.exe" "C:/Users/A B/.claude/hooks/pulse-capture.py" || true'):
        with installation():
            other = {"type": "command", "command": "notify", "timeout": 17}
            original = json.dumps({"theme": "dark", "hooks": {"Stop": [{"matcher": "", "hooks": [
                {"type": "command", "command": legacy, "timeout": 30}, other]}]}})
            write(setup.SETTINGS, original)
            write(setup.LEGACY_HOOK, "synthetic capture script from an older install")
            neighbor = Path(setup.LEGACY_HOOK).parent / "other.py"
            write(neighbor, "keep this")
            install_hook()
            assert stop_commands() == [setup.HOOK_COMMAND, "notify"]
            assert Path(setup.HOOK_DEST).is_file()
            assert not Path(setup.LEGACY_HOOK).exists()
            assert neighbor.read_text(encoding="utf-8") == "keep this"
            assert Path(setup.SETTINGS + ".bak").read_text(encoding="utf-8") == original
            settings = json.loads(Path(setup.SETTINGS).read_text(encoding="utf-8"))
            assert settings["theme"] == "dark" and settings["hooks"]["Stop"][0]["hooks"][1] == other


def test_installed_copy_is_the_capture_script_in_this_repo():
    with installation():
        install_hook()
        source = REPO / "skills" / "setup" / "capture.py"
        assert Path(setup.HOOK_DEST).read_bytes() == source.read_bytes()


def test_uninstall_preserves_other_hooks_and_backs_up_settings():
    commands = (
        setup.HOOK_COMMAND,
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
        write(setup.LEGACY_HOOK, "synthetic capture script from an older install")
        write(recall / "SKILL.md", "synthetic recall skill")
        write(recall / "nested" / "extra.txt", "installed extra")
        kept = [Path(setup.ENV_FILE), Path(setup.CONFIG_FILE),
                Path(setup.PULSE_HOME) / "capture.log", root / "notes" / "note.md",
                Path(setup.HOOKS_DIR) / "other.py",
                Path(setup.LEGACY_HOOK).parent / "other.py",
                Path(setup.CLAUDE_DIR) / "skills" / "other" / "SKILL.md"]
        for path in kept:
            write(path, "keep this")
        out = uninstall()
        assert not Path(setup.HOOK_DEST).exists()
        assert not Path(setup.LEGACY_HOOK).exists()
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
