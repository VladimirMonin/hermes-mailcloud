"""Schema-conformant planning and execution for the v0.1 JSON batch command."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from ..commands.backend import RcloneBackend, configured_target
from ..commands.mkdir import MkdirCommand
from ..commands.move_copy import MoveCopyCommands
from ..commands.public import PublicCommands
from ..commands.read import ReadCommands
from ..commands.remove import RemoveCommand
from ..commands.transfer import TransferCommands
from ..config import ConfigError, ResolvedConfig
from ..core.errors import ErrorKind, ErrorPayload, MailCloudError
from ..core.policy import WRITE_OPERATIONS, OperationRequest, validate_operation
from ..journal import LinkJournal

_PLAN_FIELDS = frozenset({"version", "description", "defaults", "operations"})
_DEFAULT_FIELDS = frozenset({"overwrite", "continue_on_error"})
_OVERWRITE_MODES = frozenset({"never", "always", "if-newer"})
_OPERATION_FIELDS: dict[str, tuple[frozenset[str], frozenset[str]]] = {
    "ls": (frozenset({"op", "remote_path"}), frozenset({"recursive"})),
    "stat": (frozenset({"op", "remote_path"}), frozenset()),
    "mkdir": (frozenset({"op", "remote_path"}), frozenset({"parents", "exist_ok"})),
    "upload": (frozenset({"op", "local_path", "remote_path"}), frozenset({"overwrite"})),
    "download": (frozenset({"op", "remote_path", "local_path"}), frozenset({"overwrite"})),
    "mv": (frozenset({"op", "src_remote_path", "dst_remote_path"}), frozenset()),
    "cp": (frozenset({"op", "src_remote_path", "dst_remote_path"}), frozenset()),
    "rm": (frozenset({"op", "remote_path"}), frozenset({"recursive"})),
    "publish": (frozenset({"op", "local_path", "remote_path"}), frozenset({"overwrite"})),
    "link": (frozenset({"op", "remote_path"}), frozenset()),
}


@dataclass(frozen=True, slots=True)
class BatchDefaults:
    """Static plan defaults that make every execution deterministic."""

    overwrite: str
    continue_on_error: bool


@dataclass(frozen=True, slots=True)
class BatchOperation:
    """One already-schema-validated operation in source-plan order."""

    index: int
    operation: str
    fields: Mapping[str, object]


@dataclass(frozen=True, slots=True)
class BatchPlan:
    """Versioned JSON plan after strict discriminated-operation validation."""

    defaults: BatchDefaults
    operations: tuple[BatchOperation, ...]

    @property
    def has_writes(self) -> bool:
        return any(operation.operation in WRITE_OPERATIONS for operation in self.operations)


@dataclass(frozen=True, slots=True)
class BatchExecution:
    """Ordered execution outcome, ready for a schema-shaped result envelope."""

    items: tuple[Mapping[str, object], ...]

    @property
    def is_partial(self) -> bool:
        return any(item["ok"] is False for item in self.items)

    @property
    def result(self) -> dict[str, object]:
        """Return exactly one frozen completed or partial batch result shape."""
        copied_items = [dict(item) for item in self.items]
        failed = sum(item["ok"] is False for item in copied_items)
        if failed:
            return {
                "status": "partial_failure",
                "exit_code": 11,
                "total": len(copied_items),
                "succeeded": len(copied_items) - failed,
                "failed": failed,
                "items": copied_items,
            }
        return {
            "status": "completed",
            "total": len(copied_items),
            "succeeded": len(copied_items),
            "failed": 0,
            "items": copied_items,
        }


def parse_batch_file(plan_path: Path) -> BatchPlan:
    """Load and validate one UTF-8 JSON plan without resolving configuration or rclone."""
    try:
        if not plan_path.is_file():
            raise MailCloudError(ErrorPayload(ErrorKind.NOT_FOUND, "batch plan file was not found"))
        raw_document = plan_path.read_text(encoding="utf-8")
    except MailCloudError:
        raise
    except OSError as exc:
        raise MailCloudError(
            ErrorPayload(ErrorKind.INVALID_ARGUMENTS, "batch plan file could not be read")
        ) from exc
    try:
        document = json.loads(raw_document)
    except json.JSONDecodeError as exc:
        raise MailCloudError(
            ErrorPayload(ErrorKind.INVALID_ARGUMENTS, "batch plan must be valid JSON")
        ) from exc
    return parse_batch_document(document)


def parse_batch_document(document: object) -> BatchPlan:
    """Validate the batch-plan schema's v0.1 discriminated-union surface in-process."""
    payload = _mapping(document, "batch plan must be a JSON object")
    _reject_unknown_fields(payload, _PLAN_FIELDS, "batch plan contains unsupported fields")
    if set(payload) - {"version", "operations", "description", "defaults"} or not {
        "version",
        "operations",
    }.issubset(payload):
        raise _invalid("batch plan requires version and operations")
    if not _is_integer(payload["version"]) or payload["version"] != 1:
        raise _invalid("batch plan version must be the supported integer 1")
    if "description" in payload and not _is_nonempty_string(payload["description"]):
        raise _invalid("batch plan description must be a non-empty string")

    defaults = _parse_defaults(payload.get("defaults"))
    raw_operations = payload["operations"]
    if not isinstance(raw_operations, list) or not raw_operations:
        raise _invalid("batch plan operations must be a non-empty array")
    operations = tuple(
        _parse_operation(index, raw_operation) for index, raw_operation in enumerate(raw_operations)
    )
    return BatchPlan(defaults=defaults, operations=operations)


