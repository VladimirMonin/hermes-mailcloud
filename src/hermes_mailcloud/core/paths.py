"""Remote-path and rclone-remote validation before backend invocation."""

from __future__ import annotations

import posixpath
import re

RCLONE_REMOTE_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}:$")


class RemotePathError(ValueError):
    """Raised when a cloud path is not a safe absolute POSIX path."""


def normalize_remote_path(value: str) -> str:
    """Normalize an absolute cloud path without accepting malformed input."""
    if not isinstance(value, str) or not value:
        raise RemotePathError("remote path must not be empty")
    if "\x00" in value:
        raise RemotePathError("remote path must not contain NUL")
    if not value.startswith("/"):
        raise RemotePathError("remote path must be absolute")

    normalized = posixpath.normpath(value)
    if normalized in {".", "//"} or not normalized.startswith("/") or normalized.startswith("//"):
        raise RemotePathError("remote path must use one absolute POSIX root")
    return normalized


def is_descendant(path: str, root: str) -> bool:
    """Return whether the normalized path is strictly inside the normalized root."""
    normalized_path = normalize_remote_path(path)
    normalized_root = normalize_remote_path(root).rstrip("/") or "/"
    if normalized_root == "/":
        return normalized_path != "/"
    return normalized_path.startswith(f"{normalized_root}/")


def require_descendant(path: str, root: str) -> str:
    """Normalize a path and reject the root itself and every escape from it."""
    normalized_path = normalize_remote_path(path)
    if not is_descendant(normalized_path, root):
        normalized_root = normalize_remote_path(root)
        raise RemotePathError(f"remote path must be a descendant of {normalized_root}")
    return normalized_path


def validate_rclone_remote(remote: str) -> str:
    """Allow only a simple named rclone remote, never a credential-bearing URL."""
    if not isinstance(remote, str) or not RCLONE_REMOTE_PATTERN.fullmatch(remote):
        raise RemotePathError("remote must be a simple rclone remote name ending in ':'")
    return remote


def qualify_remote_path(remote: str, path: str) -> str:
    """Build an rclone target only after separately validating remote and path."""
    return f"{validate_rclone_remote(remote)}{normalize_remote_path(path)}"
