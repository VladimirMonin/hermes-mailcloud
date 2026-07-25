"""Remote move and copy adapters with explicit overwrite modes."""

from __future__ import annotations

from dataclasses import dataclass

from ..config import ResolvedConfig
from ..core.errors import ErrorKind, ErrorPayload, MailCloudError
from ..core.policy import OperationRequest, validate_operation
from .backend import RcloneBackend, configured_target
from .transfer import overwrite_args, resolve_overwrite


@dataclass(frozen=True, slots=True)
class MoveCopyCommands:
    """Perform one non-retried move or copy after both remote paths are validated."""

    backend: RcloneBackend
    config: ResolvedConfig
    timeout_seconds: float

    def __post_init__(self) -> None:
        if isinstance(self.timeout_seconds, bool) or self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")

    def move(
        self,
        source_path: str,
        target_path: str,
        *,
        overwrite: str | None = None,
        dry_run: bool = False,
        retries: int = 0,
    ) -> dict[str, object]:
        """Move one remote object without an automatic retry after an ambiguous failure."""
        return self._run(
            "mv",
            "moveto",
            source_path,
            target_path,
            overwrite=overwrite,
            dry_run=dry_run,
            retries=retries,
        )

    def copy(
        self,
        source_path: str,
        target_path: str,
        *,
        overwrite: str | None = None,
        dry_run: bool = False,
        retries: int = 0,
    ) -> dict[str, object]:
        """Copy one remote object without altering the source path."""
        return self._run(
            "cp",
            "copyto",
            source_path,
            target_path,
            overwrite=overwrite,
            dry_run=dry_run,
            retries=retries,
        )

    def _run(
        self,
        operation: str,
        rclone_command: str,
        source_path: str,
        target_path: str,
        *,
        overwrite: str | None,
        dry_run: bool,
        retries: int,
    ) -> dict[str, object]:
        source_decision = validate_operation(
            OperationRequest(operation, remote_path=source_path, dry_run=dry_run, retries=retries)
        )
        target_decision = validate_operation(
            OperationRequest(operation, remote_path=target_path, dry_run=dry_run, retries=retries)
        )
        assert source_decision.remote_path is not None
        assert target_decision.remote_path is not None
        if source_decision.remote_path == target_decision.remote_path:
            raise MailCloudError(
                ErrorPayload(
                    ErrorKind.INVALID_ARGUMENTS, "source and target remote paths must differ"
                )
            )

        source = configured_target(self.config, source_decision.remote_path)
        target = configured_target(self.config, target_decision.remote_path)
        overwrite_mode = resolve_overwrite(overwrite, self.config)
        result: dict[str, object] = {
            "source_path": source_decision.remote_path,
            "target_path": target_decision.remote_path,
            "overwrite": overwrite_mode,
        }
        if source_decision.is_dry_run:
            return {**result, **source_decision.dry_run_result()}

        self.backend.require_success(
            [rclone_command, source, target, *overwrite_args(overwrite_mode)],
            timeout_seconds=self.timeout_seconds,
        )
        return result