@dataclass(frozen=True, slots=True)
class BatchCommands:
    """Preflight and execute an already-validated plan through existing command adapters."""

    backend: RcloneBackend
    config: ResolvedConfig
    timeout_seconds: float
    read_retries: int

    def __post_init__(self) -> None:
        if isinstance(self.timeout_seconds, bool) or self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        if isinstance(self.read_retries, bool) or self.read_retries < 0:
            raise ValueError("read_retries must be non-negative")

    def run(
        self,
        plan: BatchPlan,
        *,
        dry_run: bool = False,
        yes: bool = False,
        explicit_retries: int | None = None,
    ) -> BatchExecution:
        """Validate every operation before calls, then run in order with bounded continuation."""
        effective_read_retries = self._validate_outer_policy(
            plan, dry_run=dry_run, yes=yes, explicit_retries=explicit_retries
        )
        if not dry_run and any(
            operation.operation in {"publish", "link"} for operation in plan.operations
        ):
            if self.config.links_journal is None:
                raise ConfigError(
                    "links_journal must be configured for public link operations",
                    field="links_journal",
                )
            LinkJournal(self.config.links_journal).prepare()
        planned_items = tuple(
            {
                "index": operation.index,
                "operation": operation.operation,
                "ok": True,
                "result": self._planned_item(
                    operation,
                    plan.defaults,
                    read_retries=effective_read_retries,
                ),
            }
            for operation in plan.operations
        )
        if dry_run:
            return BatchExecution(planned_items)

        items: list[Mapping[str, object]] = []
        for operation in plan.operations:
            try:
                result = self._execute_operation(
                    operation,
                    plan.defaults,
                    yes=yes,
                    read_retries=effective_read_retries,
                )
            except MailCloudError as exc:
                items.append(
                    {
                        "index": operation.index,
                        "operation": operation.operation,
                        "ok": False,
                        "error": ErrorPayload(exc.error.kind, exc.error.message).to_payload(),
                    }
                )
                if not plan.defaults.continue_on_error:
                    break
            else:
                items.append(
                    {
                        "index": operation.index,
                        "operation": operation.operation,
                        "ok": True,
                        "result": result,
                    }
                )
        return BatchExecution(tuple(items))

    def _validate_outer_policy(
        self,
        plan: BatchPlan,
        *,
        dry_run: bool,
        yes: bool,
        explicit_retries: int | None,
    ) -> int:
        if explicit_retries is not None and (
            isinstance(explicit_retries, bool)
            or not isinstance(explicit_retries, int)
            or explicit_retries < 0
        ):
            raise _invalid("retries must be a non-negative integer")
        if plan.has_writes and explicit_retries:
            validate_operation(
                OperationRequest(
                    "batch",
                    dry_run=dry_run,
                    yes=yes,
                    retries=explicit_retries,
                    batch_has_writes=True,
                )
            )
        validate_operation(
            OperationRequest("batch", dry_run=dry_run, yes=yes, batch_has_writes=plan.has_writes)
        )
        return self.read_retries if explicit_retries is None else explicit_retries

    def _planned_item(
        self,
        operation: BatchOperation,
        defaults: BatchDefaults,
        *,
        read_retries: int,
    ) -> Mapping[str, object]:
        self._validate_mkdir_options(operation)
        if operation.operation in {"ls", "stat"}:
            result = self._plan_read(operation, read_retries=read_retries)
        else:
            result = self._run_write_adapter(
                operation,
                defaults,
                dry_run=True,
                yes=False,
            )
        return result

    def _execute_operation(
        self,
        operation: BatchOperation,
        defaults: BatchDefaults,
        *,
        yes: bool,
        read_retries: int,
    ) -> dict[str, object]:
        if operation.operation == "ls":
            return ReadCommands(
                self.backend,
                self.config,
                timeout_seconds=self.timeout_seconds,
                retries=read_retries,
            ).ls(
                _string_field(operation, "remote_path"),
                recursive=_bool_field(operation, "recursive", default=False),
            )
        if operation.operation == "stat":
            return ReadCommands(
                self.backend,
                self.config,
                timeout_seconds=self.timeout_seconds,
                retries=read_retries,
            ).stat(_string_field(operation, "remote_path"))
        if operation.operation in {"publish", "link"} and self.config.links_journal is None:
            raise ConfigError(
                "links_journal must be configured for public link operations", field="links_journal"
            )
        return self._run_write_adapter(operation, defaults, dry_run=False, yes=yes)

    def _plan_read(self, operation: BatchOperation, *, read_retries: int) -> dict[str, object]:
        decision = validate_operation(
            OperationRequest(
                operation.operation,
                remote_path=_string_field(operation, "remote_path"),
                retries=read_retries,
            )
        )
        assert decision.remote_path is not None
        configured_target(self.config, decision.remote_path)
        return {"remote_path": decision.remote_path, **decision.dry_run_result()}

    def _run_write_adapter(
        self,
        operation: BatchOperation,
        defaults: BatchDefaults,
        *,
        dry_run: bool,
        yes: bool,
    ) -> dict[str, object]:
        overwrite = _string_field(operation, "overwrite", default=defaults.overwrite)
        if operation.operation == "mkdir":
            return MkdirCommand(self.backend, self.config, self.timeout_seconds).run(
                _string_field(operation, "remote_path"),
                dry_run=dry_run,
                yes=yes,
            )
        if operation.operation == "upload":
            return TransferCommands(self.backend, self.config, self.timeout_seconds).upload(
                _string_field(operation, "local_path"),
                _string_field(operation, "remote_path"),
                overwrite=overwrite,
                dry_run=dry_run,
            )
        if operation.operation == "download":
            return TransferCommands(self.backend, self.config, self.timeout_seconds).download(
                _string_field(operation, "remote_path"),
                _string_field(operation, "local_path"),
                overwrite=overwrite,
                dry_run=dry_run,
            )
        if operation.operation == "mv":
            return MoveCopyCommands(self.backend, self.config, self.timeout_seconds).move(
                _string_field(operation, "src_remote_path"),
                _string_field(operation, "dst_remote_path"),
                overwrite=overwrite,
                dry_run=dry_run,
            )
        if operation.operation == "cp":
            return MoveCopyCommands(self.backend, self.config, self.timeout_seconds).copy(
                _string_field(operation, "src_remote_path"),
                _string_field(operation, "dst_remote_path"),
                overwrite=overwrite,
                dry_run=dry_run,
            )
        if operation.operation == "rm":
            return RemoveCommand(self.backend, self.config, self.timeout_seconds).run(
                _string_field(operation, "remote_path"),
                recursive=_bool_field(operation, "recursive", default=False),
                dry_run=dry_run,
                yes=yes,
            )
        if operation.operation == "publish":
            return PublicCommands(self.backend, self.config, self.timeout_seconds).publish(
                _string_field(operation, "local_path"),
                _string_field(operation, "remote_path"),
                overwrite=overwrite,
                dry_run=dry_run,
                yes=yes,
            )
        if operation.operation == "link":
            return PublicCommands(self.backend, self.config, self.timeout_seconds).link(
                _string_field(operation, "remote_path"), dry_run=dry_run
            )
        raise AssertionError(f"unsupported validated batch operation: {operation.operation}")

    @staticmethod
    def _validate_mkdir_options(operation: BatchOperation) -> None:
        if operation.operation != "mkdir":
            return
        if operation.fields.get("parents") is False or operation.fields.get("exist_ok") is False:
            raise _invalid(
                "batch mkdir requires rclone's safe parent and existing-directory behavior"
            )


