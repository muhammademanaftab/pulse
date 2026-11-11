#!/usr/bin/env python3
"""Pulse setup.

  python3 skills/setup/install.py                         wire capture (default)
  python3 skills/setup/install.py notes --repo <path> --create   configure daily notes
  python3 skills/setup/install.py recall                  install the /pulse-recall skill
"""
from __future__ import annotations

import argparse
import json
import os
import re
import secrets
import shutil
import subprocess
import sys
from urllib.request import Request, urlopen

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
BACKEND = os.path.join(REPO, "backend")
PULSE_HOME = os.path.expanduser("~/.pulse")
ENV_FILE = os.path.join(PULSE_HOME, ".env")
CONFIG_FILE = os.path.join(PULSE_HOME, "config.yaml")
CONFIG_EXAMPLE = os.path.join(REPO, "config.example.yaml")
CLAUDE_DIR = os.path.expanduser("~/.claude")
HOOKS_DIR = os.path.join(CLAUDE_DIR, "hooks")
HOOK_DEST = os.path.join(HOOKS_DIR, "pulse-capture.py")
SETTINGS = os.path.join(CLAUDE_DIR, "settings.json")
if os.name == "nt":
    # python3 can be the Microsoft Store alias stub, which `|| true` would hide.
    # Claude Code runs hooks through Git Bash, so forward slashes and quotes work.
    # The base interpreter, not a venv's, so deleting a venv doesn't break capture.
    _exe = getattr(sys, "_base_executable", None) or sys.executable
    _py, _hook = (p.replace("\\", "/") for p in (_exe, HOOK_DEST))
    HOOK_COMMAND = f'"{_py}" "{_hook}" || true'
else:
    HOOK_COMMAND = 'python3 ~/.claude/hooks/pulse-capture.py || true'


def die(msg: str) -> None:
    print(f"\n  STOP: {msg}\n", file=sys.stderr)
    sys.exit(1)


def have(cmd: str) -> bool:
    return shutil.which(cmd) is not None


def run(args: list[str], cwd: str | None = None, timeout: int = 60) -> tuple[int, str, str]:
    # shutil.which finds npm.cmd/npx.cmd shims on Windows; no-op on POSIX.
    resolved = shutil.which(args[0]) or args[0]
    try:
        p = subprocess.run([resolved, *args[1:]], cwd=cwd, capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=timeout)
    except subprocess.TimeoutExpired:
        return 124, "", f"'{' '.join(args)}' timed out after {timeout}s"
    return p.returncode, p.stdout.strip(), p.stderr.strip()


def check_prereqs() -> None:
    print("1. Checking prerequisites...")
    # On Windows the hook runs with this interpreter (sys.executable), not python3.
    py = [] if os.name == "nt" else [("python3", "this script")]
    for cmd, why in py + [("node", "the Convex CLI"),
                     ("npx", "the Convex CLI"), ("git", "your notes repo")]:
        if not have(cmd):
            die(f"'{cmd}' not found (needed for {why}). Install it and re-run.")
    print(f"   ok: {'python' if os.name == 'nt' else 'python3'}, node, npx, git")


def ensure_backend_deps() -> None:
    print("2. Installing Convex backend deps (backend/)...")
    code, _, err = run(["npm", "install"], cwd=BACKEND, timeout=300)
    if code != 0:
        die(f"npm install failed in {BACKEND}:\n{err}")
    print("   ok")


def deployment_ready() -> bool:
    return os.path.isfile(os.path.join(BACKEND, ".env.local"))


def print_login_instructions() -> None:
    print(
        "\n3. Convex needs a one-time login (the only manual step).\n"
        "   Run these in your terminal, then re-run this script:\n\n"
        f"     cd {BACKEND}\n"
        "     npx convex login\n"
        "     npx convex dev --once --dev-deployment cloud\n")


def resolve_token() -> str:
    code, out, _ = run(["npx", "convex", "env", "get", "INGEST_TOKEN"], cwd=BACKEND)
    if code == 0 and out and "not found" not in out.lower():
        return out.strip().strip('"')
    token = secrets.token_hex(32)
    code, _, err = run(["npx", "convex", "env", "set", "INGEST_TOKEN", token], cwd=BACKEND)
    if code != 0:
        die(f"could not set INGEST_TOKEN on the deployment:\n{err}")
    return token


