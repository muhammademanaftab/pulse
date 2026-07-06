#!/usr/bin/env python3
"""Tests for the Pulse capture hook (skills/setup/capture.py).

Stdlib only, no test framework: plain asserts, runnable directly.

    python3 skills/setup/test_capture.py

Covers the two riskiest parts: the transcript parser (which re-implements
Claude Code's transcript shape) and the redaction / truncation pass.
"""
import importlib.util
import json
import os
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("capture", os.path.join(HERE, "capture.py"))
cap = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cap)


def write_transcript(entries: list[dict]) -> str:
    fd, path = tempfile.mkstemp(suffix=".jsonl")
    with os.fdopen(fd, "w") as f:
        for e in entries:
            f.write(json.dumps(e) + "\n")
    return path


def user(text) -> dict:
    return {"type": "user", "message": {"content": text}}


def assistant(blocks, model="claude-test") -> dict:
    return {"type": "assistant", "message": {"model": model, "content": blocks}}


# --- transcript parsing -----------------------------------------------------

def test_extracts_last_prompt_and_response():
    path = write_transcript([
        user("first prompt"),
        assistant([{"type": "text", "text": "first answer"}]),
        user("second prompt"),
        assistant([{"type": "text", "text": "second answer"}]),
    ])
    prompt, response, model = cap.extract_from_transcript(path)
    os.unlink(path)
    assert prompt == "second prompt", prompt
    assert "second answer" in response, response
    assert model == "claude-test", model


def test_skips_auto_injected_prompts():
    # The only real user text is the earlier one; the later "user" entry is an
    # auto-injected system reminder and must not be picked as the prompt.
    path = write_transcript([
        user("real question"),
        assistant([{"type": "text", "text": "answer"}]),
        user("<system-reminder>background context</system-reminder>"),
    ])
    prompt, _, _ = cap.extract_from_transcript(path)
    os.unlink(path)
    assert prompt == "real question", prompt


def test_tool_use_filtering():
    path = write_transcript([
        user("do a thing"),
        assistant([
            {"type": "tool_use", "name": "Bash",
             "input": {"command": "ls -la", "content": "should be dropped"}},
            {"type": "tool_use", "name": "Edit",
             "input": {"file_path": "/x.py", "old_string": "a", "new_string": "b"}},
        ]),
    ])
    _, response, _ = cap.extract_from_transcript(path)
    os.unlink(path)
    assert "command: ls -la" in response, response
    assert "file_path: /x.py" in response, response
    # Filtered fields never appear.
    assert "should be dropped" not in response, response
    assert "old_string" not in response and "new_string" not in response, response


def test_thinking_captured():
    path = write_transcript([
        user("q"),
        assistant([
            {"type": "thinking", "thinking": "let me reason"},
            {"type": "text", "text": "the answer"},
        ]),
    ])
    _, response, _ = cap.extract_from_transcript(path)
    os.unlink(path)
    assert "<thinking>" in response and "let me reason" in response, response


def test_skips_pending_background_work():
    # An enqueue with no matching task-notification means work is still pending;
    # render_assistant signals skip (empty response, None model).
    path = write_transcript([
        user("kick off background work"),
        {"type": "queue-operation", "operation": "enqueue"},
        assistant([{"type": "text", "text": "started"}]),
    ])
    prompt, response, model = cap.extract_from_transcript(path)
    os.unlink(path)
    assert prompt is None and response is None and model is None, (prompt, response, model)


def test_empty_transcript():
    path = write_transcript([])
    result = cap.extract_from_transcript(path)
    os.unlink(path)
    assert result == (None, None, None), result


# --- redaction --------------------------------------------------------------

def test_redaction_each_class():
    cases = {
        "private-key": "-----BEGIN RSA PRIVATE KEY-----\nMII\n-----END RSA PRIVATE KEY-----",
        "aws-key": "AKIAIOSFODNN7EXAMPLE",
        "github-token": "ghp_0123456789012345678901234567890123456",
        "slack-token": "xoxb-1234567890-abcdefghij",
        "api-key": "sk-abcdefghijklmnopqrstuvwxyz012345",
        "bearer": "Authorization: Bearer abcdef1234567890XYZ",
        "assignment": "export API_KEY=supersecretvalue123",
        "hex": "0123456789abcdef0123456789abcdef01234567",
    }
    for kind, sample in cases.items():
        out = cap.redact(sample)
        assert f"[REDACTED:{kind}]" in out, (kind, out)
        # The secret substring itself is gone.
        secret = sample.split()[-1]
        assert secret not in out, (kind, out)


def test_redaction_prefixed_env_vars():
    # Real-world shapes: the keyword sits after an underscore prefix.
    for sample in (
        "export GITHUB_TOKEN=ghsecretvalue99",
        "DB_PASSWORD=hunter2hunter2",
        "STRIPE_SECRET_KEY: sk_live_replaced",
        "AWS_SECRET_ACCESS_KEY=wJalrXUtnFEMIabc",
    ):
        out = cap.redact(sample)
        assert "[REDACTED:assignment]" in out, (sample, out)


def test_load_env_refuses_http():
    env_dir = tempfile.mkdtemp()
    env_path = os.path.join(env_dir, ".env")
    with open(env_path, "w") as f:
        f.write("CONVEX_URL=http://evil.example\nCONVEX_TOKEN=abc123abc123\n")
    old_env, old_log = cap.ENV_FILE, cap.LOG_FILE
    cap.ENV_FILE = env_path
    cap.LOG_FILE = os.path.join(env_dir, "capture.log")
    try:
        assert cap.load_env() == (None, None)
    finally:
        cap.ENV_FILE, cap.LOG_FILE = old_env, old_log


def test_clean_text_passthrough():
    clean = "Refactored the parser and added a test for project foo."
    assert cap.redact(clean) == clean


def test_truncation():
    big = "x" * (cap.MAX_FIELD_CHARS + 5000)
    out = cap.truncate(big)
    assert out.endswith("[TRUNCATED]"), out[-20:]
    assert len(out) <= cap.MAX_FIELD_CHARS + len("\n[TRUNCATED]"), len(out)
    assert cap.truncate("short") == "short"


def main() -> int:
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print(f"OK {t.__name__}")
    print(f"\n{len(tests)} passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
