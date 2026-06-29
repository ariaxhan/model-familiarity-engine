"""Redaction gate — scrub secrets before any content leaves for a third-party model.

This is the hard boundary for replaying private work logs. Nothing leaves for a
third-party model unredacted.

Design: **fail-closed, with an independent verifier.**

1. ``redact(text)`` scrubs known secret/PII patterns, replacing each with a typed
   placeholder ``[REDACTED:<kind>]``.
2. ``verify_clean(text)`` re-scans with the *same* detectors and returns any surviving
   findings. It does not trust that ``redact`` ran — it is the floor test.
3. ``assert_clean(text)`` raises :class:`SecretLeakError` if ``verify_clean`` finds
   anything. The replay harness calls this immediately before sending to a provider, so a
   detector gap or a new secret shape stops the send rather than leaking.

The scrubber preserves task *structure* (code, prose, file layout) so the task is still
replayable — it removes secrets and identifying tokens, not content. Content-level
privacy (shipping private business logic at all) is a task-selection decision, not
something this gate can automate; pick non-sensitive tasks for replay.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

PLACEHOLDER_RE = re.compile(r"\[REDACTED:[a-z0-9_]+\]")


@dataclass(frozen=True)
class Finding:
    """One detected secret/PII span."""

    kind: str
    start: int
    end: int
    preview: str  # first/last few chars only — never the full secret


class SecretLeakError(Exception):
    """Raised when content still carries a secret after redaction (fail-closed)."""

    def __init__(self, findings: list[Finding]):
        self.findings = findings
        kinds = ", ".join(sorted({f.kind for f in findings}))
        super().__init__(
            f"redaction gate: {len(findings)} secret(s) survived "
            f"[{kinds}] — refusing to send"
        )


# Each detector is (kind, compiled regex). Order matters: structural blocks
# (private keys) before line-level patterns so the broad match wins first.
#
# Patterns are tuned for precision over recall on *obvious* secret shapes, then
# backstopped by the assignment heuristic (anything named like a secret with a
# quoted value). High-entropy bare strings are NOT auto-redacted (too many false
# positives on code/hashes); they are caught only when assigned to a secret-named
# variable. Pick non-sensitive replay tasks rather than relying on entropy guesses.
_DETECTORS: list[tuple[str, re.Pattern[str]]] = [
    (
        "private_key",
        re.compile(
            r"-----BEGIN (?:[A-Z ]+ )?PRIVATE KEY-----.*?-----END (?:[A-Z ]+ )?PRIVATE KEY-----",
            re.DOTALL,
        ),
    ),
    ("aws_access_key", re.compile(r"\b(?:AKIA|ASIA|AGPA|AIDA|AROA|ANPA)[0-9A-Z]{16}\b")),
    (
        "aws_secret_key",
        re.compile(
            r"(?i)aws_secret_access_key\s*[=:]\s*['\"]?([A-Za-z0-9/+]{40})['\"]?"
        ),
    ),
    ("openai_key", re.compile(r"\bsk-(?:proj-|svcacct-)?[A-Za-z0-9_\-]{20,}\b")),
    ("anthropic_key", re.compile(r"\bsk-ant-[A-Za-z0-9_\-]{20,}\b")),
    ("github_token", re.compile(r"\bgh[posru]_[A-Za-z0-9]{30,}\b")),
    ("github_pat", re.compile(r"\bgithub_pat_[A-Za-z0-9_]{30,}\b")),
    ("google_api_key", re.compile(r"\bAIza[0-9A-Za-z_\-]{35}\b")),
    ("slack_token", re.compile(r"\bxox[baprs]-[0-9A-Za-z\-]{10,}\b")),
    ("stripe_key", re.compile(r"\b[rs]k_(?:live|test)_[A-Za-z0-9]{20,}\b")),
    ("jwt", re.compile(r"\beyJ[A-Za-z0-9_\-]{8,}\.eyJ[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}\b")),
    ("bearer_token", re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._\-]{20,}")),
    # Secret-named variable assignment: KEY = "value" / "token": "value" / export SECRET=value
    (
        "assigned_secret",
        re.compile(
            r"""(?ix)
            \b(?:api[_-]?key|secret(?:[_-]?key)?|access[_-]?token|auth[_-]?token|
               client[_-]?secret|password|passwd|private[_-]?key|bearer)\b
            \s*[:=]\s*
            ['"]?
            ([^\s'"]{8,})
            ['"]?
            """
        ),
    ),
    ("email", re.compile(r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b")),
    # Home-directory username — identity leak. Redact only the username segment.
    ("home_user", re.compile(r"/(?:Users|home)/([^/\s'\"]+)")),
]

# Detectors whose *value* group (1) is the secret while group 0 is contextual
# (keep the context, redact the captured value).
_GROUP1_DETECTORS = {"aws_secret_key", "assigned_secret", "home_user"}


def _preview(s: str) -> str:
    s = s.replace("\n", " ")
    if len(s) <= 10:
        return s[:2] + "…"
    return f"{s[:3]}…{s[-2:]}"


def scan(text: str) -> list[Finding]:
    """Return all secret/PII findings in *text* (no mutation)."""
    findings: list[Finding] = []
    for kind, pat in _DETECTORS:
        for m in pat.finditer(text):
            if kind in _GROUP1_DETECTORS and m.lastindex:
                start, end = m.start(1), m.end(1)
            else:
                start, end = m.start(), m.end()
            findings.append(Finding(kind, start, end, _preview(text[start:end])))
    return findings


def redact(text: str) -> tuple[str, list[Finding]]:
    """Scrub secrets/PII from *text*. Returns (redacted_text, findings).

    Replaces each detected span with ``[REDACTED:<kind>]``. For group-1 detectors
    (e.g. ``aws_secret_access_key = "..."``) only the value is replaced, the
    surrounding context is kept so the structure stays legible.
    """
    if not text:
        return text, []
    findings = scan(text)
    if not findings:
        return text, []
    # Replace right-to-left so earlier offsets stay valid.
    findings_sorted = sorted(findings, key=lambda f: f.start, reverse=True)
    out = text
    for f in findings_sorted:
        out = out[: f.start] + f"[REDACTED:{f.kind}]" + out[f.end :]
    return out, findings


def verify_clean(text: str) -> list[Finding]:
    """Independent re-scan. Returns findings that are NOT already placeholders.

    This is the floor test: it does not assume ``redact`` ran. A finding here means
    a real secret slipped through.
    """
    if not text:
        return []
    surviving = []
    for f in scan(text):
        span = text[f.start : f.end]
        # A span fully inside a placeholder is not a leak.
        if PLACEHOLDER_RE.fullmatch(span) or span.startswith("[REDACTED:"):
            continue
        surviving.append(f)
    return surviving


def assert_clean(text: str) -> None:
    """Raise :class:`SecretLeakError` if any secret survives. Fail-closed gate."""
    findings = verify_clean(text)
    if findings:
        raise SecretLeakError(findings)


def redact_obj(obj):
    """Recursively redact every string in a nested dict/list structure.

    Used on mined task tuples before they are persisted or replayed.
    """
    if isinstance(obj, str):
        return redact(obj)[0]
    if isinstance(obj, dict):
        return {k: redact_obj(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [redact_obj(v) for v in obj]
    return obj


def assert_obj_clean(obj) -> None:
    """Fail-closed gate over a nested structure (every string must be clean)."""
    leaks: list[Finding] = []

    def walk(o):
        if isinstance(o, str):
            leaks.extend(verify_clean(o))
        elif isinstance(o, dict):
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)

    walk(obj)
    if leaks:
        raise SecretLeakError(leaks)
