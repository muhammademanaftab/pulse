#!/usr/bin/env python3
"""Tests for the Pulse capture hook (skills/setup/capture.py).

Stdlib only, no test framework: plain asserts, runnable directly.

    python3 tests/test_capture.py

Covers the two riskiest parts: the transcript parser (which re-implements
Claude Code's transcript shape) and the redaction / truncation pass.
"""
from __future__ import annotations

import importlib.util
import json
import os
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
spec = importlib.util.spec_from_file_location(
    "capture", os.path.join(REPO, "skills", "setup", "capture.py"))
cap = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cap)


def write_transcript(entries: list[dict]) -> str:
    fd, path = tempfile.mkstemp(suffix=".jsonl")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        for e in entries:
            f.write(json.dumps(e, ensure_ascii=False) + "\n")
    return path


def user(text) -> dict:
    return {"type": "user", "message": {"content": text}}


def assistant(blocks, model="claude-test") -> dict:
    return {"type": "assistant", "message": {"model": model, "content": blocks}}


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
    path = write_transcript([
        user("kick off background work"),
        {"type": "queue-operation", "operation": "enqueue"},
        assistant([{"type": "text", "text": "started"}]),
    ])
    prompt, response, model = cap.extract_from_transcript(path)
    os.unlink(path)
    assert prompt is None and response is None and model is None, (prompt, response, model)


def test_non_ascii_transcript_on_non_utf8_locale():
    path = write_transcript([
        user("why \u201cquoted\u201d?"),
        assistant([{"type": "text", "text": "because \u2014 reasons \u2713"}]),
    ])
    real_open = open

    def cp1252_default_open(file, mode="r", *a, **kw):
        if "b" not in mode and "encoding" not in kw and not a:
            kw["encoding"] = "cp1252"
        return real_open(file, mode, *a, **kw)

    cap.open = cp1252_default_open
    try:
        prompt, response, _ = cap.extract_from_transcript(path)
    finally:
        del cap.open
        os.unlink(path)
    assert prompt == "why \u201cquoted\u201d?", prompt
    assert "\u2014 reasons \u2713" in response, response


def test_empty_transcript():
    path = write_transcript([])
    result = cap.extract_from_transcript(path)
    os.unlink(path)
    assert result == (None, None, None), result


def test_redaction_each_class():
    cases = {
        "private-key": "-----BEGIN RSA PRIVATE KEY-----\nMII\n-----END RSA PRIVATE KEY-----",
        "aws-key": "AKIAIOSFODNN7EXAMPLE",
        "github-token": "ghp_0123456789012345678901234567890123456",
        "slack-token": "xoxb-1234567890-abcdefghij",
        "api-key": "sk-abcdefghijklmnopqrstuvwxyz012345",
        "bearer": "Authorization: Bearer abcdef1234567890XYZ",
        "assignment": "export API_KEY=supersecretvalue123",
        "hex": "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
        "url-credentials": "postgres://admin:Pa55w0rdXyz@db.internal:5432/app",
        "webhook": "https://hooks.slack.com/services/T000/B000/abcdefghijklmnop",
        "stripe-key": "sk_live_abcdefghijklmnop1234",
        "jwt": "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dozjgNryP4J3jVmNHl0w5N",
        "token": "glpat-abcdefghij0123456789",
        "basic-auth": "Authorization: Basic dXNlcjpwYXNzd29yZDEyMw==",
    }
    for kind, sample in cases.items():
        out = cap.redact(sample)
        assert f"[REDACTED:{kind}]" in out, (kind, out)
        secret = sample.split()[-1]
        assert secret not in out, (kind, out)


def test_redaction_prefixed_env_vars():
    for sample in (
        "export GITHUB_TOKEN=ghsecretvalue99",
        "DB_PASSWORD=hunter2hunter2",
        "STRIPE_SECRET_KEY: sk_live_replaced",
        "AWS_SECRET_ACCESS_KEY=wJalrXUtnFEMIabc",
    ):
        out = cap.redact(sample)
        assert "[REDACTED:assignment]" in out, (sample, out)


def test_redaction_more_shapes():
    for sample, secret in (
        ('{"password": "hunter2hunter2"}', "hunter2hunter2"),
        ('"api_key": "abcd1234abcd1234"', "abcd1234abcd1234"),
        ("github_pat_11ABCDEFG0abcdefghijklmn_opqrstuv", "github_pat_11ABCDEFG0"),
        ("ASIAIOSFODNN7EXAMPLE", "ASIAIOSFODNN7EXAMPLE"),
        ("xapp-1-A0123456789-abcdef", "xapp-1-A0123456789"),
        ("mongodb+srv://user:s3cretpw@cluster0.example.net", "s3cretpw"),
        ("-----BEGIN PGP PRIVATE KEY BLOCK-----\nabc\n-----END PGP PRIVATE KEY BLOCK-----", "abc"),
        ("0123456789ABCDEF0123456789ABCDEF0123456789ABCDEF", "0123456789ABCDEF"),
    ):
        out = cap.redact(sample)
        assert "[REDACTED:" in out and secret not in out, (sample, out)


