#!/usr/bin/env python3
"""Pulse capture hook (L0).

Runs as a Claude Code `Stop` hook. Reads the session transcript, extracts the
last real user prompt and the assistant's response, and POSTs one
schema-compliant event to the user's Convex deployment at `{CONVEX_URL}/ingest`.

Credentials live in `~/.pulse/.env` (written by skills/setup/install.py):

    CONVEX_URL=https://<deployment>.convex.site   # the .site URL, not .cloud
    CONVEX_TOKEN=<the deployment's INGEST_TOKEN>

Local-first to install and dependency-free: standard library only, no pip
install. Never raises into the session: all work is wrapped, failures are logged
to ~/.pulse/capture.log, and the hook always exits 0 with no stdout. If the env
file is missing (capture not set up yet), it no-ops cleanly.
"""
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from urllib.request import Request, urlopen

ENV_FILE = os.path.expanduser("~/.pulse/.env")
LOG_FILE = os.path.expanduser("~/.pulse/capture.log")

FILTERED_TOOL_FIELDS = {"content", "old_string", "new_string"}
AUTO_INJECTED_PREFIXES = (
    "<task-notification>",
    "<user-prompt-submit-hook>",
    "<system-reminder>",
    "<command-message>",
    "<command-name>",
    "<local-command-stdout>",
    "[Image: source:",
)


# --- credentials + logging --------------------------------------------------

def log(msg: str) -> None:
    try:
        os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
        with open(LOG_FILE, "a") as f:
            f.write(f"[{datetime.now(timezone.utc).isoformat()}] {msg}\n")
    except Exception:
        pass


def load_env() -> tuple[str | None, str | None]:
    """Read CONVEX_URL and CONVEX_TOKEN from ~/.pulse/.env. Returns (None, None)
    if the file or either key is absent (capture not configured yet)."""
    if not os.path.isfile(ENV_FILE):
        return None, None
    url = token = None
    try:
        with open(ENV_FILE) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                k, v = k.strip(), v.strip().strip('"').strip("'")
                if k == "CONVEX_URL":
                    url = v
                elif k == "CONVEX_TOKEN":
                    token = v
    except Exception as e:
        log(f"env read error: {e}")
    return url, token


# --- transcript parsing -----------------------------------------------------

def get_git_info(cwd: str) -> tuple[str, str]:
    repo_name = os.path.basename(cwd.rstrip("/")) or "unknown"
    username = os.environ.get("USER", "unknown")
    try:
        r = subprocess.run(
            ["git", "-C", cwd, "rev-parse", "--show-toplevel"],
            capture_output=True, text=True, timeout=2,
        )
        if r.returncode == 0 and r.stdout.strip():
            repo_name = os.path.basename(r.stdout.strip())
    except Exception:
        pass
    try:
        r = subprocess.run(
            ["git", "-C", cwd, "config", "user.name"],
            capture_output=True, text=True, timeout=2,
        )
        if r.returncode == 0 and r.stdout.strip():
            username = r.stdout.strip()
    except Exception:
        pass
    return repo_name, username


def is_user_typed_text(text: str) -> bool:
    s = text.strip()
    if not s:
        return False
    return not any(s.startswith(p) for p in AUTO_INJECTED_PREFIXES)


def extract_user_text(entry: dict) -> str | None:
    msg = entry.get("message", {})
    content = msg.get("content")
    if isinstance(content, str):
        return content if is_user_typed_text(content) else None
    if isinstance(content, list):
        parts = []
        for block in content:
            if not isinstance(block, dict) or block.get("type") != "text":
                continue
            text = block.get("text", "")
            if is_user_typed_text(text):
                parts.append(text)
        return "\n".join(parts) if parts else None
    return None


