"""Private upload and atomic local download adapters through rclone."""

from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass
from pathlib import Path

from ..config import ResolvedConfig
from ..core.errors import ErrorKind, ErrorPayload, MailCloudError
from ..core.policy import OperationRequest, validate_operation
from .backend import RcloneBackend, configured_target

OVERWRITE_MODES = frozenset({"never", "always", "if-newer"})


def resolve_overwrite(overwrite: str | None, config: ResolvedConfig) -> str:
    """Choose one frozen overwrite mode without accepting an implicit backend default."""
    resolved = config.default_overwrite if overwrite is None else overwrite
    if not isinstance(resolved, str) or resolved not in OVERWRITE_MODES:
        raise MailCloudError(
            ErrorPayload(
                ErrorKind.INVALID_ARGUMENTS,
                "overwrite must be one of: never, always, if-newer",
            )
        )
    return resolved


def overwrite_args(overwrite: str) -> tuple[str, ...]:
    """Map the public overwrite modes to rclone's target-preserving flags."""
    if overwrite == "never":
        return ("--immutable",)
    if overwrite == "always":
        return ("--ignore-times",)
    if overwrite == "if-newer":
        return ("--update",)
    raise ValueError("overwrite must be a validated v0.1 overwrite mode")


@dataclass(frozen=True, slots=True)
class TransferCommands:
    """Execute uploads and downloads without public-link or write-retry behavior."""

    backend: RcloneBackend
    config: ResolvedConfig
    timeout_seconds: float

    def __post_init__(self) -> None:
        if isinstance(self.timeout_seconds, bool) or self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")

    def upload(
        self,
        local_path: str,
        remote_path: str,
        *,
        overwrite: str | None = None,
        dry_run: bool = False,
        retries: int = 0,
    ) -> dict[str, object]:
        """Copy one existing local file to a private-or-public remote path without linking it."""
        decision = validate_operation(
            OperationRequest("upload", remote_path=remote_path, dry_run=dry_run, retries=retries)
        )
        assert decision.remote_path is not None
        target = configured_target(self.config, decision.remote_path)
        source, source_size = _require_local_source(local_path)
        overwrite_mode = resolve_overwrite(overwrite, self.config)
        result: dict[str, object] = {
            "local_path": local_path,
            "remote_path": decision.remote_path,
            "published": False,
            "bytes": source_size,
            "overwrite": overwrite_mode,
        }
        if decision.is_dry_run:
            return {**result, **decision.dry_run_result()}

        self.backend.require_success(
            ["copyto", str(source), target, *overwrite_args(overwrite_mode)],
            timeout_seconds=self.timeout_seconds,
        )
        return result

    def download(
        self,
        remote_path: str,
        local_path: str,
        *,
        overwrite: str | None = None,
        dry_run: bool = False,
        retries: int = 0,
    ) -> dict[str, object]:
        """Download through a sibling temporary file and only commit after rclone succeeds."""
        decision = validate_operation(
            OperationRequest("download", remote_path=remote_path, dry_run=dry_run, retries=retries)
        )
        assert decision.remote_path is not None
        source = configured_target(self.config, decision.remote_path)
        destination = _require_local_destination(local_path)
        overwrite_mode = resolve_overwrite(overwrite, self.config)
        if overwrite_mode == "never" and destination.exists():
            raise MailCloudError(
                ErrorPayload(ErrorKind.CONFLICT, "local download destination already exists")
            )

        result: dict[str, object] = {
            "remote_path": decision.remote_path,
            "local_path": local_path,
            "overwrite": overwrite_mode,
        }
        if decision.is_dry_run:
            return {**result, **decision.dry_run_result()}

        temporary = _temporary_download_path(destination)
        try:
            self.backend.require_success(
                ["copyto", source, str(temporary)], timeout_seconds=self.timeout_seconds
            )
            if not temporary.is_file():
                raise MailCloudError(
                    ErrorPayload(
                        ErrorKind.UNKNOWN_ERROR,
                        "rclone download did not produce a local temporary file",
                    )
                )
            updated, byte_count = _commit_download(temporary, destination, overwrite_mode)
            return {**result, "bytes": byte_count, "updated": updated}
        finally:
            _remove_temporary_download(temporary)


