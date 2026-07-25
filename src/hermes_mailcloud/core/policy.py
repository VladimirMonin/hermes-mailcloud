"""Fail-closed v0.1 policy checks that run before any backend invocation."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import PurePath

from .errors import ErrorKind, ErrorPayload, MailCloudError
from .paths import RemotePathError, normalize_remote_path, require_descendant

PUBLIC_ROOT = "/Hermes/public"
READ_ONLY_OPERATIONS = frozenset({"doctor", "ls", "stat"})
WRITE_OPERATIONS = frozenset({"mkdir", "upload", "download", "mv", "cp", "rm", "publish", "link"})
SUPPORTED_OPERATIONS = READ_ONLY_OPERATIONS | WRITE_OPERATIONS | {"batch"}
PUBLIC_OPERATIONS = frozenset({"publish", "link"})
CONFIRMATION_OPERATIONS = frozenset({"rm", "publish"})
DANGEROUS_EXACT_FILENAMES = frozenset({".env", "id_rsa", "id_ed25519"})
DANGEROUS_EXTENSIONS = frozenset({".key", ".pem", ".p12", ".pfx", ".kdbx", ".sqlite", ".db"})
DANGEROUS_PREFIXES = ("cookies", "tokens", "secrets", "credentials")


@dataclass(frozen=True, slots=True)
class OperationRequest:
    """Static inputs that must pass policy before a command may call rclone."""

    operation: str
    remote_path: str | None = None
    local_path: str | None = None
    yes: bool = False
    dry_run: bool = False
    retries: int = 0
    batch_has_writes: bool = False


@dataclass(frozen=True, slots=True)
class PolicyDecision:
    """Validated operation inputs, safe for a downstream backend adapter to consume."""

    request: OperationRequest
    remote_path: str | None
    planned_steps: tuple[str, ...]

    @property
    def is_dry_run(self) -> bool:
        return self.request.dry_run

    def dry_run_result(self) -> dict[str, object]:
        """Return a side-effect-free plan shape for command implementations."""
        return {
            "dry_run": True,
            "plan": [{"step": step, "status": "planned"} for step in self.planned_steps],
        }


@dataclass(frozen=True, slots=True)
class GuardedExecution[ResultT]:
    """Capture whether policy allowed a backend runner to execute."""

    decision: PolicyDecision
    executed: bool
    value: ResultT | None = None


class PolicyViolation(MailCloudError):
    """Expected policy failure with a stable error kind and exit code."""

    def __init__(
        self, kind: ErrorKind, message: str, *, details: dict[str, object] | None = None
    ) -> None:
        super().__init__(ErrorPayload(kind=kind, message=message, details=details or {}))


def dangerous_filename(path: str) -> str | None:
    """Return the matched frozen safety rule for a filename, if any."""
    name = PurePath(path).name.casefold()
    if name in DANGEROUS_EXACT_FILENAMES or name.startswith(".env."):
        return ".env" if name.startswith(".env") else name
    if any(name.endswith(extension) for extension in DANGEROUS_EXTENSIONS):
        return next(extension for extension in DANGEROUS_EXTENSIONS if name.endswith(extension))
    if name.startswith(DANGEROUS_PREFIXES):
        return next(prefix for prefix in DANGEROUS_PREFIXES if name.startswith(prefix))
    return None


def validate_operation(request: OperationRequest) -> PolicyDecision:
    """Validate the frozen policy surface without calling a cloud backend."""
    if request.operation not in SUPPORTED_OPERATIONS:
        raise PolicyViolation(
            ErrorKind.INVALID_ARGUMENTS,
            "operation is not part of the frozen v0.1 command set",
            details={"operation": request.operation},
        )
    if (
        isinstance(request.retries, bool)
        or not isinstance(request.retries, int)
        or request.retries < 0
    ):
        raise PolicyViolation(
            ErrorKind.INVALID_ARGUMENTS,
            "retries must be a non-negative integer",
        )
    if request.retries and request.operation not in READ_ONLY_OPERATIONS:
        raise PolicyViolation(
            ErrorKind.INVALID_ARGUMENTS,
            "automatic retries are allowed only for safe read-only operations in v0.1",
            details={"operation": request.operation},
        )

    remote_path = _normalize_request_path(request)
    if request.operation in PUBLIC_OPERATIONS:
        if remote_path is None:
            raise PolicyViolation(
                ErrorKind.INVALID_ARGUMENTS,
                "publish and link require a remote path",
            )
        try:
            remote_path = require_descendant(remote_path, PUBLIC_ROOT)
        except RemotePathError as exc:
            raise PolicyViolation(
                ErrorKind.UNSAFE_PUBLIC_PATH,
                "publishing is allowed only inside /Hermes/public",
                details={"remote_path": remote_path, "public_root": PUBLIC_ROOT},
            ) from exc
        for candidate in (request.local_path, remote_path):
            if candidate and (matched_rule := dangerous_filename(candidate)):
                raise PolicyViolation(
                    ErrorKind.DANGEROUS_FILE_PATTERN,
                    "this file name is blocked by publish safety policy",
                    details={"matched_rule": matched_rule},
                )

    needs_confirmation = request.operation in CONFIRMATION_OPERATIONS or (
        request.operation == "batch" and request.batch_has_writes
    )
    if needs_confirmation and not request.dry_run and not request.yes:
        raise PolicyViolation(
            ErrorKind.CONFIRMATION_REQUIRED,
            f"{request.operation} requires --yes for real execution",
        )

    return PolicyDecision(
        request=request,
        remote_path=remote_path,
        planned_steps=_planned_steps(request.operation),
    )


def execute_with_policy[ResultT](
    request: OperationRequest, runner: Callable[[PolicyDecision], ResultT]
) -> GuardedExecution[ResultT]:
    """Run policy first; dry-run and every rejection keep the runner untouched."""
    decision = validate_operation(request)
    if decision.is_dry_run:
        return GuardedExecution(decision=decision, executed=False)
    return GuardedExecution(decision=decision, executed=True, value=runner(decision))


def _normalize_request_path(request: OperationRequest) -> str | None:
    if request.remote_path is None:
        return None
    try:
        return normalize_remote_path(request.remote_path)
    except RemotePathError as exc:
        raise PolicyViolation(
            ErrorKind.INVALID_ARGUMENTS,
            "remote path must be an absolute non-empty POSIX path",
        ) from exc


def _planned_steps(operation: str) -> tuple[str, ...]:
    if operation == "publish":
        return (
            "validate_local_file",
            "validate_public_root",
            "upload",
            "create_public_link",
            "record_link_journal",
        )
    if operation == "link":
        return ("validate_public_root", "create_public_link", "record_link_journal")
    if operation == "batch":
        return ("validate_batch", "execute_operations")
    if operation in WRITE_OPERATIONS:
        return ("validate_arguments", "execute")
    return ("validate_arguments", "read")