def resolve_site_url() -> str:
    code, out, _ = run(["npx", "convex", "run", "setup:siteUrl"], cwd=BACKEND)
    if code == 0 and out:
        url = out.strip().strip('"')
        if url.endswith(".convex.site"):
            return url
    envlocal = os.path.join(BACKEND, ".env.local")
    if os.path.isfile(envlocal):
        for line in open(envlocal, encoding="utf-8"):
            m = re.search(r"https://[\w-]+\.convex\.cloud", line)
            if m:
                return m.group(0).replace(".convex.cloud", ".convex.site")
    die("could not determine the .convex.site URL (run `npx convex run setup:siteUrl`)")


def write_env(url: str, token: str) -> None:
    os.makedirs(PULSE_HOME, exist_ok=True)
    content = f"CONVEX_URL={url}\nCONVEX_TOKEN={token}\n"
    if os.path.isfile(ENV_FILE) and open(ENV_FILE, encoding="utf-8").read() == content:
        os.chmod(ENV_FILE, 0o600)  # re-tighten perms even when content is current
        print(f"4. Credentials already current at {ENV_FILE}")
        return
    with open(ENV_FILE, "w", encoding="utf-8", newline="\n") as f:
        f.write(content)
    os.chmod(ENV_FILE, 0o600)
    print(f"4. Wrote credentials to {ENV_FILE}")


def save_settings(settings: dict) -> str:
    backed_up = os.path.isfile(SETTINGS)
    if backed_up:
        shutil.copy(SETTINGS, SETTINGS + ".bak")
    with open(SETTINGS, "w", encoding="utf-8", newline="\n") as f:
        json.dump(settings, f, indent=2, ensure_ascii=False)
        f.write("\n")
    return " (backup at settings.json.bak)" if backed_up else ""


def install_hook() -> None:
    settings = {}
    if os.path.isfile(SETTINGS):
        try:
            settings = json.load(open(SETTINGS, encoding="utf-8"))
        except Exception:
            die(f"{SETTINGS} is not valid JSON; fix or move it, then re-run.")
    hooks = settings.setdefault("hooks", {}) if isinstance(settings, dict) else None
    stop = hooks.setdefault("Stop", []) if isinstance(hooks, dict) else None
    if not isinstance(stop, list):
        die(f"{SETTINGS} has an unexpected shape (it must be an object whose `hooks` is an "
            "object and `hooks.Stop` a list); fix or move it, then re-run.")

    os.makedirs(HOOKS_DIR, exist_ok=True)
    shutil.copy(os.path.join(HERE, "capture.py"), HOOK_DEST)
    os.chmod(HOOK_DEST, 0o755)
    print(f"5. Copied capture script to {HOOK_DEST}")

    ours = [h for group in stop if isinstance(group, dict)
            for h in group.get("hooks", [])
            if isinstance(h, dict) and "pulse-capture.py" in h.get("command", "")]
    if any(h.get("command") != HOOK_COMMAND for h in ours):
        for h in ours:
            h["command"] = HOOK_COMMAND
        print(f"   updated the Stop hook command in {SETTINGS}{save_settings(settings)}")
    elif ours:
        print("   hook already present in settings.json (no change)")
    else:
        stop.append({"matcher": "", "hooks": [
            {"type": "command", "command": HOOK_COMMAND, "timeout": 30}]})
        print(f"   added the Stop hook to {SETTINGS}{save_settings(settings)}")


def verify(url: str, token: str) -> None:
    print("6. Verifying with a probe record...")
    payload = json.dumps({"message": "pulse install verification probe",
                          "event_id": "pulse-install-verify",
                          "project": "pulse-install", "projectPath": "/",
                          "sessionId": "install-verify"}).encode()
    req = Request(url.rstrip("/") + "/ingest", data=payload, method="POST",
                  headers={"Content-Type": "application/json",
                           "Authorization": f"Bearer {token}"})
    try:
        with urlopen(req, timeout=15) as resp:
            body = resp.read().decode()
        if '"ok":true' in body.replace(" ", ""):
            print("   ok: a record reached your Convex deployment")
        else:
            print(f"   warning: unexpected response: {body}")
    except Exception as e:
        die(f"probe POST failed: {e}\n  Check CONVEX_URL is the .site URL and the token matches.")


def cmd_capture() -> int:
    print("Pulse capture setup\n")
    check_prereqs()
    ensure_backend_deps()
    if not deployment_ready():
        print_login_instructions()
        return 0
    token = resolve_token()
    url = resolve_site_url()
    write_env(url, token)
    install_hook()
    verify(url, token)
    print("\nDone. Capture is live: every Claude Code turn now records to your Convex.\n"
          "Logs: ~/.pulse/capture.log\n")
    return 0