def _parse_defaults(raw_defaults: object | None) -> BatchDefaults:
    if raw_defaults is None:
        return BatchDefaults(overwrite="never", continue_on_error=False)
    defaults = _mapping(raw_defaults, "batch defaults must be an object")
    _reject_unknown_fields(defaults, _DEFAULT_FIELDS, "batch defaults contain unsupported fields")
    overwrite = defaults.get("overwrite", "never")
    if not isinstance(overwrite, str) or overwrite not in _OVERWRITE_MODES:
        raise _invalid("batch default overwrite must be never, always, or if-newer")
    continue_on_error = defaults.get("continue_on_error", False)
    if not isinstance(continue_on_error, bool):
        raise _invalid("batch default continue_on_error must be a boolean")
    return BatchDefaults(overwrite=overwrite, continue_on_error=continue_on_error)


def _parse_operation(index: int, raw_operation: object) -> BatchOperation:
    fields = _mapping(raw_operation, "each batch operation must be an object")
    operation = fields.get("op")
    if not isinstance(operation, str) or operation not in _OPERATION_FIELDS:
        raise _invalid("batch operation op is unsupported")
    required, optional = _OPERATION_FIELDS[operation]
    _reject_unknown_fields(
        fields, required | optional, "batch operation contains unsupported fields"
    )
    if not required.issubset(fields):
        raise _invalid("batch operation is missing required fields")
    _validate_operation_field_types(operation, fields)
    return BatchOperation(index=index, operation=operation, fields=dict(fields))


