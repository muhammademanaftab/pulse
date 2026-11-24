#!/usr/bin/env python3
"""Pulse setup.

  python3 skills/setup/install.py                         wire capture (default)
  python3 skills/setup/install.py notes --repo <path> --create   configure daily notes
  python3 skills/setup/install.py recall                  install the /pulse-recall skill
  python3 skills/setup/install.py rules                   install the /pulse-rules skill
  python3 skills/setup/install.py uninstall               remove hooks and installed skills
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
HOOKS_DIR = os.path.join(PULSE_HOME, "hooks")
HOOK_DEST = os.path.join(HOOKS_DIR, "pulse-capture.py")
LEGACY_HOOK = os.path.join(CLAUDE_DIR, "hooks", "pulse-capture.py")
SETTINGS = os.path.join(CLAUDE_DIR, "settings.json")
if os.name == "nt":
    _exe = getattr(sys, "_base_executable", None) or sys.executable
    _py, _hook = (p.replace("\\", "/") for p in (_exe, HOOK_DEST))
    HOOK_COMMAND = f'"{_py}" "{_hook}" --source claude-code || true'
else:
    HOOK_COMMAND = 'python3 ~/.pulse/hooks/pulse-capture.py --source claude-code || true'


def die(msg: str) -> None:
    print(f"\n  STOP: {msg}\n", file=sys.stderr)
    sys.exit(1)


def have(cmd: str) -> bool:
    return shutil.which(cmd) is not None


def run(args: list[str], cwd: str | None = None, timeout: int = 60) -> tuple[int, str, str]:
    resolved = shutil.which(args[0]) or args[0]
    try:
        p = subprocess.run([resolved, *args[1:]], cwd=cwd, capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=timeout)
    except subprocess.TimeoutExpired:
        return 124, "", f"'{' '.join(args)}' timed out after {timeout}s"
    return p.returncode, p.stdout.strip(), p.stderr.strip()


def check_prereqs() -> None:
    print("1. Checking prerequisites...")
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
        os.chmod(ENV_FILE, 0o600)
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
    os.makedirs(os.path.dirname(SETTINGS), exist_ok=True)
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
            for h in (group.get("hooks") if isinstance(group.get("hooks"), list) else [])
            if isinstance(h, dict) and "pulse-capture.py" in str(h.get("command", ""))]
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
    if os.path.isfile(LEGACY_HOOK) and not os.path.islink(LEGACY_HOOK):
        shutil.copy(os.path.join(HERE, "capture.py"), LEGACY_HOOK)
        print(f"   refreshed the older copy at {LEGACY_HOOK} (other settings files may still "
              "point at it; `install.py uninstall` removes it)")


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
    labels = os.path.join(PULSE_HOME, "project-labels.yaml")
    if not os.path.isfile(labels):
        shutil.copy(os.path.join(REPO, "skills", "digest", "templates", "project-labels.yaml"), labels)
        print(f"   wrote a starter label map at {labels}")
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

def cmd_rules() -> int:
    script = os.path.join(REPO, "skills", "rules", "rules.py").replace("\\", "/")
    python = f'"{_py}"' if os.name == "nt" else "python3"
    text = open(os.path.join(REPO, "skills", "rules", "SKILL.md"), encoding="utf-8").read()
    text = text.replace("name: rules", "name: pulse-rules", 1).replace(
        "python3 skills/rules/rules.py", f'{python} "{script}"')
    dest = os.path.join(CLAUDE_DIR, "skills", "pulse-rules", "SKILL.md")
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    with open(dest, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    print(f"   installed /pulse-rules at {dest}\n"
          "   it runs the script in this clone, so re-run this if you move the repo")
    return 0

def cmd_uninstall() -> int:
    removed = False
    try:
        if os.path.lexists(SETTINGS):
            try:
                with open(SETTINGS, encoding="utf-8") as f:
                    settings = json.load(f)
            except ValueError:
                die(f"{SETTINGS} is not valid JSON; fix or move it, then re-run.")
            hooks = settings.get("hooks", {}) if isinstance(settings, dict) else None
            stop = hooks.get("Stop", []) if isinstance(hooks, dict) else None
            if not isinstance(stop, list):
                die(f"{SETTINGS} has an unexpected shape (it must be an object whose `hooks` is an "
                    "object and `hooks.Stop` a list); fix or move it, then re-run.")
            kept_groups = []
            for group in stop:
                entries = group.get("hooks") if isinstance(group, dict) else None
                if not isinstance(entries, list):
                    kept_groups.append(group)
                    continue
                kept = [h for h in entries if not (
                    isinstance(h, dict) and "pulse-capture.py" in str(h.get("command", "")))]
                if len(kept) == len(entries):
                    kept_groups.append(group)
                else:
                    removed = True
                    if kept:
                        kept_groups.append({**group, "hooks": kept})
            if removed:
                settings["hooks"]["Stop"] = kept_groups
                print(f"Removed the Pulse Stop hook from {SETTINGS}{save_settings(settings)}")

        for hook in (HOOK_DEST, LEGACY_HOOK):
            if os.path.lexists(hook):
                os.unlink(hook)
                removed = True
                print(f"Removed {hook}")
        if os.path.isdir(HOOKS_DIR) and not os.listdir(HOOKS_DIR):
            os.rmdir(HOOKS_DIR)
        recall = os.path.join(CLAUDE_DIR, "skills", "pulse-recall")
        if os.path.lexists(recall):
            if os.path.islink(recall) or os.path.isfile(recall):
                os.unlink(recall)
            else:
                shutil.rmtree(recall)
            removed = True
            print(f"Removed {recall}")
        rules = os.path.join(CLAUDE_DIR, "skills", "pulse-rules")
        if os.path.lexists(rules):
            if os.path.islink(rules) or os.path.isfile(rules):
                os.unlink(rules)
            else:
                shutil.rmtree(rules)
            removed = True
            print(f"Removed {rules}")
    except OSError as e:
        die(f"could not finish uninstall: {e}")
    if not removed:
        print("nothing to remove")
    print("Kept ~/.pulse/, the Convex deployment and the notes repo; remove the local folders "
          "manually and delete the deployment in the Convex dashboard if you want to remove that data.")
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
    sub.add_parser("rules")
    sub.add_parser("uninstall")
    args = p.parse_args()
    if args.cmd == "notes":
        return cmd_notes(args)
    if args.cmd == "recall":
        return cmd_recall()
    if args.cmd == "rules":
        return cmd_rules()
    if args.cmd == "uninstall":
        return cmd_uninstall()
    return cmd_capture()


if __name__ == "__main__":
    sys.exit(main())
