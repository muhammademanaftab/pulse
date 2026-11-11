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
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from urllib.request import Request, urlopen

ENV_FILE = os.path.expanduser("~/.pulse/.env")
LOG_FILE = os.path.expanduser("~/.pulse/capture.log")
MAX_LOG_BYTES = 5 * 1024 * 1024
MAX_FIELD_CHARS = 100_000  # Convex caps documents at 1MB; stay well under it

FILTERED_TOOL_FIELDS = {"content", "old_string", "new_string", "new_source"}
COMMAND_NAME_RE = re.compile(r"<command-name>\s*(/?[^<\s]+)\s*</command-name>")
COMMAND_ARGS_RE = re.compile(r"<command-args>(.*?)</command-args>", re.S)
AUTO_INJECTED_PREFIXES = (
    "<task-notification>",
    "<user-prompt-submit-hook>",
    "<system-reminder>",
    "<command-message>",
    "<command-name>",
    "<local-command-stdout>",
    "[Image: source:",
    "[Request interrupted",
    "Caveat: The messages below were generated",
    "<bash-input>",
    "<bash-stdout>",
    "<bash-stderr>",
)

# Best-effort secret scrubbing. Everything captured (prompts, responses,
# thinking, tool inputs like Bash commands) passes through these before it
# leaves the machine. Not a guarantee, but it catches the common shapes.
REDACT_PATTERNS = (
    ("private-key", re.compile(
        r"-----BEGIN [A-Z ]*PRIVATE KEY(?: BLOCK)?-----.*?"
        r"(?:-----END [A-Z ]*PRIVATE KEY(?: BLOCK)?-----|\Z)", re.S)),
    ("url-credentials", re.compile(r"(?<=://)[^\s:/@]*:[^\s@/]+(?=@)")),
    ("webhook", re.compile(r"https://hooks\.slack\.com/services/[A-Za-z0-9/_-]+")),
    ("aws-key", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")),
    ("github-token", re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{36,}|github_pat_[A-Za-z0-9_]{20,})\b")),
    ("slack-token", re.compile(r"\b(?:xox[baprs]|xapp)-[A-Za-z0-9-]{10,}\b")),
    ("api-key", re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b")),
    ("stripe-key", re.compile(r"\b[sr]k_(?:live|test)_[A-Za-z0-9]{10,}\b")),
    ("jwt", re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{5,}")),
    ("token", re.compile(
        r"\b(?:glpat-[A-Za-z0-9_-]{20,}|AIza[0-9A-Za-z_-]{35}|hf_[A-Za-z0-9]{30,}"
        r"|SG\.[A-Za-z0-9_-]{16,}\.[A-Za-z0-9_-]{16,})")),
    ("bearer", re.compile(r"\bBearer\s+[A-Za-z0-9._~+/=-]{16,}", re.I)),
    ("basic-auth", re.compile(r"\bBasic\s+[A-Za-z0-9+/]{16,}={0,2}")),
    # No leading \b: it would fail after an underscore, missing GITHUB_TOKEN=...
    ("assignment", re.compile(
        r"(?:api[_-]?key|access[_-]?key|secret(?:[_-]?key)?|token|passwd|password)"
        r"\b['\"]?\s*[=:]\s*"
        r"(?!['\"]?(?:process\.env|os\.environ|os\.getenv|\$\{?[A-Za-z_]|undefined\b|null\b|None\b))"
        r"['\"]?[^\s'\"]{8,}", re.I)),
    ("hex", re.compile(r"\b(?![a-f0-9]{40}\b)[a-fA-F0-9]{40,}\b")),
)


def redact(text: str) -> str:
    for kind, rx in REDACT_PATTERNS:
        text = rx.sub(f"[REDACTED:{kind}]", text)
    return text


def truncate(text: str) -> str:
    if len(text) > MAX_FIELD_CHARS:
        return text[:MAX_FIELD_CHARS] + "\n[TRUNCATED]"
    return text


def make_event_id(session_id: str, prompt: str, response: str) -> str:
    """Stable id for a turn so a double-fired Stop hook does not duplicate rows.
    Built only from transcript content (never the clock), so two firings for the
    same turn produce the same id and the backend dedups the second."""
    return hashlib.sha256(
        f"{session_id}:{prompt}:{response}".encode("utf-8")).hexdigest()[:32]


# --- credentials + logging --------------------------------------------------

def log(msg: str) -> None:
    try:
        os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
        try:
            if os.path.getsize(LOG_FILE) > MAX_LOG_BYTES:
                os.replace(LOG_FILE, LOG_FILE + ".1")
        except OSError:
            pass
        with open(LOG_FILE, "a", encoding="utf-8") as f:
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
        with open(ENV_FILE, encoding="utf-8") as f:
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
    if url and not url.startswith("https://"):
        log(f"refusing non-https CONVEX_URL: {url}")
        return None, None
    return url, token


# --- transcript parsing -----------------------------------------------------

def get_git_info(cwd: str) -> tuple[str, str]:
    repo_name = os.path.basename(cwd.rstrip("/\\")) or "unknown"
    username = os.environ.get("USER") or os.environ.get("USERNAME", "unknown")
    try:
        r = subprocess.run(
            ["git", "-C", cwd, "rev-parse", "--show-toplevel"],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=2,
        )
        if r.returncode == 0 and r.stdout.strip():
            repo_name = os.path.basename(r.stdout.strip())
    except Exception:
        pass
    try:
        r = subprocess.run(
            ["git", "-C", cwd, "config", "user.name"],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=2,
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


def message_of(entry: dict) -> dict:
    msg = entry.get("message")
    return msg if isinstance(msg, dict) else {}


def content_text(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(b.get("text", "") for b in content
                         if isinstance(b, dict) and isinstance(b.get("text"), str))
    return ""


def command_text(text: str) -> str | None:
    name = COMMAND_NAME_RE.search(text)
    if not name:
        return None
    args = COMMAND_ARGS_RE.search(text)
    command = name.group(1) if name.group(1).startswith("/") else "/" + name.group(1)
    return f"{command} {args.group(1).strip() if args else ''}".strip()


def extract_user_text(entry: dict) -> str | None:
    if entry.get("isMeta") or entry.get("isCompactSummary"):
        return None
    content = message_of(entry).get("content")
    if isinstance(content, str):
        return command_text(content) or (content if is_user_typed_text(content) else None)
    if isinstance(content, list):
        parts = []
        for block in content:
            if not isinstance(block, dict) or block.get("type") != "text":
                continue
            text = block.get("text", "")
            if (command := command_text(text)):
                parts.append(command)
            elif is_user_typed_text(text):
                parts.append(text)
        return "\n".join(parts) if parts else None
    return None


def drop_filtered(value):
    if isinstance(value, dict):
        return {k: drop_filtered(v) for k, v in value.items() if k not in FILTERED_TOOL_FIELDS}
    if isinstance(value, list):
        return [drop_filtered(v) for v in value]
    return value


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
                model = message_of(entry).get("model")
            for b in message_of(entry).get("content") or []:
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
                        kept = [f"{k}: {v}" for k, v in drop_filtered(inp).items()]
                        if kept:
                            parts.append(", ".join(kept))
                    parts.append("</tool_use>\n")
        elif et == "queue-operation" and entry.get("operation") == "enqueue":
            enqueue_count += 1
        elif et == "user" or "permissionMode" in entry:
            if "<task-notification>" in content_text(message_of(entry).get("content")):
                task_noti_count += 1
                last_was_task_noti = True

    if enqueue_count and enqueue_count != task_noti_count:
        return "", None  # background work pending, skip
    if last_was_task_noti:
        return "", None  # assistant hasn't responded yet, skip
    return "\n".join(parts).strip(), model or "claude-code"


def extract_from_transcript(path: str) -> tuple[str | None, str | None, str | None]:
    parsed = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(entry, dict):
                parsed.append(entry)
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
    if not response and (model is None or last_user_text.startswith("/")):
        return None, None, None
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
        if os.path.isfile(ENV_FILE):
            log(f"no usable CONVEX_URL/CONVEX_TOKEN in {ENV_FILE}, skipping "
                "(run skills/setup/install.py)")
        return

    try:
        hook_input = json.loads(sys.stdin.buffer.read().decode("utf-8"))
    except Exception as e:
        log(f"stdin parse error: {e}")
        return
    if not isinstance(hook_input, dict):
        log("stdin is not a JSON object, skipping")
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
        "event_id": make_event_id(session_id, prompt, response or ""),
        "message": truncate(redact(prompt)),
        "response": truncate(redact(response or "")),
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
