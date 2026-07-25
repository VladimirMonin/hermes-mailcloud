"""Safe public-link commands backed by rclone and the owner-private link journal."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ..config import ConfigError, ResolvedConfig
from ..core.errors import ErrorKind, ErrorPayload, MailCloudError
from ..core.policy import OperationRequest, validate_operation
from ..journal import LinkJournal
from ..rclone.parser import parse_public_link
from .backend import RcloneBackend, configured_target
from .transfer import overwrite_args, resolve_overwrite


@dataclass(frozen=True, slots=True)
class PublicCommands:
    """Publish a local file or link one public-root object without exposing its capability URL."""

    backend: RcloneBackend
    config: ResolvedConfig
    timeout_seconds: float

    def __post_init__(self) -> None:
        if isinstance(self.timeout_seconds, bool) or self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")

    def publish(
        self,
        local_path: str,
        remote_path: str,
        *,
        overwrite: str | None = None,
        dry_run: bool = False,
        yes: bool = False,
        retries: int = 0,
    ) -> dict[str, object]:
        """Validate, upload, link, and journal one public file with no automatic write retry."""
        decision = validate_operation(
            OperationRequest(
                "publish",
                remote_path=remote_path,
                local_path=local_path,
                dry_run=dry_run,
                yes=yes,
                retries=retries,
            )
        )
        assert decision.remote_path is not None
        target = configured_target(self.config, decision.remote_path)
        source, source_size = _require_local_source(local_path, role="publish source")
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

        journal = self._journal()
        journal.prepare()
        self.backend.require_success(
            ["copyto", str(source), target, *overwrite_args(overwrite_mode)],
            timeout_seconds=self.timeout_seconds,
        )
        linked = self.backend.require_success(
            ["link", target], timeout_seconds=self.timeout_seconds
        )
        public_link = parse_public_link(linked.stdout)
        journal.record("publish", decision.remote_path, public_link)
        return {
            **result,
            "published": True,
            "public_url_fingerprint": public_link.fingerprint,
            "backend": "rclone",
        }

    def link(
        self,
        remote_path: str,
        *,
        dry_run: bool = False,
        retries: int = 0,
    ) -> dict[str, object]:
        """Validate and journal a public link for a safe existing public-root object."""
        decision = validate_operation(
            OperationRequest("link", remote_path=remote_path, dry_run=dry_run, retries=retries)
        )
        assert decision.remote_path is not None
        target = configured_target(self.config, decision.remote_path)
        result: dict[str, object] = {"remote_path": decision.remote_path}
        if decision.is_dry_run:
            return {**result, **decision.dry_run_result()}

        journal = self._journal()
        journal.prepare()
        linked = self.backend.require_success(
            ["link", target], timeout_seconds=self.timeout_seconds
        )
        public_link = parse_public_link(linked.stdout)
        journal.record("link", decision.remote_path, public_link)
        return {
            **result,
            "public_url_fingerprint": public_link.fingerprint,
            "backend": "rclone",
        }

    def _journal(self) -> LinkJournal:
        if self.config.links_journal is None:
            raise ConfigError(
                "links_journal must be configured for public link operations", field="links_journal"
            )
        return LinkJournal(self.config.links_journal)


def _require_local_source(local_path: str, *, role: str) -> tuple[Path, int]:
    if not isinstance(local_path, str) or not local_path or "\x00" in local_path:
        raise MailCloudError(
            ErrorPayload(
                ErrorKind.INVALID_ARGUMENTS,
                f"local {role} path must be non-empty and contain no NUL",
            )
        )
    source = Path(local_path)
    try:
        if source.is_file():
            return source, source.stat().st_size
        if source.exists():
            raise MailCloudError(
                ErrorPayload(ErrorKind.INVALID_ARGUMENTS, f"local {role} must be a regular file")
            )
    except OSError as exc:
        raise MailCloudError(
            ErrorPayload(ErrorKind.INVALID_ARGUMENTS, f"local {role} could not be inspected")
        ) from exc
    raise MailCloudError(ErrorPayload(ErrorKind.NOT_FOUND, f"local {role} was not found"))
