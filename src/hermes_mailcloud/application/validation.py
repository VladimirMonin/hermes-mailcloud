"""Runtime input types only; paths and domain policy retain their existing owners."""

from __future__ import annotations

from pathlib import Path

from ..config import ConfigOverrides
from ..core.errors import ErrorKind, ErrorPayload, MailCloudError
from .contracts import CallOptions


def invalid_argument(field: str) -> MailCloudError:
    return MailCloudError(
        ErrorPayload(ErrorKind.INVALID_ARGUMENTS, "invalid application argument", {"field": field})
    )


def require_string(value: object, field: str) -> None:
    if not isinstance(value, str):
        raise invalid_argument(field)


def require_bool(value: object, field: str) -> None:
    if not isinstance(value, bool):
        raise invalid_argument(field)


def require_path(value: object, field: str) -> None:
    if not isinstance(value, Path):
        raise invalid_argument(field)


def require_overwrite(value: object) -> None:
    """Validate the callable contract without coercing non-string input."""
    if value is not None and (
        not isinstance(value, str) or value not in {"never", "always", "if-newer"}
    ):
        raise invalid_argument("overwrite")


def validate_options(options: CallOptions | None) -> CallOptions:
    """Validate before inspecting nested inputs or permitting configuration access."""
    if options is None:
        return CallOptions()
    if not isinstance(options, CallOptions):
        raise invalid_argument("options")
    if not isinstance(options.config, ConfigOverrides):
        raise invalid_argument("config")
    for name in ("profile", "remote"):
        value = getattr(options.config, name)
        if value is not None:
            require_string(value, name)
    if options.config.config_path is not None and not isinstance(options.config.config_path, Path):
        raise invalid_argument("config_path")
    if options.trace_id is not None:
        require_string(options.trace_id, "trace_id")
    require_bool(options.dry_run, "dry_run")
    require_bool(options.yes, "yes")
    for name, minimum in (("timeout_seconds", 1), ("retries", 0)):
        value = getattr(options, name)
        if value is not None and (
            isinstance(value, bool) or not isinstance(value, int) or value < minimum
        ):
            raise invalid_argument(name)
    return options
