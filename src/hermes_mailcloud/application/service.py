"""Synchronous, terminal-independent application operations implemented in S1."""

from __future__ import annotations

import os
from collections.abc import Callable, Mapping
from types import MappingProxyType
from typing import Any

from .. import __version__
from ..commands.read import ReadCommands
from ..config import resolve_profile_name
from ..core.errors import ErrorPayload, MailCloudError, unknown_error
from ..core.result import ResultEnvelope
from ..output import sanitize_value
from ..probes.core import HttpOpener
from . import composition
from .contracts import BackendFactory, CallOptions, ConfigLoader
from .validation import require_bool, require_string, validate_options


class MailCloudApplication:
    """A lazy environment snapshot and explicit dependencies, not a live session.

    Configuration and runners belong to each call, never to the instance. Trusted
    DI is not a sandbox; home expansion still follows the process environment.
    """

    def __init__(
        self,
        *,
        environment: Mapping[str, str] | None = None,
        config_loader: ConfigLoader | None = None,
        backend_factory: BackendFactory | None = None,
        http_opener: HttpOpener | None = None,
    ) -> None:
        self._environment = MappingProxyType(
            dict(os.environ if environment is None else environment)
        )
        self._config_loader = (
            config_loader if config_loader is not None else composition.load_config
        )
        self._backend_factory = (
            backend_factory if backend_factory is not None else composition.create_backend
        )
        self._http_opener = http_opener

    def version(self, *, options: CallOptions | None = None) -> ResultEnvelope:
        """Return the package version without configuration or backend I/O."""
        return self._invoke(
            "version", options, lambda _options, _metadata: {"version": __version__}
        )

    def ls(
        self,
        remote_path: str,
        *,
        recursive: bool = False,
        files_only: bool = False,
        dirs_only: bool = False,
        options: CallOptions | None = None,
    ) -> ResultEnvelope:
        """List through the existing policy, safe-read retries and parser."""
        return self._read(
            "ls",
            remote_path,
            options,
            recursive=recursive,
            files_only=files_only,
            dirs_only=dirs_only,
        )

    def stat(self, remote_path: str, *, options: CallOptions | None = None) -> ResultEnvelope:
        """Inspect file/directory metadata through the existing read service."""
        return self._read("stat", remote_path, options)

    def _read(
        self,
        operation: str,
        remote_path: str,
        options: CallOptions | None,
        *,
        recursive: bool = False,
        files_only: bool = False,
        dirs_only: bool = False,
    ) -> ResultEnvelope:
        def execute(selected: CallOptions, metadata: dict[str, Any]) -> Mapping[str, Any]:
            require_string(remote_path, "remote_path")
            for name, value in (
                ("recursive", recursive),
                ("files_only", files_only),
                ("dirs_only", dirs_only),
            ):
                require_bool(value, name)
            config = self._config_loader(selected.config, environment=self._environment)
            metadata.update(profile=config.profile, remote=config.remote)
            backend = self._backend_factory(config, environment=self._environment)
            commands = ReadCommands(
                backend,
                config,
                timeout_seconds=(
                    selected.timeout_seconds
                    if selected.timeout_seconds is not None
                    else config.timeout_seconds
                ),
                retries=selected.retries if selected.retries is not None else config.retries,
            )
            if operation == "stat":
                return commands.stat(remote_path)
            return commands.ls(
                remote_path, recursive=recursive, files_only=files_only, dirs_only=dirs_only
            )

        return self._invoke(operation, options, execute)

    def _invoke(
        self,
        operation: str,
        options: CallOptions | None,
        action: Callable[[CallOptions, dict[str, Any]], Mapping[str, Any]],
    ) -> ResultEnvelope:
        metadata: dict[str, Any] = {}
        try:
            selected = validate_options(options)
            metadata["trace_id"] = selected.trace_id
            metadata["profile"] = resolve_profile_name(
                selected.config, environment=self._environment
            )
            if operation != "version":
                metadata["remote"] = selected.config.remote
            result = action(selected, metadata)
            envelope = ResultEnvelope.success(operation, result, **metadata)
        except MailCloudError as exc:
            envelope = ResultEnvelope.failure(operation, exc.error, **metadata)
        except Exception:
            envelope = ResultEnvelope.failure(operation, unknown_error(), **metadata)
        try:
            return _finalize(envelope)
        except Exception:
            # Never fall back to unsanitized data if projection itself fails.
            return ResultEnvelope.failure(operation, unknown_error())


def _finalize(envelope: ResultEnvelope) -> ResultEnvelope:
    """Copy safe data before direct access, preserving typed errors and envelope shape."""
    error = envelope.error
    return ResultEnvelope(
        ok=envelope.ok,
        operation=envelope.operation,
        result=sanitize_value(envelope.result) if envelope.result is not None else None,
        error=(
            ErrorPayload(error.kind, sanitize_value(error.message), sanitize_value(error.details))
            if error is not None
            else None
        ),
        trace_id=sanitize_value(envelope.trace_id),
        profile=sanitize_value(envelope.profile),
        remote=sanitize_value(envelope.remote),
        warnings=tuple(sanitize_value(envelope.warnings)),
    )
