"""Redaction gate tests — the secret-leak floor.

The gate is the hard boundary before content leaves for a third-party model. These
tests inject realistic secret shapes and prove (a) they are scrubbed, (b) the
independent verifier reports zero leaks afterward, and (c) the gate fails CLOSED on
raw secrets (assert_clean raises). A regression here = a potential live secret leak.

NOTE: fake secrets are assembled from fragments via ``j()`` so no literal secret
pattern sits in this source file (the repo's pre-commit secret-detection hook scans
file text, and these are deliberately secret-shaped).
"""

from __future__ import annotations

import pytest

from model_familiarity.redact import (
    SecretLeakError,
    assert_clean,
    assert_obj_clean,
    redact,
    redact_obj,
    verify_clean,
)


def j(*parts: str) -> str:
    """Join fragments into a secret-shaped string at runtime."""
    return "".join(parts)


# (label, raw_text_containing_secret, kind_expected)
SECRET_SAMPLES = [
    ("aws_access", "key is " + j("AKIA", "1234567890ABCDEF") + " in config", "aws_access_key"),
    (
        "aws_secret",
        'aws_secret_access_key = "' + j("wJalrXUtnFEMIabcd1234567890ABCDEFGHIJ5678") + '"',
        "aws_secret_key",
    ),
    ("openai", "OPENAI=" + j("sk-", "proj-abcdefghijklmnopqrstuvwxyz1234"), "openai_key"),
    (
        "anthropic",
        "ANTHROPIC_API_KEY=" + j("sk-", "ant-api03-abcdef_ghijklmnop-qrstuv"),
        "anthropic_key",
    ),
    (
        "github",
        "token " + j("ghp_", "abcdefghijklmnopqrstuvwxyz0123456789AB") + " done",
        "github_token",
    ),
    ("google", j("AIza", "SyA1234567890abcdefghijklmnop_qrstu") + " key", "google_api_key"),
    ("slack", j("xox", "b-12345678901-abcdefghijklmnop"), "slack_token"),
    ("stripe", j("sk_", "live_abcdefghijklmnopqrstuvwx") + " done", "stripe_key"),
    (
        "jwt",
        "auth: " + j("eyJ", "hbGciOiJIUzI1NiI", ".eyJ", "zdWIiOiIxMjM0NTY", ".SflKxwRJSMeKKF2QT4f"),
        "jwt",
    ),
    ("bearer", "Authorization: " + j("Bearer ", "abcdefghijklmnopqrstuvwxyz12"), "bearer_token"),
    ("assigned", 'password = "' + j("hunter2hunter2") + '"', "assigned_secret"),
    ("email", "contact " + j("ariaxhan", "@", "gmail.com") + " for access", "email"),
    ("home", "/Users/" + j("slowember") + "/Documents/secret.txt", "home_user"),
]

PRIVATE_KEY = (
    j("-----BEGIN ", "RSA PRIVATE KEY-----") + "\n"
    "MIIEpAIBAAKCAQEA1234567890abcdefghABCDEFGH\n"
    "qrstuvwxyzQRSTUVWXYZ0987654321zyxwvut\n"
    + j("-----END ", "RSA PRIVATE KEY-----")
)


@pytest.mark.parametrize("label,raw,kind", SECRET_SAMPLES, ids=[s[0] for s in SECRET_SAMPLES])
def test_secret_is_scrubbed(label, raw, kind):
    redacted, findings = redact(raw)
    assert any(f.kind == kind for f in findings), f"{label}: {kind} not detected"
    assert f"[REDACTED:{kind}]" in redacted, f"{label}: placeholder missing"


@pytest.mark.parametrize("label,raw,kind", SECRET_SAMPLES, ids=[s[0] for s in SECRET_SAMPLES])
def test_no_leak_after_redaction(label, raw, kind):
    """FLOOR TEST: after redaction the independent verifier finds zero leaks."""
    redacted, _ = redact(raw)
    assert verify_clean(redacted) == [], f"{label}: secret survived redaction"


@pytest.mark.parametrize("label,raw,kind", SECRET_SAMPLES, ids=[s[0] for s in SECRET_SAMPLES])
def test_gate_fails_closed_on_raw(label, raw, kind):
    """assert_clean MUST raise on un-redacted secrets — the fail-closed contract."""
    with pytest.raises(SecretLeakError):
        assert_clean(raw)


def test_private_key_block_scrubbed():
    redacted, findings = redact("here:\n" + PRIVATE_KEY + "\nend")
    assert any(f.kind == "private_key" for f in findings)
    assert "PRIVATE KEY" not in redacted
    assert verify_clean(redacted) == []


def test_home_user_redacts_username_keeps_path_shape():
    redacted, _ = redact("/Users/" + j("slowember") + "/Documents/Vaults/file.py")
    assert "slowember" not in redacted
    # path structure preserved so the task is still legible
    assert "/Documents/Vaults/file.py" in redacted


def test_clean_text_untouched():
    clean = "def add(a, b):\n    return a + b  # no secrets here"
    redacted, findings = redact(clean)
    assert redacted == clean
    assert findings == []
    assert verify_clean(clean) == []


def test_redact_is_idempotent():
    raw = (
        "OPENAI=" + j("sk-", "proj-abcdefghijklmnopqrstuvwxyz1234")
        + " and /Users/" + j("slowember") + "/x"
    )
    once, _ = redact(raw)
    twice, _ = redact(once)
    assert once == twice
    assert verify_clean(twice) == []


def test_multiple_secrets_one_pass():
    raw = (
        "export OPENAI=" + j("sk-", "proj-abcdefghijklmnopqrstuvwxyz1234") + "\n"
        "export AWS=" + j("AKIA", "1234567890ABCDEF") + "\n"
        "email " + j("ariaxhan", "@", "gmail.com")
    )
    redacted, findings = redact(raw)
    kinds = {f.kind for f in findings}
    assert {"openai_key", "aws_access_key", "email"} <= kinds
    assert verify_clean(redacted) == []


def test_redact_obj_walks_nested_structure():
    tup = {
        "prompt": "fix the bug, key is " + j("AKIA", "1234567890ABCDEF"),
        "trajectory": [
            {"text": "I'll use " + j("sk-", "proj-abcdefghijklmnopqrstuvwxyz1234")},
            {"text": "clean line"},
        ],
        "meta": {"cwd": "/Users/" + j("slowember") + "/repo"},
    }
    cleaned = redact_obj(tup)
    # fail-closed gate over the whole structure must now pass
    assert_obj_clean(cleaned)
    assert "1234567890ABCDEF" not in str(cleaned)
    assert "slowember" not in str(cleaned)


def test_assert_obj_clean_raises_on_dirty_structure():
    dirty = {"a": ["fine", j("AKIA", "1234567890ABCDEF")], "b": "ok"}
    with pytest.raises(SecretLeakError):
        assert_obj_clean(dirty)
