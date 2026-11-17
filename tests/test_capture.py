#!/usr/bin/env python3
"""Tests for the Pulse capture hook (skills/setup/capture.py).

Stdlib only, no test framework: plain asserts, runnable directly.

    python3 tests/test_capture.py

Covers the two riskiest parts: the transcript parser (which re-implements
Claude Code's transcript shape) and the redaction / truncation pass.
"""
from __future__ import annotations

import importlib.util
import io
import json
import ntpath
import os
import subprocess
import sys
import tempfile
from types import SimpleNamespace
from unittest.mock import patch

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


def test_redaction_hex_next_to_underscores():
    for secret in ("a1b2c3d4" * 8, "a1B2c3D4" * 8,
                   "a1b2c3d4" * 5 + "a", "a1B2c3D4" * 5):
        for prefix, suffix in (("dop_v1_", ""), ("", "_suffix"),
                               ("prefix_", "_suffix")):
            text = "credential (" + prefix + secret + suffix + "), end"
            expected = "credential (" + prefix + "[REDACTED:hex]" + suffix + "), end"
            out = cap.redact(text)
            assert out == expected, out
            assert cap.redact(out) == out, out


def test_redaction_leaves_short_hex_and_commit_shas_next_to_underscores():
    for value in ("a1b2c3d4" * 5, "a1b2c3d4" * 4 + "a1b2c3d",
                  "a1B2c3D4" * 4 + "a1B2c3D"):
        for prefix, suffix in (("", ""), ("prefix_", ""),
                               ("", "_suffix"), ("prefix_", "_suffix")):
            text = prefix + value + suffix
            assert cap.redact(text) == text, text


def test_redaction_leaves_hex_inside_words():
    value = "a1b2c3d4" * 8
    for prefix, suffix in (("g", ""), ("", "g"),
                           ("\u00e9", ""), ("", "\u00e9")):
        text = prefix + value + suffix
        assert cap.redact(text) == text, text


def test_redaction_provider_tokens():
    samples = [
        "npm_" + "a1B2" * 9,
        "123456789:" + "AA" + "a1_B-" * 6 + "abc",
        "123456789:" + "AA" + "a1_B-" * 6 + "ab-",
        "lin_api_" + "a1B2c3D4" * 5,
        "pypi-" + "AgEIcHlwaS5vcmc" + "a1B2c3D4" * 9,
        "dckr_pat_" + "a1B2c3D4" * 3 + "a1B",
        "gsk_" + "a1B2" * 12,
        "r8_" + "a1B2c3D4" * 4 + "a1B2c",
        "pplx-" + "a1B2" * 12,
    ]
    samples.extend(prefix + "a1B2c3D4" * 4
                   for prefix in ("shpat_", "shpca_", "shppa_"))
    for sample in samples:
        out = cap.redact("credential (" + sample + "), end")
        assert sample not in out, out
        assert "[REDACTED:token]" in out, out
        assert out.endswith("), end"), out
        assert cap.redact(out) == out, out


def test_redaction_leaves_normal_numbers_and_colons():
    for text in (
        "Meeting starts at 12:30 and ends at 13:15.",
        "Order 123456789: ready for collection.",
        "npm_package_name and lin_api_examples are labels.",
        "pypi-package-name is just a package name.",
        "dckr_pat_short is not a token.",
        "gsk_example is a harmless label.",
    ):
        assert cap.redact(text) == text, text


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


FAKE_PASSWORD = "Sup3r" + "SecretPw99"
FAKE_HEADER_TOKEN = "a1B2c3D4" * 4


def assert_redacts_to(sample, expected):
    out = cap.redact(sample)
    assert out == expected, (sample, out)
    assert cap.redact(out) == out, out