def _require_local_source(local_path: str) -> tuple[Path, int]:
    source = _local_path(local_path, role="upload source")
    try:
        if source.is_file():
            return source, source.stat().st_size
        if source.exists():
            raise MailCloudError(
                ErrorPayload(
                    ErrorKind.INVALID_ARGUMENTS, "local upload source must be a regular file"
                )
            )
    except OSError as exc:
        raise MailCloudError(
            ErrorPayload(ErrorKind.INVALID_ARGUMENTS, "local upload source could not be inspected")
        ) from exc
    raise MailCloudError(ErrorPayload(ErrorKind.NOT_FOUND, "local upload source was not found"))


def _require_local_destination(local_path: str) -> Path:
    destination = _local_path(local_path, role="download destination")
    try:
        if destination.name in {"", "."} or destination.is_symlink():
            raise MailCloudError(
                ErrorPayload(
                    ErrorKind.INVALID_ARGUMENTS, "local download destination must not be a symlink"
                )
            )
        if not destination.parent.is_dir():
            raise MailCloudError(
                ErrorPayload(
                    ErrorKind.INVALID_ARGUMENTS,
                    "local download destination parent directory does not exist",
                )
            )
        if destination.exists() and not destination.is_file():
            raise MailCloudError(
                ErrorPayload(
                    ErrorKind.INVALID_ARGUMENTS,
                    "local download destination must be a file path",
                )
            )
        return destination
    except OSError as exc:
        raise MailCloudError(
            ErrorPayload(
                ErrorKind.INVALID_ARGUMENTS, "local download destination could not be inspected"
            )
        ) from exc


def _local_path(value: str, *, role: str) -> Path:
    if not isinstance(value, str) or not value or "\x00" in value:
        raise MailCloudError(
            ErrorPayload(
                ErrorKind.INVALID_ARGUMENTS,
                f"local {role} path must be non-empty and contain no NUL",
            )
        )
    return Path(value)


def _temporary_download_path(destination: Path) -> Path:
    try:
        descriptor, raw_path = tempfile.mkstemp(
            prefix=f".{destination.name}.", suffix=".hermes-mailcloud-part", dir=destination.parent
        )
        os.close(descriptor)
        temporary = Path(raw_path)
        temporary.unlink()
        return temporary
    except OSError as exc:
        raise MailCloudError(
            ErrorPayload(
                ErrorKind.UNKNOWN_ERROR, "could not create a local temporary download path"
            )
        ) from exc


def _commit_download(temporary: Path, destination: Path, overwrite: str) -> tuple[bool, int]:
    """Atomically expose a completed local download while preserving a failed target."""
    try:
        temporary_stat = temporary.stat()
        if overwrite == "never":
            try:
                os.link(temporary, destination)
            except FileExistsError as exc:
                raise MailCloudError(
                    ErrorPayload(ErrorKind.CONFLICT, "local download destination already exists")
                ) from exc
            return True, temporary_stat.st_size
        if overwrite == "if-newer" and destination.exists():
            destination_stat = destination.stat()
            if temporary_stat.st_mtime_ns <= destination_stat.st_mtime_ns:
                return False, destination_stat.st_size
        os.replace(temporary, destination)
        return True, temporary_stat.st_size
    except MailCloudError:
        raise
    except OSError as exc:
        raise MailCloudError(
            ErrorPayload(ErrorKind.UNKNOWN_ERROR, "could not safely commit the local download")
        ) from exc


def _remove_temporary_download(temporary: Path) -> None:
    try:
        temporary.unlink(missing_ok=True)
    except OSError:
        pass