def detect_timezone() -> str:
    try:
        path = os.path.realpath("/etc/localtime")
        if "zoneinfo/" in path:
            return path.split("zoneinfo/", 1)[1]
    except Exception:
        pass
    print("   could not detect your timezone, using UTC; re-run with "
          "--timezone Area/City (e.g. Europe/London) to fix", file=sys.stderr)
    return "UTC"


def cmd_notes(args) -> int:
    if not have("git"):
        die("'git' not found. Install it and re-run.")
    repo = os.path.abspath(os.path.expanduser(args.repo))
    if os.path.exists(repo) and not os.path.isdir(repo):
        die(f"{repo} is a file, not a folder.")
    if args.timezone:
        try:
            from zoneinfo import available_timezones
            known = available_timezones()
        except Exception:
            known = set()
        if known and args.timezone not in known:
            die(f"unknown timezone {args.timezone!r}. Use an IANA name such as Europe/London.")
    if not os.path.isdir(repo):
        if not args.create:
            die(f"{repo} does not exist. Check the path, or add --create to make it.")
        os.makedirs(repo)
    if not os.path.exists(os.path.join(repo, ".git")):
        code, _, err = run(["git", "init", repo])
        if code != 0:
            die(f"git init failed at {repo}:\n{err}")
        run(["git", "-C", repo, "symbolic-ref", "HEAD", "refs/heads/main"])
        print(f"   initialized notes repo at {repo}")
    else:
        print(f"   using existing notes repo at {repo}")

    if not os.path.isfile(CONFIG_EXAMPLE):
        die(f"missing {CONFIG_EXAMPLE}")
    old = open(CONFIG_FILE, encoding="utf-8").read() if os.path.isfile(CONFIG_FILE) else None
    lines = (old or "").splitlines()
    key_of = lambda line: line.split(":", 1)[0].strip() if ":" in line and not line.startswith("#") else None
    have_keys = {key_of(line) for line in lines}
    wanted = {"notes_repo": f'notes_repo: "{repo}"'}
    if args.timezone or "timezone" not in have_keys:
        wanted["timezone"] = f"timezone: {args.timezone or detect_timezone()}"
    lines = [wanted.get(key_of(line), line) for line in lines]
    for line in open(CONFIG_EXAMPLE, encoding="utf-8").read().splitlines():
        if key_of(line) and key_of(line) not in have_keys:
            lines.append(wanted.get(key_of(line), line))
    content = "\n".join(lines) + "\n"

    os.makedirs(PULSE_HOME, exist_ok=True)
    if old == content:
        print(f"   config already current at {CONFIG_FILE}")
        print(repo)
        return 0
    if old is not None:
        shutil.copy(CONFIG_FILE, CONFIG_FILE + ".bak")
    with open(CONFIG_FILE, "w", encoding="utf-8", newline="\n") as f:
        f.write(content)
    print(f"   wrote {CONFIG_FILE} (notes_repo={repo}); your other settings are kept")
    print(repo)
    return 0


def cmd_recall() -> int:
    script = os.path.join(REPO, "skills", "recall", "recall.py").replace("\\", "/")
    python = f'"{_py}"' if os.name == "nt" else "python3"
    text = open(os.path.join(REPO, "skills", "recall", "SKILL.md"), encoding="utf-8").read()
    text = text.replace("name: recall", "name: pulse-recall", 1).replace(
        "python3 skills/recall/recall.py", f'{python} "{script}"')
    dest = os.path.join(CLAUDE_DIR, "skills", "pulse-recall", "SKILL.md")
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    with open(dest, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    print(f"   installed /pulse-recall at {dest}\n"
          "   it runs the script in this clone, so re-run this if you move the repo")
    return 0


def main() -> int:
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd")
    sub.add_parser("capture")
    n = sub.add_parser("notes")
    n.add_argument("--repo", required=True)
    n.add_argument("--create", action="store_true")
    n.add_argument("--timezone", default=None)
    sub.add_parser("recall")
    args = p.parse_args()
    if args.cmd == "notes":
        return cmd_notes(args)
    if args.cmd == "recall":
        return cmd_recall()
    return cmd_capture()


if __name__ == "__main__":
    sys.exit(main())
