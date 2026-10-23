"""Sanitized serialization for JSON-first command output and diagnostics."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from typing import Any

SENSITIVE_KEY_PATTERN = re.compile(
    r"(?i)^(access[_-]?token|refresh[_-]?token|api[_-]?key|password|passwd|secret|token|cookie|authorization)$"
)
SENSITIVE_NAME = (
    r"access[_-]?token|refresh[_-]?token|api[_-]?key|password|passwd|secret|token|cookie|"
    r"authorization"
)
PUBLIC_URL_PATTERN = re.compile(r"https://cloud\.mail\.ru/public/[^\s'\"<>]+", re.IGNORECASE)
SENSITIVE_ASSIGNMENT_PATTERN = re.compile(
    rf"""(?ix)
    (?P<prefix>[\"']?(?:{SENSITIVE_NAME})[\"']?\s*[:=]\s*)
    (?P<value>
        \"(?:\\.|[^\"\\])*\"
        | '(?:\\.|[^'\\])*'
        # A marker is one value unit, never a reason to trust an adjacent suffix.
        | (?: \[REDACTED\] | [^\s,;}}\]] )+
    )
    """
)
ESCAPED_SENSITIVE_ASSIGNMENT_PATTERN = re.compile(
    rf"""(?ix)
    (?P<prefix>\\+[\"'](?:{SENSITIVE_NAME})\\+[\"']\s*[:=]\s*\\+[\"'])
    (?P<value>[^\r\n]*?)
    (?P<suffix>\\+[\"'])
    (?=\s*(?:[,;}}\]]|$))
    """
)
HEADER_PATTERN = re.compile(r"(?i)(?P<prefix>\b(?:authorization|cookie)\s*:\s*)[^\r\n]+")
BEARER_PATTERN = re.compile(r"(?i)\bbearer\s+[^\s,;]+")


def redact_text(value: str) -> str:
    """Redact credentials and replace public capability URLs with fingerprints."""

    def redact_public_url(match: re.Match[str]) -> str:
        digest = hashlib.sha256(match.group(0).encode("utf-8")).hexdigest()
        return f"[public-url sha256:{digest}]"

    redacted = PUBLIC_URL_PATTERN.sub(redact_public_url, value)
    redacted = ESCAPED_SENSITIVE_ASSIGNMENT_PATTERN.sub(r"\g<prefix>[REDACTED]\g<suffix>", redacted)
    redacted = HEADER_PATTERN.sub(r"\g<prefix>[REDACTED]", redacted)
    redacted = BEARER_PATTERN.sub("Bearer [REDACTED]", redacted)
    return SENSITIVE_ASSIGNMENT_PATTERN.sub(r"\g<prefix>[REDACTED]", redacted)


def sanitize_value(value: Any) -> Any:
    """Recursively sanitize values before they can enter JSON or diagnostics."""
    if isinstance(value, str):
        return redact_text(value)
    if isinstance(value, Mapping):
        return {
            str(key): "[REDACTED]" if _is_sensitive_key(str(key)) else sanitize_value(item)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [sanitize_value(item) for item in value]
    return value


def render_json(value: Any, *, pretty: bool = False) -> str:
    """Serialize already-sanitized JSON with deterministic object-key ordering."""
    kwargs: dict[str, Any] = {"ensure_ascii": False, "sort_keys": True}
    if pretty:
        kwargs["indent"] = 2
    return json.dumps(sanitize_value(value), **kwargs)


def _is_sensitive_key(key: str) -> bool:
    return SENSITIVE_KEY_PATTERN.fullmatch(key.strip()) is not None
