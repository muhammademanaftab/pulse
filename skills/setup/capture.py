#!/usr/bin/env python3
"""Pulse capture hook (L0).

Runs when a coding tool finishes a turn (for Claude Code, as a `Stop` hook) and
POSTs one event to the user's Convex deployment at `{CONVEX_URL}/ingest`.

It has two parts. An adapter knows one tool: it reads that tool's hook input and
returns the turn (prompt, response, model, session_id). The core knows no tool:
it skips ignored folders, redacts, truncates, builds the event and sends it. An
adapter never sends anything, so every turn goes through the same redaction.

The hook command picks the adapter with `--source <name>`; without it the source
is `claude-code`. To support another tool, write its two functions (the folder of
a hook input, and the turn of a hook input), add them to `ADAPTERS`, and add a
fake hook input for it to `HOOK_INPUTS` in tests/test_capture.py. The folder
function must use the hook input only: it runs before the ignore list is checked,
so it must not open the session.

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
IGNORE_FILE = os.path.expanduser("~/.pulse/ignore")
LOG_FILE = os.path.expanduser("~/.pulse/capture.log")
MAX_LOG_BYTES = 5 * 1024 * 1024
MAX_FIELD_CHARS = 100_000
DEFAULT_SOURCE = "claude-code"

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

NOT_AN_ENV_LOOKUP = (
    r"(?!['\"]?(?:process\.env|os\.environ|os\.getenv|\$\{?[A-Za-z_]|undefined\b|null\b|None\b"
    r"|\[REDACTED:))")

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
        r"|SG\.[A-Za-z0-9_-]{16,}\.[A-Za-z0-9_-]{16,}"
        r"|npm_[A-Za-z0-9]{36}\b|[0-9]{6,}:[A-Za-z0-9_-]{35}(?![A-Za-z0-9_-])"
        r"|lin_api_[A-Za-z0-9]{40}\b|shp(?:at|ca|pa)_[A-Za-z0-9]{32}\b"
        r"|pypi-[A-Za-z0-9_-]{85,}|dckr_pat_[A-Za-z0-9_-]{27}(?![A-Za-z0-9_-])"
        r"|gsk_[A-Za-z0-9]{52}\b|r8_[A-Za-z0-9]{37}\b|pplx-[A-Za-z0-9]{48}\b)")),
    ("bearer", re.compile(r"\bBearer\s+[A-Za-z0-9._~+/=-]{16,}", re.I)),
    ("basic-auth", re.compile(r"\bBasic\s+[A-Za-z0-9+/]{16,}={0,2}")),
    ("assignment", re.compile(
        r"((?:api[_-]?key|access[_-]?key|secret(?:[_-]?key)?|token|passwd|password|passphrase"
        r"|[_-]pass|[_-]pwd)"
        r"\b['\"]?\s*[=:]\s*" + NOT_AN_ENV_LOOKUP +
        r"['\"]?)(?:(?=[^\s)\]},;+])(?:(?<=\")[^\"\r\n]{8,200}(?=\")|(?<=')[^'\r\n]{8,200}(?='))"
        r"|[^\s'\"]{8,})", re.I)),
    ("password", re.compile(
        r"((?<![A-Za-z0-9])(?:pass|pwd|credentials?)(?:[_-][A-Za-z0-9_]{1,40})?"
        r"['\"]?\s*[=:]\s*" + NOT_AN_ENV_LOOKUP + r"(?!['\"]?(?:[~.]{0,2}/|[A-Za-z]:[\\/]))"
        r"['\"]?)(?=[^\s'\"]{0,63}[0-9])[^\s'\"]{8,}", re.I)),
    ("cli-password", re.compile(
        r"(\b(?:mysql|mariadb)[^\n]{0,200}?\s-p['\"]?)(?!\[REDACTED:)[^\s'\"]{8,}")),
    ("cli-password", re.compile(
        r"(\bcurl\b[^\n]{0,200}?\s(?:-u\s*|--user[=\s]\s*)['\"]?[^\s:'\"]{0,100}:)"
        + NOT_AN_ENV_LOOKUP + r"[^\s'\"]{8,}")),
    ("authorization", re.compile(
        r"(\bauthorization['\"]?\s*:\s*['\"]?(?:(?!(?:bearer|basic)\b)[a-z][a-z0-9_-]{0,30}\s+)?)"
        r"(?!\[REDACTED:)[A-Za-z0-9._~+/=-]{16,}", re.I)),
    ("cookie", re.compile(
        r"(\bcookie['\"]?\s*:\s*['\"]?)(?=[^\s=;'\"]{1,256}=)"
        r"[^\r\n]+?(?=['\"](?:[\s,)}\]]|\Z)|[\r\n]|\Z)", re.I)),
    ("hex", re.compile(
        r"(?:\b|(?<=_))(?![a-f0-9]{40}(?:\b|(?=_)))"
        r"[a-fA-F0-9]{40,}(?:\b|(?=_))")),
)


def redact(text: str) -> str:
    for kind, rx in REDACT_PATTERNS:
        text = rx.sub(lambda m, kind=kind: (m.group(1) if rx.groups else "") + f"[REDACTED:{kind}]", text)
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


def normalized_folder(folder: str) -> str:
    if not isinstance(folder, str) or not folder or "\0" in folder:
        raise ValueError("folder must be a nonempty path without null bytes")
    expanded = os.path.expanduser(folder)
    if not os.path.isabs(expanded):
        raise ValueError("folder must be an absolute path")
    return os.path.normcase(os.path.realpath(expanded))


def is_ignored_folder(cwd: str) -> bool:
    try:
        try:
            with open(IGNORE_FILE, encoding="utf-8") as f:
                folders = [line.strip() for line in f
                           if line.strip() and not line.lstrip().startswith("#")]
        except FileNotFoundError:
            if not os.path.lexists(IGNORE_FILE):
                return False
            raise
        if not folders:
            return False
        current = normalized_folder(cwd)
        ignored = [normalized_folder(folder) for folder in folders]
        for folder in ignored:
            try:
                matches = os.path.commonpath((current, folder)) == folder
            except ValueError:
                continue
            if matches:
                log(f"skipping ignored folder: {os.path.basename(current) or current!r}")
                return True
    except (OSError, ValueError):
        log("capture skipped: could not read or validate ~/.pulse/ignore")
        return True
    return False


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
        return "", None
    if last_was_task_noti:
        return "", None
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


def claude_code_folder(hook_input: dict) -> str:
    return hook_input.get("cwd", os.getcwd())


def claude_code_turn(hook_input: dict) -> dict | None:
    transcript_path = hook_input.get("transcript_path", "")
    if not transcript_path or not os.path.isfile(transcript_path):
        log(f"transcript not found: {transcript_path}")
        return None
    prompt, response, model = extract_from_transcript(transcript_path)
    if not prompt:
        log("no real user prompt found, skipping")
        return None
    return {"prompt": prompt, "response": response or "", "model": model,
            "session_id": hook_input.get("session_id", "")}


ADAPTERS = {
    "claude-code": (claude_code_folder, claude_code_turn),
}


def build_event(source: str, cwd: str, turn: dict) -> dict:
    project, username = get_git_info(cwd)
    return {
        "username": username,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "event_id": make_event_id(turn["session_id"], turn["prompt"], turn["response"]),
        "message": truncate(redact(turn["prompt"])),
        "response": truncate(redact(turn["response"])),
        "project": project,
        "project_path": cwd,
        "session_id": turn["session_id"],
        "model": turn.get("model") or "unknown",
        "source": source,
    }


def capture(source: str, hook_input: dict) -> dict | None:
    """The event for one hook input, or None when there is nothing to send. The
    ignore list is checked before the adapter reads anything from the session."""
    folder_of, turn_of = ADAPTERS[source]
    cwd = folder_of(hook_input)
    if is_ignored_folder(cwd):
        return None
    turn = turn_of(hook_input)
    return build_event(source, cwd, turn) if turn else None


def source_arg(argv: list[str]) -> str:
    for i, arg in enumerate(argv):
        if arg == "--source":
            return argv[i + 1] if i + 1 < len(argv) else ""
        if arg.startswith("--source="):
            return arg[len("--source="):]
    return DEFAULT_SOURCE


def main(argv: list[str] | None = None) -> None:
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

    source = source_arg(argv or [])
    if source not in ADAPTERS:
        log(f"unknown source {source!r}, skipping (known: {', '.join(sorted(ADAPTERS))})")
        return

    payload = capture(source, hook_input)
    if payload is None:
        return

    try:
        post_event(url, token, payload)
    except Exception as e:
        log(f"POST failed: {e}")


if __name__ == "__main__":
    try:
        main(sys.argv[1:])
    except Exception as e:
        log(f"fatal: {e}")
    sys.exit(0)