def test_redaction_quoted_values_with_spaces():
    phrase = "my secret " + "pass phrase"
    for sample, expected in (
        ('password: "' + phrase + '"', 'password: "[REDACTED:assignment]"'),
        ("password: '" + phrase + "'", "password: '[REDACTED:assignment]'"),
        ('{"password": "' + phrase + '"}', '{"password": "[REDACTED:assignment]"}'),
        ('DB_PASSWORD="' + phrase + '"', 'DB_PASSWORD="[REDACTED:assignment]"'),
        ('passphrase: "correct horse ' + 'battery staple"', 'passphrase: "[REDACTED:assignment]"'),
        ('api_key = "' + phrase + '"', 'api_key = "[REDACTED:assignment]"'),
    ):
        assert_redacts_to(sample, expected)


def test_redaction_short_password_key_names():
    for key, kind in (
        ("DB_PASS=", "assignment"), ("DB_PWD=", "assignment"), ("MYSQL_PWD=", "assignment"),
        ("--pass=", "assignment"), ("passphrase=", "assignment"), ("PWD_ADMIN=", "password"),
        ("PASS_ADMIN: ", "password"), ("pass=", "password"), ("pwd: ", "password"),
        ("credential=", "password"), ("credentials=", "password"), ("SMTP_CREDENTIALS: ", "password"),
        ('"pass": "', "password"), ("openssl enc -pass pass:", "password"),
    ):
        assert_redacts_to(key + FAKE_PASSWORD, key + "[REDACTED:" + kind + "]")
    assert_redacts_to("DB_PASS=" + "hunter" * 2, "DB_PASS=[REDACTED:assignment]")


def test_redaction_command_line_passwords():
    pw = FAKE_PASSWORD
    for sample, expected in (
        ("mysql -u root -p" + pw + " db", "mysql -u root -p[REDACTED:cli-password] db"),
        ("mysqldump -h db1 -u root -p'" + pw + "' app", "mysqldump -h db1 -u root -p'[REDACTED:cli-password]' app"),
        ("mariadb -p" + pw, "mariadb -p[REDACTED:cli-password]"),
        ("curl -u admin:" + pw + " https://x.test", "curl -u admin:[REDACTED:cli-password] https://x.test"),
        ("curl --user admin:" + pw + " https://x.test", "curl --user admin:[REDACTED:cli-password] https://x.test"),
        ("curl -sSL --user=admin:" + pw + " https://x.test",
         "curl -sSL --user=admin:[REDACTED:cli-password] https://x.test"),
        ('curl -u "admin:' + pw + '" https://x.test', 'curl -u "admin:[REDACTED:cli-password]" https://x.test'),
        ("curl -uadmin:" + pw + " https://x.test", "curl -uadmin:[REDACTED:cli-password] https://x.test"),
    ):
        assert_redacts_to(sample, expected)


def test_redaction_cookie_and_authorization_headers():
    tok = FAKE_HEADER_TOKEN
    for sample, expected in (
        ("Cookie: sessionid=" + tok, "Cookie: [REDACTED:cookie]"),
        ("Set-Cookie: sessionid=" + tok + "; Path=/; HttpOnly", "Set-Cookie: [REDACTED:cookie]"),
        ("curl -H 'Cookie: theme=dark; sessionid=" + tok + "' https://x.test",
         "curl -H 'Cookie: [REDACTED:cookie]' https://x.test"),
        ('{"cookie": "sessionid=' + tok + '"}', '{"cookie": "[REDACTED:cookie]"}'),
        ('Set-Cookie: sessionid="' + tok + '"; Path=/', "Set-Cookie: [REDACTED:cookie]"),
        ("'Set-Cookie: a=" + tok + "\\r\\nSet-Cookie: b=" + tok + "'", "'Set-Cookie: [REDACTED:cookie]'"),
        ("Authorization: token " + tok, "Authorization: token [REDACTED:authorization]"),
        ("authorization: Bot " + tok, "authorization: Bot [REDACTED:authorization]"),
        ("Proxy-Authorization: Digest " + tok, "Proxy-Authorization: Digest [REDACTED:authorization]"),
        ('"Authorization": "token ' + tok + '"', '"Authorization": "token [REDACTED:authorization]"'),
        ("Authorization: " + tok, "Authorization: [REDACTED:authorization]"),
        ("Authorization: Bearer " + tok, "Authorization: [REDACTED:bearer]"),
    ):
        assert_redacts_to(sample, expected)