def test_redaction_keeps_the_variable_name_and_the_specific_kind():
    assert cap.redact("STRIPE_API_KEY=sk_test_abcdefghij1234 pytest") == \
        "STRIPE_API_KEY=[REDACTED:stripe-key] pytest"
    assert cap.redact("GH_TOKEN=github_pat_11ABCDEFG0abcdefghijklmn") == "GH_TOKEN=[REDACTED:github-token]"
    assert cap.redact('{"password": "hunter2hunter2"}') == '{"password": "[REDACTED:assignment]"}'
    assert cap.redact("DB_PASSWORD=hunter2hunter2") == "DB_PASSWORD=[REDACTED:assignment]"


def test_redaction_leaves_commit_shas_and_env_lookups():
    for harmless in (
        "git checkout 0123456789abcdef0123456789abcdef01234567",
        "password: process.env.DB_PASSWORD",
        'api_key = os.environ["API_KEY"]',
        "export TOKEN=$GITHUB_TOKEN",
        "The token=undefined bug",
        "see https://example.com/docs/page",
    ):
        assert cap.redact(harmless) == harmless, (harmless, cap.redact(harmless))


def test_skill_turn_records_the_command_not_the_skill_body():
    path = write_transcript([
        user("earlier question"),
        assistant([{"type": "text", "text": "earlier answer"}]),
        user("<command-message>review</command-message>\n<command-name>/review</command-name>\n"
             "<command-args>the login bug</command-args>"),
        {"type": "user", "isMeta": True,
         "message": {"content": [{"type": "text", "text": "Base directory for this skill: /x\nSKILL BODY"}]}},
        assistant([{"type": "text", "text": "reviewing"}]),
    ])
    prompt, response, _ = cap.extract_from_transcript(path)
    os.unlink(path)
    assert prompt == "/review the login bug", prompt
    assert "reviewing" in response and "earlier answer" not in response, response


def test_compact_summary_is_not_a_prompt():
    path = write_transcript([
        user("real question"),
        assistant([{"type": "text", "text": "answer"}]),
        {"type": "user", "isCompactSummary": True,
         "message": {"content": "This session is being continued from a previous conversation"}},
    ])
    prompt, _, _ = cap.extract_from_transcript(path)
    os.unlink(path)
    assert prompt == "real question", prompt


def test_local_command_without_a_response_is_skipped():
    path = write_transcript([
        user("q1"),
        assistant([{"type": "text", "text": "a1"}]),
        user("<command-name>/cost</command-name>"),
        user("<local-command-stdout>$0.12</local-command-stdout>"),
    ])
    result = cap.extract_from_transcript(path)
    os.unlink(path)
    assert result == (None, None, None), result


def test_nested_edit_payloads_are_dropped():
    path = write_transcript([
        user("edit things"),
        assistant([
            {"type": "tool_use", "name": "MultiEdit",
             "input": {"file_path": "/c.py", "edits": [{"old_string": "OLDM", "new_string": "NEWM"}]}},
            {"type": "tool_use", "name": "NotebookEdit",
             "input": {"notebook_path": "/n.ipynb", "new_source": "NBSRC"}},
        ]),
    ])
    _, response, _ = cap.extract_from_transcript(path)
    os.unlink(path)
    assert "file_path: /c.py" in response and "notebook_path: /n.ipynb" in response, response
    assert not any(leak in response for leak in ("OLDM", "NEWM", "NBSRC")), response


def test_load_env_refuses_http():
    env_dir = tempfile.mkdtemp()
    env_path = os.path.join(env_dir, ".env")
    with open(env_path, "w", encoding="utf-8") as f:
        f.write("CONVEX_URL=http://evil.example\nCONVEX_TOKEN=abc123abc123\n")
    old_env, old_log = cap.ENV_FILE, cap.LOG_FILE
    cap.ENV_FILE = env_path
    cap.LOG_FILE = os.path.join(env_dir, "capture.log")
    try:
        assert cap.load_env() == (None, None)
    finally:
        cap.ENV_FILE, cap.LOG_FILE = old_env, old_log


def test_event_id_stable_across_refires():
    a = cap.make_event_id("sess-1", "do the thing", "did the thing")
    b = cap.make_event_id("sess-1", "do the thing", "did the thing")
    c = cap.make_event_id("sess-1", "do the thing", "did it differently")
    d = cap.make_event_id("sess-2", "do the thing", "did the thing")
    assert a == b
    assert len({a, c, d}) == 3
    assert len(a) == 32 and all(ch in "0123456789abcdef" for ch in a)


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