def render_assistant(parsed: list[dict], start: int) -> tuple[str, str | None]:
    parts: list[str] = []
    model: str | None = None
    enqueue_count = 0
    task_noti_count = 0
    last_was_task_noti = False

    for i in range(start + 1, len(parsed)):
        entry = parsed[i]
        et = entry.get("type", "")
        if et == "assistant":
            last_was_task_noti = False
            if model is None:
                model = entry.get("message", {}).get("model")
            for b in entry.get("message", {}).get("content", []):
                if not isinstance(b, dict):
                    continue
                bt = b.get("type", "")
                if bt == "thinking":
                    parts.append(f"<thinking>\n{b.get('thinking', '')}\n</thinking>\n")
                elif bt == "text":
                    parts.append(f"{b.get('text', '')}\n")
                elif bt == "tool_use":
                    name = b.get("name", "")
                    parts.append(f'<tool_use name="{name}">')
                    inp = b.get("input", {})
                    if isinstance(inp, dict):
                        kept = [f"{k}: {v}" for k, v in inp.items() if k not in FILTERED_TOOL_FIELDS]
                        if kept:
                            parts.append(", ".join(kept))
                    parts.append("</tool_use>\n")
        elif et == "queue-operation" and entry.get("operation") == "enqueue":
            enqueue_count += 1
        elif et == "user" or "permissionMode" in entry:
            c = entry.get("message", {}).get("content", "")
            if isinstance(c, str) and "<task-notification>" in c:
                task_noti_count += 1
                last_was_task_noti = True

    if enqueue_count and enqueue_count != task_noti_count:
        return "", None  # background work pending — skip
    if last_was_task_noti:
        return "", None  # assistant hasn't responded yet — skip
    return "\n".join(parts).strip(), model or "claude-code"


def extract_from_transcript(path: str) -> tuple[str | None, str | None, str | None]:
    parsed = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                parsed.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    if not parsed:
        return None, None, None

    last_user_idx = -1
    last_user_text: str | None = None
    for i in range(len(parsed) - 1, -1, -1):
        entry = parsed[i]
        if entry.get("type") != "user" and "permissionMode" not in entry:
            continue
        text = extract_user_text(entry)
        if text:
            last_user_idx = i
            last_user_text = text
            break

    if last_user_idx == -1 or last_user_text is None:
        return None, None, None

    response, model = render_assistant(parsed, last_user_idx)
    if not response and model is None:
        return None, None, None  # render_assistant signaled skip
    return last_user_text, response, model


# --- POST to Convex ---------------------------------------------------------

def post_event(url: str, token: str, payload: dict) -> None:
    endpoint = url.rstrip("/") + "/ingest"
    req = Request(
        endpoint,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}",
        },
        method="POST",
    )
    with urlopen(req, timeout=10) as resp:
        log(
            f"sent prompt={len(payload['message'])}c "
            f"response={len(payload.get('response') or '')}c status={resp.status}"
        )


# --- entrypoint -------------------------------------------------------------

def main() -> None:
    url, token = load_env()
    if not url or not token:
        log(f"no CONVEX_URL/CONVEX_TOKEN in {ENV_FILE}, skipping (run skills/setup/install.py)")
        return

    try:
        hook_input = json.load(sys.stdin)
    except Exception as e:
        log(f"stdin parse error: {e}")
        return

    session_id = hook_input.get("session_id", "")
    transcript_path = hook_input.get("transcript_path", "")
    cwd = hook_input.get("cwd", os.getcwd())

    if not transcript_path or not os.path.isfile(transcript_path):
        log(f"transcript not found: {transcript_path}")
        return

    prompt, response, model = extract_from_transcript(transcript_path)
    if not prompt:
        log("no real user prompt found, skipping")
        return

    project, username = get_git_info(cwd)
    payload = {
        "username": username,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "message": prompt,
        "response": response or "",
        "project": project,
        "project_path": cwd,
        "session_id": session_id,
        "model": model or "unknown",
    }

    try:
        post_event(url, token, payload)
    except Exception as e:
        log(f"POST failed: {e}")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:  # never break the session
        log(f"fatal: {e}")
    sys.exit(0)