def test_redaction_leaves_harmless_flags_paths_and_prose():
    for harmless in (
        "mkdir -p /tmp/a/b",
        "ssh -p 2222 host",
        "docker run -p 8080:80 img",
        "cp -pR src dst",
        "gcc -pedantic-errors main.c",
        "mysql -u root -p app_db",
        "mysql -h db1 -P 3306 -u root -p",
        "docker exec -u www-data:www-data app ls",
        "PWD=/Users/someone/project",
        "OLDPWD=/home/x/y",
        "PWD=/home/u1/proj2",
        "PASS_FILE=/run/secrets/db1",
        "GOOGLE_APPLICATION_CREDENTIALS=/home/me/key1.json",
        "CREDENTIALS_PATH=C:\\Users\\me\\creds1.json",
        "bypass=truevalue123",
        "compass: northwest-heading",
        "passive: voice123456",
        'password = os.environ["X"]',
        "curl -u",
        "curl -u admin https://x.test",
        'curl -u "$USER:$API_PASSWORD" https://x.test',
        "curl -sSL https://example.com/install.sh",
        "the pass was completed quickly",
        'git commit -m "pass: second attempt at it"',
        "First pass: refactoring everything",
        "if ok: pass",
        "pass_count=12",
        "pytest: 10 passed, 2 failed",
        "Password reset: check the email",
        "fetch(url, { credentials: 'same-origin' })",
        "Client(credentials=credentials)",
        "credential=DefaultAzureCredential()",
        "withCredentials: true",
        "has_credentials=True",
        'input("Password: ") + check("something long here")',
        'log("token: " + token_name + " suffix")',
        'print("password: ", pw, "and more text")',
        "Authorization: the process of granting access",
        "Authorization: Bearer short",
        "Authorization: Basic short",
        "Authorization: token $GITHUB_TOKEN",
        'headers = {"Authorization": f"token {tok}"}',
        'authorization = self.headers.get("authorization")',
        "authorization = authorization.split(':')",
        "the Cookie: header carries state",
        "Cookies: we use them sparingly",
        "document.cookie = 'a=b'",
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


def test_ignored_folder_matches_itself_and_descendants_only():
    with tempfile.TemporaryDirectory() as root:
        ignore = os.path.join(root, "ignore")
        private = os.path.join(root, "work")
        with open(ignore, "w", encoding="utf-8") as f:
            f.write("# Private projects\n\n" + private + os.sep + "\n")
        with patch.object(cap, "IGNORE_FILE", ignore), patch.object(cap, "log"):
            assert cap.is_ignored_folder(private)
            assert cap.is_ignored_folder(os.path.join(private, "project", "nested"))
            assert not cap.is_ignored_folder(private + "-notes")
            assert not cap.is_ignored_folder(root)


def test_ignored_folder_expands_home_and_normalizes_parent_segments():
    with tempfile.TemporaryDirectory() as root:
        ignore = os.path.join(root, "ignore")
        with open(ignore, "w", encoding="utf-8") as f:
            f.write("~/private project\n")
        with patch.object(cap, "IGNORE_FILE", ignore), patch.object(cap, "log"), \
                patch.object(cap.os.path, "expanduser", side_effect=lambda p:
                             os.path.join(root, p[2:]) if p.startswith("~/") else p):
            assert cap.is_ignored_folder(os.path.join(root, "private project", "child", ".."))
            assert not cap.is_ignored_folder(os.path.join(root, "public"))


def test_ignored_folder_windows_paths_and_different_drives():
    with tempfile.TemporaryDirectory() as root:
        ignore = os.path.join(root, "ignore")
        with open(ignore, "w", encoding="utf-8") as f:
            f.write("D:\\Private\nC:\\Users\\Example\\Work\n")
        with patch.object(cap, "IGNORE_FILE", ignore), patch.object(cap, "log"), \
                patch.object(cap, "os", SimpleNamespace(path=ntpath)):
            assert cap.is_ignored_folder("c:/users/example/WORK/project")
            assert cap.is_ignored_folder("D:/PRIVATE")
            assert not cap.is_ignored_folder("C:/Users/Example/Work-notes")
            assert not cap.is_ignored_folder("E:/Private")


def test_ignored_folder_resolves_symlink_aliases():
    with tempfile.TemporaryDirectory() as root:
        private = os.path.join(root, "private")
        alias = os.path.join(root, "alias")
        os.mkdir(private)
        try:
            os.symlink(private, alias, target_is_directory=True)
        except OSError:
            if os.name == "nt":
                return
            raise
        ignore = os.path.join(root, "ignore")
        for listed, cwd in ((private, alias), (alias, private)):
            with open(ignore, "w", encoding="utf-8") as f:
                f.write(listed + "\n")
            with patch.object(cap, "IGNORE_FILE", ignore), patch.object(cap, "log"):
                assert cap.is_ignored_folder(cwd)
                assert cap.is_ignored_folder(os.path.join(cwd, "child"))


def test_missing_or_empty_ignore_list_allows_capture():
    with tempfile.TemporaryDirectory() as root:
        ignore = os.path.join(root, "ignore")
        with patch.object(cap, "IGNORE_FILE", ignore), patch.object(cap, "log") as logged:
            assert not cap.is_ignored_folder(root)
            for text in ("", "\n  # comment\n\n"):
                with open(ignore, "w", encoding="utf-8") as f:
                    f.write(text)
                assert not cap.is_ignored_folder(root)
            logged.assert_not_called()


def test_invalid_ignore_list_skips_capture_without_echoing_contents():
    with tempfile.TemporaryDirectory() as root:
        ignore = os.path.join(root, "ignore")
        for content in (b"relative/private", b"\xff", b"/private\x00folder"):
            with open(ignore, "wb") as f:
                f.write(content)
            with patch.object(cap, "IGNORE_FILE", ignore), patch.object(cap, "log") as logged:
                assert cap.is_ignored_folder(root)
                logged.assert_called_once_with("capture skipped: could not read or validate ~/.pulse/ignore")
        with patch.object(cap, "IGNORE_FILE", root), patch.object(cap, "log"):
            assert cap.is_ignored_folder(root)


def test_ignored_turn_never_reads_transcript_or_sends_event():
    with tempfile.TemporaryDirectory() as root:
        ignore = os.path.join(root, "ignore")
        with open(ignore, "w", encoding="utf-8") as f:
            f.write(root + "\n")
        hook = {"cwd": root, "session_id": "not-for-log", "transcript_path": "not-for-log.jsonl"}
        with patch.object(cap, "IGNORE_FILE", ignore), \
                patch.object(cap, "load_env", return_value=("https://example.invalid", "fake")), \
                patch.object(cap, "sys", SimpleNamespace(stdin=SimpleNamespace(
                    buffer=io.BytesIO(json.dumps(hook).encode("utf-8"))))), \
                patch.object(cap, "extract_from_transcript") as extract, \
                patch.object(cap, "post_event") as post, \
                patch.object(cap, "get_git_info") as git, patch.object(cap, "log") as logged:
            cap.main()
            extract.assert_not_called()
            post.assert_not_called()
            git.assert_not_called()
            logged.assert_called_once_with(f"skipping ignored folder: {os.path.basename(root)!r}")


def test_unlisted_turn_still_captures():
    with tempfile.TemporaryDirectory() as root:
        transcript = os.path.join(root, "transcript.jsonl")
        with open(transcript, "w", encoding="utf-8") as f:
            f.write(json.dumps(user("synthetic prompt")) + "\n")
            f.write(json.dumps(assistant([{"type": "text", "text": "synthetic reply"}])) + "\n")
        hook = {"cwd": root, "session_id": "fake-session", "transcript_path": transcript}
        with patch.object(cap, "IGNORE_FILE", os.path.join(root, "missing-ignore")), \
                patch.object(cap, "load_env", return_value=("https://example.invalid", "fake")), \
                patch.object(cap, "sys", SimpleNamespace(stdin=SimpleNamespace(
                    buffer=io.BytesIO(json.dumps(hook).encode("utf-8"))))), \
                patch.object(cap, "get_git_info", return_value=("project", "user")), \
                patch.object(cap, "post_event") as post:
            cap.main()
            post.assert_called_once()
            assert post.call_args.args[2]["message"] == "synthetic prompt"


EVENT_FIELDS = {"username", "timestamp", "event_id", "message", "response", "project",
                "project_path", "session_id", "model", "source"}
FAKE_SECRET = "npm_" + "a1B2" * 9


def claude_code_hook(root: str) -> dict:
    transcript = os.path.join(root, "transcript.jsonl")
    with open(transcript, "w", encoding="utf-8") as f:
        f.write(json.dumps(user("deploy with " + FAKE_SECRET)) + "\n")
        f.write(json.dumps(assistant([{"type": "text", "text": "used " + FAKE_SECRET}])) + "\n")
    return {"cwd": root, "session_id": "fake-session", "transcript_path": transcript}


HOOK_INPUTS = {"claude-code": claude_code_hook}


def test_every_adapter_returns_the_same_event_and_is_redacted():
    assert set(cap.ADAPTERS) == set(HOOK_INPUTS), "add a fake hook input for each adapter"
    for source, hook_input in HOOK_INPUTS.items():
        with tempfile.TemporaryDirectory() as root:
            with patch.object(cap, "IGNORE_FILE", os.path.join(root, "missing-ignore")), \
                    patch.object(cap, "get_git_info", return_value=("project", "user")):
                event = cap.capture(source, hook_input(root))
        assert set(event) == EVENT_FIELDS, (source, sorted(event))
        assert event["source"] == source, event
        assert all(isinstance(event[k], str) and event[k] for k in EVENT_FIELDS), (source, event)
        for field in ("message", "response"):
            assert FAKE_SECRET not in event[field], (source, field)
            assert "[REDACTED:token]" in event[field], (source, field, event[field])


def test_core_checks_the_ignore_list_before_an_adapter_reads_the_turn():
    with tempfile.TemporaryDirectory() as root:
        ignore = os.path.join(root, "ignore")
        with open(ignore, "w", encoding="utf-8") as f:
            f.write(root + "\n")
        calls = []
        fake = (lambda hook_input: root, lambda hook_input: calls.append(hook_input))
        with patch.object(cap, "IGNORE_FILE", ignore), patch.object(cap, "log"), \
                patch.dict(cap.ADAPTERS, {"fake": fake}):
            assert cap.capture("fake", {}) is None
        assert calls == [], calls


def test_adapter_without_a_turn_sends_nothing():
    with tempfile.TemporaryDirectory() as root:
        fake = (lambda hook_input: root, lambda hook_input: None)
        with patch.object(cap, "IGNORE_FILE", os.path.join(root, "missing-ignore")), \
                patch.dict(cap.ADAPTERS, {"fake": fake}), \
                patch.object(cap, "get_git_info") as git:
            assert cap.capture("fake", {}) is None
            git.assert_not_called()


def test_event_carries_the_source_it_was_captured_with():
    with tempfile.TemporaryDirectory() as root:
        turn = {"prompt": "fake prompt", "response": "", "model": None, "session_id": "fake"}
        fake = (lambda hook_input: root, lambda hook_input: turn)
        with patch.object(cap, "IGNORE_FILE", os.path.join(root, "missing-ignore")), \
                patch.dict(cap.ADAPTERS, {"fake": fake}), \
                patch.object(cap, "get_git_info", return_value=("project", "user")):
            event = cap.capture("fake", {})
    assert event["source"] == "fake" and event["model"] == "unknown", event
    assert event["event_id"] == cap.make_event_id("fake", "fake prompt", ""), event


def test_source_argument():
    assert cap.source_arg([]) == "claude-code"
    assert cap.source_arg(["--source", "codex"]) == "codex"
    assert cap.source_arg(["--source=codex"]) == "codex"
    assert cap.source_arg(["--other", "--source", "cursor"]) == "cursor"
    assert cap.source_arg(["--source"]) == ""
    assert cap.source_arg(["--source="]) == ""


def test_hook_run_as_a_process_reads_its_source_and_stays_silent():
    with tempfile.TemporaryDirectory() as home:
        os.makedirs(os.path.join(home, ".pulse"))
        with open(os.path.join(home, ".pulse", ".env"), "w", encoding="utf-8") as f:
            f.write("CONVEX_URL=https://example.invalid\nCONVEX_TOKEN=fake\n")
        env = {**os.environ, "HOME": home, "USERPROFILE": home}
        if sys.version_info < (3, 10):
            env.pop("PYTHONWARNINGS", None)
        script = os.path.join(REPO, "skills", "setup", "capture.py")
        for argv in (["--source", "nope"], ["--source=nope"]):
            result = subprocess.run([sys.executable, script, *argv], input=b"{}", env=env,
                                    capture_output=True, timeout=30)
            assert (result.returncode, result.stdout, result.stderr) == (0, b"", b""), result
        with open(os.path.join(home, ".pulse", "capture.log"), encoding="utf-8") as f:
            lines = f.read().splitlines()
        assert len(lines) == 2 and all("unknown source 'nope'" in line for line in lines), lines


def run_main(hook: dict, argv=None):
    with patch.object(cap, "load_env", return_value=("https://example.invalid", "fake")), \
            patch.object(cap, "sys", SimpleNamespace(stdin=SimpleNamespace(
                buffer=io.BytesIO(json.dumps(hook).encode("utf-8"))))), \
            patch.object(cap, "get_git_info", return_value=("project", "user")), \
            patch.object(cap, "post_event") as post, patch.object(cap, "log") as logged:
        cap.main() if argv is None else cap.main(argv)
    return post, logged


def test_hook_command_without_a_source_still_captures_as_claude_code():
    with tempfile.TemporaryDirectory() as root:
        with patch.object(cap, "IGNORE_FILE", os.path.join(root, "missing-ignore")):
            post, _ = run_main(claude_code_hook(root))
            explicit, _ = run_main(claude_code_hook(root), ["--source", "claude-code"])
    post.assert_called_once()
    assert post.call_args.args[2]["source"] == "claude-code"
    assert explicit.call_args.args[2]["source"] == "claude-code"
    assert post.call_args.args[2]["event_id"] == explicit.call_args.args[2]["event_id"]


def test_unknown_source_sends_nothing_and_says_so():
    with tempfile.TemporaryDirectory() as root:
        for argv in (["--source", "nope"], ["--source"]):
            post, logged = run_main(claude_code_hook(root), argv)
            post.assert_not_called()
            logged.assert_called_once()
            assert "unknown source" in logged.call_args.args[0], logged.call_args


def test_event_id_formula_is_pinned_and_uses_the_unredacted_turn():
    assert cap.make_event_id("fake-session", "first prompt", "first answer") == \
        "d892bdc5927022dc11b56c4ac4aa4643"
    with tempfile.TemporaryDirectory() as root:
        with patch.object(cap, "IGNORE_FILE", os.path.join(root, "missing-ignore")), \
                patch.object(cap, "get_git_info", return_value=("project", "user")):
            event = cap.capture("claude-code", claude_code_hook(root))
    assert event["event_id"] == cap.make_event_id(
        "fake-session", "deploy with " + FAKE_SECRET, "used " + FAKE_SECRET), event


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
