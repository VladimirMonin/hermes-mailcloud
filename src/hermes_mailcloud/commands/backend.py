"""Typed backend boundary shared by v0.1 command adapters."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from ..config import ResolvedConfig
from ..core.errors import ErrorKind, ErrorPayload, MailCloudError
from ..core.paths import qualify_remote_path
from ..rclone.runner import RcloneResult


class RcloneBackend(Protocol):
    """Minimal backend interface command adapters need from the subprocess runner."""

    def require_success(
        self, args: Sequence[str], *, timeout_seconds: float | None = None
    ) -> RcloneResult: ...


def configured_target(config: ResolvedConfig, remote_path: str) -> str:
    """Assemble a backend target only after configuration and policy validation."""
    if config.remote is None:
        raise MailCloudError(
            ErrorPayload(ErrorKind.REMOTE_NOT_CONFIGURED, "no rclone remote is configured")
        )
    return qualify_remote_path(config.remote, remote_path)
