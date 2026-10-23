"""Small in-process call and dependency contracts; no transport or second schema."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Literal, Protocol

from ..commands.backend import RcloneBackend
from ..config import ConfigOverrides, ResolvedConfig
from ..doctor import DiagnosticBackend

Overwrite = Literal["never", "always", "if-newer"]


@dataclass(frozen=True, slots=True)
class CallOptions:
    """Per-call intent; annotations are checked at the application boundary."""

    config: ConfigOverrides = field(default_factory=ConfigOverrides)
    trace_id: str | None = None
    dry_run: bool = False
    yes: bool = False
    timeout_seconds: int | None = None
    retries: int | None = None


class Backend(RcloneBackend, DiagnosticBackend, Protocol):
    """Existing runner ports, not a new backend implementation."""


class ConfigLoader(Protocol):
    def __call__(
        self, overrides: ConfigOverrides, *, environment: Mapping[str, str]
    ) -> ResolvedConfig: ...


class BackendFactory(Protocol):
    def __call__(self, config: ResolvedConfig, *, environment: Mapping[str, str]) -> Backend: ...
