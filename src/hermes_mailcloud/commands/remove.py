"""Guarded permanent remote removal through the typed rclone backend."""

from __future__ import annotations

from dataclasses import dataclass

from ..config import ResolvedConfig
from ..core.errors import ErrorKind, ErrorPayload, MailCloudError
from ..core.paths import normalize_remote_path
from ..core.policy import OperationRequest, validate_operation
from .backend import RcloneBackend, configured_target

_RESERVED_REMOVAL_ROOTS = frozenset({"/", "/Hermes", "/TEST"})


@dataclass(frozen=True, slots=True)
class RemoveCommand:
    """Delete one file or recursively purge one non-reserved remote path."""

    backend: RcloneBackend
    config: ResolvedConfig
    timeout_seconds: float

    def __post_init__(self) -> None:
        if isinstance(self.timeout_seconds, bool) or self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")

    def run(
        self,
        remote_path: str,
        *,
        recursive: bool = False,
        dry_run: bool = False,
        yes: bool = False,
        retries: int = 0,
    ) -> dict[str, object]:
        """Require confirmation and reject protected roots before one rclone command."""
        if not isinstance(recursive, bool):
            raise MailCloudError(
                ErrorPayload(ErrorKind.INVALID_ARGUMENTS, "recursive must be a boolean")
            )
        decision = validate_operation(
            OperationRequest(
                "rm",
                remote_path=remote_path,
                dry_run=dry_run,
                yes=yes,
                retries=retries,
            )
        )
        assert decision.remote_path is not None
        _reject_protected_removal_target(decision.remote_path, self.config)
        target = configured_target(self.config, decision.remote_path)
        result: dict[str, object] = {
            "remote_path": decision.remote_path,
            "recursive": recursive,
        }
        if decision.is_dry_run:
            return {**result, **decision.dry_run_result()}

        command = "purge" if recursive else "deletefile"
        self.backend.require_success([command, target], timeout_seconds=self.timeout_seconds)
        return {**result, "deleted": True}


def _reject_protected_removal_target(remote_path: str, config: ResolvedConfig) -> None:
    """Keep service roots intact while allowing callers to manage their descendants."""
    protected_paths = _protected_removal_paths(config)
    if remote_path in protected_paths:
        raise MailCloudError(
            ErrorPayload(ErrorKind.INVALID_ARGUMENTS, "rm cannot target a protected remote root")
        )


def _protected_removal_paths(config: ResolvedConfig) -> frozenset[str]:
    """Collect normalized exact roots that must never be passed to destructive rclone calls."""
    return _RESERVED_REMOVAL_ROOTS | frozenset(
        normalize_remote_path(path)
        for path in (config.private_root, config.public_root, config.temp_root)
    )