def _validate_operation_field_types(operation: str, fields: Mapping[str, object]) -> None:
    remote_fields = {
        "ls": ("remote_path",),
        "stat": ("remote_path",),
        "mkdir": ("remote_path",),
        "upload": ("remote_path",),
        "download": ("remote_path",),
        "mv": ("src_remote_path", "dst_remote_path"),
        "cp": ("src_remote_path", "dst_remote_path"),
        "rm": ("remote_path",),
        "publish": ("remote_path",),
        "link": ("remote_path",),
    }[operation]
    for field in remote_fields:
        _require_remote_path(fields[field])
    if operation in {"upload", "download", "publish"}:
        _require_local_path(fields["local_path"])
    if "overwrite" in fields and (
        not isinstance(fields["overwrite"], str) or fields["overwrite"] not in _OVERWRITE_MODES
    ):
        raise _invalid("batch operation overwrite must be never, always, or if-newer")
    for field in ("recursive", "parents", "exist_ok"):
        if field in fields and not isinstance(fields[field], bool):
            raise _invalid(f"batch operation {field} must be a boolean")


def _require_remote_path(value: object) -> None:
    if not isinstance(value, str) or len(value) < 2 or not value.startswith("/") or "\x00" in value:
        raise _invalid("batch remote paths must be non-empty absolute POSIX paths")


def _require_local_path(value: object) -> None:
    if not isinstance(value, str) or not value or "\x00" in value:
        raise _invalid("batch local paths must be non-empty strings")


def _mapping(value: object, message: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or any(not isinstance(key, str) for key in value):
        raise _invalid(message)
    return value


def _reject_unknown_fields(
    fields: Mapping[str, object], allowed: frozenset[str], message: str
) -> None:
    if set(fields) - allowed:
        raise _invalid(message)


def _string_field(operation: BatchOperation, field: str, *, default: str | None = None) -> str:
    value = operation.fields.get(field, default)
    if not isinstance(value, str):
        raise AssertionError(f"validated batch field {field} is not a string")
    return value


def _bool_field(operation: BatchOperation, field: str, *, default: bool) -> bool:
    value = operation.fields.get(field, default)
    if not isinstance(value, bool):
        raise AssertionError(f"validated batch field {field} is not a boolean")
    return value


def _is_integer(value: object) -> bool:
    return not isinstance(value, bool) and isinstance(value, int)


def _is_nonempty_string(value: object) -> bool:
    return isinstance(value, str) and bool(value)


def _invalid(message: str) -> MailCloudError:
    return MailCloudError(ErrorPayload(ErrorKind.INVALID_ARGUMENTS, message))


__all__ = [
    "BatchCommands",
    "BatchDefaults",
    "BatchExecution",
    "BatchOperation",
    "BatchPlan",
    "parse_batch_document",
    "parse_batch_file",
]
