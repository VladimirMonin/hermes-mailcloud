"""Bounded directory creation command through the typed rclone backend boundary."""

from __future__ import annotations

from dataclasses import dataclass

from ..config import ResolvedConfig
from ..core.policy import OperationRequest, validate_operation
from .backend import RcloneBackend, configured_target


@dataclass(frozen=True, slots=True)
class MkdirCommand:
    """Create one normalized directory, or produce a side-effect-free dry-run plan."""

    backend: RcloneBackend
    config: ResolvedConfig
    timeout_seconds: float

    def __post_init__(self) -> None:
        if isinstance(self.timeout_seconds, bool) or self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")

    def run(
        self, remote_path: str, *, dry_run: bool = False, yes: bool = False, retries: int = 0
    ) -> dict[str, object]:
        """Validate policy/config first and invoke exactly one non-retried mkdir on success."""
        decision = validate_operation(
            OperationRequest(
                "mkdir", remote_path=remote_path, dry_run=dry_run, yes=yes, retries=retries
            )
        )
        assert decision.remote_path is not None
        target = configured_target(self.config, decision.remote_path)
        if decision.is_dry_run:
            return {"remote_path": decision.remote_path, **decision.dry_run_result()}
        self.backend.require_success(["mkdir", target], timeout_seconds=self.timeout_seconds)
        return {"remote_path": decision.remote_path, "created": True}
