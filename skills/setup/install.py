#!/usr/bin/env python3
"""Pulse setup.

  python3 skills/setup/install.py                         wire capture (default)
  python3 skills/setup/install.py notes --repo <path> --create   configure daily notes
"""
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
BACKEND = os.path.join(REPO, "convex-backend")
PULSE_HOME = os.path.expanduser("~/.pulse")
ENV_FILE = os.path.join(PULSE_HOME, ".env")
CONFIG_FILE = os.path.join(PULSE_HOME, "config.yaml")
CONFIG_EXAMPLE = os.path.join(REPO, "config.example.yaml")
CLAUDE_DIR = os.path.expanduser("~/.claude")
HOOKS_DIR = os.path.join(CLAUDE_DIR, "hooks")
HOOK_DEST = os.path.join(HOOKS_DIR, "pulse-capture.py")
SETTINGS = os.path.join(CLAUDE_DIR, "settings.json")
HOOK_COMMAND = 'python3 ~/.claude/hooks/pulse-capture.py || true'


def die(msg: str) -> None:
    print(f"\n  STOP: {msg}\n", file=sys.stderr)
    sys.exit(1)


def have(cmd: str) -> bool:
    return shutil.which(cmd) is not None


def run(args: list[str], cwd: str | None = None) -> tuple[int, str, str]:
    p = subprocess.run(args, cwd=cwd, capture_output=True, text=True)
    return p.returncode, p.stdout.strip(), p.stderr.strip()


def check_prereqs() -> None:
    print("1. Checking prerequisites...")
    for cmd, why in [("python3", "this script"), ("node", "the Convex CLI"),
                     ("npx", "the Convex CLI"), ("git", "your notes repo"),
                     ("curl", "the verification step")]:
        if not have(cmd):
            die(f"'{cmd}' not found (needed for {why}). Install it and re-run.")
    print("   ok: python3, node, npx, git, curl")


def ensure_backend_deps() -> None:
    print("2. Installing Convex backend deps (convex-backend/)...")
    code, _, err = run(["npm", "install"], cwd=BACKEND)
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
        for line in open(envlocal):
            m = re.search(r"https://[\w-]+\.convex\.cloud", line)
            if m:
                return m.group(0).replace(".convex.cloud", ".convex.site")
    die("could not determine the .convex.site URL (run `npx convex run setup:siteUrl`)")


def write_env(url: str, token: str) -> None:
    os.makedirs(PULSE_HOME, exist_ok=True)
    content = f"CONVEX_URL={url}\nCONVEX_TOKEN={token}\n"
    if os.path.isfile(ENV_FILE) and open(ENV_FILE).read() == content:
        print(f"4. Credentials already current at {ENV_FILE}")
        return
    with open(ENV_FILE, "w") as f:
        f.write(content)
    os.chmod(ENV_FILE, 0o600)
    print(f"4. Wrote credentials to {ENV_FILE}")


def install_hook() -> None:
    os.makedirs(HOOKS_DIR, exist_ok=True)
    shutil.copy(os.path.join(HERE, "capture.py"), HOOK_DEST)
    os.chmod(HOOK_DEST, 0o755)
    print(f"5. Copied capture script to {HOOK_DEST}")

    settings = {}
    if os.path.isfile(SETTINGS):
        try:
            settings = json.load(open(SETTINGS))
        except Exception:
            die(f"{SETTINGS} is not valid JSON; fix or move it, then re-run.")
        shutil.copy(SETTINGS, SETTINGS + ".bak")

    hooks = settings.setdefault("hooks", {})
    stop = hooks.setdefault("Stop", [])
    already = any(
        "pulse-capture.py" in h.get("command", "")
        for group in stop if isinstance(group, dict)
        for h in group.get("hooks", []) if isinstance(h, dict)
    )
    if already:
        print("   hook already present in settings.json (no change)")
    else:
        stop.append({"matcher": "", "hooks": [
            {"type": "command", "command": HOOK_COMMAND, "timeout": 15000}]})
        with open(SETTINGS, "w") as f:
            json.dump(settings, f, indent=2)
        print(f"   added the Stop hook to {SETTINGS} (backup at settings.json.bak)")


def verify(url: str, token: str) -> None:
    print("6. Verifying with a probe record...")
    payload = json.dumps({"message": "pulse install verification probe",
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
    return "UTC"


def cmd_notes(args) -> int:
    if not have("git"):
        die("'git' not found. Install it and re-run.")
    repo = os.path.abspath(os.path.expanduser(args.repo))
    if args.create or not os.path.isdir(repo):
        os.makedirs(repo, exist_ok=True)
    if not os.path.isdir(os.path.join(repo, ".git")):
        code, _, err = run(["git", "init", repo])
        if code != 0:
            die(f"git init failed at {repo}:\n{err}")
        run(["git", "-C", repo, "symbolic-ref", "HEAD", "refs/heads/main"])
        print(f"   initialized notes repo at {repo}")
    else:
        print(f"   using existing notes repo at {repo}")

    tz = args.timezone or detect_timezone()
    if not os.path.isfile(CONFIG_EXAMPLE):
        die(f"missing {CONFIG_EXAMPLE}")
    out = []
    for line in open(CONFIG_EXAMPLE).read().splitlines():
        if line.startswith("timezone:"):
            out.append(f"timezone: {tz}")
        elif line.startswith("notes_repo:"):
            out.append(f"notes_repo: {repo}")
        else:
            out.append(line)
    content = "\n".join(out) + "\n"

    os.makedirs(PULSE_HOME, exist_ok=True)
    if os.path.isfile(CONFIG_FILE):
        if open(CONFIG_FILE).read() == content:
            print(f"   config already current at {CONFIG_FILE}")
            print(repo)
            return 0
        shutil.copy(CONFIG_FILE, CONFIG_FILE + ".bak")
    with open(CONFIG_FILE, "w") as f:
        f.write(content)
    print(f"   wrote {CONFIG_FILE} (notes_repo={repo}, timezone={tz})")
    print(repo)
    return 0


def main() -> int:
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd")
    sub.add_parser("capture")
    n = sub.add_parser("notes")
    n.add_argument("--repo", required=True)
    n.add_argument("--create", action="store_true")
    n.add_argument("--timezone", default=None)
    args = p.parse_args()
    if args.cmd == "notes":
        return cmd_notes(args)
    return cmd_capture()


if __name__ == "__main__":
    sys.exit(main())
