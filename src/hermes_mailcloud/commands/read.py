"""Read-only file commands implemented through the typed rclone backend boundary."""

from __future__ import annotations

from dataclasses import dataclass

from ..config import ResolvedConfig
from ..core.errors import ErrorKind, ErrorPayload, MailCloudError
from ..core.policy import OperationRequest, validate_operation
from ..rclone.parser import parse_lsjson, parse_stat
from ..rclone.runner import RcloneResult, RcloneRunnerError
from .backend import RcloneBackend, configured_target


@dataclass(frozen=True, slots=True)
class ReadCommands:
    """Execute safe list/stat operations with frozen policy and retry semantics."""

    backend: RcloneBackend
    config: ResolvedConfig
    timeout_seconds: float
    retries: int

    def __post_init__(self) -> None:
        if isinstance(self.timeout_seconds, bool) or self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        if isinstance(self.retries, bool) or self.retries < 0:
            raise ValueError("retries must be non-negative")

    def ls(
        self,
        remote_path: str,
        *,
        recursive: bool = False,
        files_only: bool = False,
        dirs_only: bool = False,
    ) -> dict[str, object]:
        """List a normalized directory root without trusting raw rclone output."""
        if files_only and dirs_only:
            raise MailCloudError(
                ErrorPayload(
                    ErrorKind.INVALID_ARGUMENTS,
                    "ls cannot combine --files-only with --dirs-only",
                )
            )
        decision = validate_operation(
            OperationRequest("ls", remote_path=remote_path, retries=self.retries)
        )
        assert decision.remote_path is not None
        args = ["lsjson", configured_target(self.config, decision.remote_path)]
        if recursive:
            args.append("--recursive")
        if files_only:
            args.append("--files-only")
        if dirs_only:
            args.append("--dirs-only")
        result = self._require_read_success(args)
        items = parse_lsjson(result.stdout, root=decision.remote_path)
        return {"remote_path": decision.remote_path, "items": items}

    def stat(self, remote_path: str) -> dict[str, object]:
        """Return only validated metadata that the current rclone backend exposes."""
        decision = validate_operation(
            OperationRequest("stat", remote_path=remote_path, retries=self.retries)
        )
        assert decision.remote_path is not None
        result = self._require_read_success(
            [
                "lsjson",
                configured_target(self.config, decision.remote_path),
                "--stat",
                "--hash",
            ]
        )
        return parse_stat(result.stdout, remote_path=decision.remote_path)

    def _require_read_success(self, args: list[str]) -> RcloneResult:
        """Retry only typed transient read failures, preserving safe public errors."""
        for attempt in range(self.retries + 1):
            try:
                return self.backend.require_success(args, timeout_seconds=self.timeout_seconds)
            except RcloneRunnerError as exc:
                is_transient = exc.error.kind in {ErrorKind.NETWORK_ERROR, ErrorKind.TIMEOUT}
                if not is_transient or attempt == self.retries:
                    if attempt == 0:
                        raise
                    raise MailCloudError(
                        ErrorPayload(
                            ErrorKind.RETRY_EXHAUSTED,
                            "safe read-only retry attempts were exhausted",
                            {"attempts": attempt + 1},
                        )
                    ) from exc
        raise AssertionError("read retry loop must return or raise")
