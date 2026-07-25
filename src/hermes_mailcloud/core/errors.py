"""Frozen v0.1 error kinds and process exit-code mapping."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class ErrorKind(StrEnum):
    """Machine-stable error kinds accepted by the result-envelope schema."""

    UNKNOWN_ERROR = "unknown_error"
    INVALID_ARGUMENTS = "invalid_arguments"
    CONFIG_ERROR = "config_error"
    RCLONE_NOT_FOUND = "rclone_not_found"
    REMOTE_NOT_CONFIGURED = "remote_not_configured"
    ACCESS_DENIED = "access_denied"
    NOT_FOUND = "not_found"
    CONFLICT = "conflict"
    UNSAFE_PUBLIC_PATH = "unsafe_public_path"
    DANGEROUS_FILE_PATTERN = "dangerous_file_pattern"
    CONFIRMATION_REQUIRED = "confirmation_required"
    NETWORK_ERROR = "network_error"
    RETRY_EXHAUSTED = "retry_exhausted"
    BACKEND_UNSUPPORTED = "backend_unsupported"
    PARSE_ERROR = "parse_error"
    TIMEOUT = "timeout"


EXIT_CODE_BY_KIND: dict[ErrorKind, int] = {
    ErrorKind.UNKNOWN_ERROR: 1,
    ErrorKind.INVALID_ARGUMENTS: 2,
    ErrorKind.CONFIG_ERROR: 3,
    ErrorKind.RCLONE_NOT_FOUND: 4,
    ErrorKind.REMOTE_NOT_CONFIGURED: 5,
    ErrorKind.ACCESS_DENIED: 6,
    ErrorKind.NOT_FOUND: 7,
    ErrorKind.CONFLICT: 8,
    ErrorKind.UNSAFE_PUBLIC_PATH: 9,
    ErrorKind.DANGEROUS_FILE_PATTERN: 9,
    ErrorKind.CONFIRMATION_REQUIRED: 9,
    ErrorKind.NETWORK_ERROR: 10,
    ErrorKind.RETRY_EXHAUSTED: 10,
    ErrorKind.BACKEND_UNSUPPORTED: 12,
    ErrorKind.PARSE_ERROR: 13,
    ErrorKind.TIMEOUT: 14,
}


@dataclass(frozen=True, slots=True)
class ErrorPayload:
    """Typed error body for a JSON result envelope."""

    kind: ErrorKind
    message: str
    details: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.message.strip():
            raise ValueError("error messages must not be empty")

    @property
    def exit_code(self) -> int:
        """Return the contractually frozen process exit code for this error."""
        return EXIT_CODE_BY_KIND[self.kind]

    def to_payload(self) -> dict[str, Any]:
        """Return the schema-shaped mapping before final output sanitization."""
        payload: dict[str, Any] = {
            "kind": self.kind.value,
            "message": self.message,
            "exit_code": self.exit_code,
        }
        if self.details:
            payload["details"] = dict(self.details)
        return payload


class MailCloudError(Exception):
    """Expected product error carrying a schema-compatible typed payload."""

    def __init__(self, error: ErrorPayload) -> None:
        super().__init__(error.message)
        self.error = error
