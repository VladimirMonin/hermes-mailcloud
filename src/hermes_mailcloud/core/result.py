"""Schema-shaped result envelopes with stable exit-code behavior."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from ..output import render_json, sanitize_value
from .errors import ErrorPayload

BATCH_PARTIAL_EXIT_CODE = 11


@dataclass(frozen=True, slots=True)
class ResultEnvelope:
    """A valid v0.1 result/error envelope before its JSON serialization."""

    ok: bool
    operation: str
    result: Mapping[str, Any] | None = None
    error: ErrorPayload | None = None
    trace_id: str | None = None
    profile: str | None = None
    remote: str | None = None
    warnings: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if not self.operation.strip():
            raise ValueError("operation must not be empty")
        if not all(isinstance(warning, str) and warning for warning in self.warnings):
            raise ValueError("warnings must contain non-empty strings")
        if self.ok:
            if self.result is None or self.error is not None:
                raise ValueError("successful envelopes require result and forbid error")
            if self.operation == "batch":
                _validate_completed_batch(self.result)
            return
        if self.error is not None:
            if self.result is not None:
                raise ValueError("error envelopes cannot contain result")
            return
        if self.operation != "batch" or self.result is None:
            raise ValueError("failed envelopes require error except a batch partial failure")
        _validate_partial_batch(self.result)

    @classmethod
    def success(
        cls,
        operation: str,
        result: Mapping[str, Any],
        **metadata: Any,
    ) -> ResultEnvelope:
        """Construct a normal successful envelope."""
        return cls(ok=True, operation=operation, result=result, **metadata)

    @classmethod
    def failure(
        cls,
        operation: str,
        error: ErrorPayload,
        **metadata: Any,
    ) -> ResultEnvelope:
        """Construct a normal typed-error envelope."""
        return cls(ok=False, operation=operation, error=error, **metadata)

    @classmethod
    def batch_partial(
        cls,
        items: Sequence[Mapping[str, Any]],
        **metadata: Any,
    ) -> ResultEnvelope:
        """Construct the sole result-bearing failure shape with exit code 11."""
        copied_items = [dict(item) for item in items]
        failed = sum(item.get("ok") is False for item in copied_items)
        result = {
            "status": "partial_failure",
            "exit_code": BATCH_PARTIAL_EXIT_CODE,
            "total": len(copied_items),
            "succeeded": len(copied_items) - failed,
            "failed": failed,
            "items": copied_items,
        }
        return cls(ok=False, operation="batch", result=result, **metadata)

    @property
    def exit_code(self) -> int:
        """Return 0, the typed-error code, or the frozen batch-partial code."""
        if self.ok:
            return 0
        if self.error is not None:
            return self.error.exit_code
        return BATCH_PARTIAL_EXIT_CODE

    def to_payload(self) -> dict[str, Any]:
        """Return a sanitized mapping suitable for stdout, logs, or journal metadata."""
        payload: dict[str, Any] = {"ok": self.ok, "operation": self.operation}
        for key, value in (
            ("trace_id", self.trace_id),
            ("profile", self.profile),
            ("remote", self.remote),
        ):
            if value is not None:
                payload[key] = value
        if self.result is not None:
            payload["result"] = dict(self.result)
        if self.error is not None:
            payload["error"] = self.error.to_payload()
        if self.warnings:
            payload["warnings"] = list(self.warnings)
        return sanitize_value(payload)

    def to_json(self, *, pretty: bool = False) -> str:
        """Render one sanitized JSON object for JSON-first command output."""
        return render_json(self.to_payload(), pretty=pretty)


def _validate_partial_batch(result: Mapping[str, Any]) -> None:
    expected_keys = {"status", "exit_code", "total", "succeeded", "failed", "items"}
    if set(result) != expected_keys or result.get("status") != "partial_failure":
        raise ValueError("batch partial result has an invalid shape")
    if result.get("exit_code") != BATCH_PARTIAL_EXIT_CODE:
        raise ValueError("batch partial result must use exit code 11")
    _validate_batch_counts(result, requires_failure=True)


def _validate_completed_batch(result: Mapping[str, Any]) -> None:
    expected_keys = {"status", "total", "succeeded", "failed", "items"}
    if set(result) != expected_keys or result.get("status") != "completed":
        raise ValueError("completed batch result has an invalid shape")
    _validate_batch_counts(result, requires_failure=False)


def _validate_batch_counts(result: Mapping[str, Any], *, requires_failure: bool) -> None:
    items = result.get("items")
    total = result.get("total")
    succeeded = result.get("succeeded")
    failed = result.get("failed")
    if (
        not isinstance(items, list)
        or not items
        or any(not isinstance(item, Mapping) for item in items)
    ):
        raise ValueError("batch result must contain at least one object item")
    if any(
        isinstance(value, bool) or not isinstance(value, int)
        for value in (total, succeeded, failed)
    ):
        raise ValueError("batch result counts must be integers")

    assert isinstance(total, int)
    assert isinstance(succeeded, int)
    assert isinstance(failed, int)
    _validate_batch_items(items)
    if (
        total != len(items)
        or succeeded < 0
        or failed < 0
        or succeeded + failed != total
        or succeeded != sum(item["ok"] is True for item in items)
        or failed != sum(item["ok"] is False for item in items)
        or [item["index"] for item in items] != list(range(total))
    ):
        raise ValueError("batch result counts and indices must match its items")
    if requires_failure and failed < 1:
        raise ValueError("partial batch result must include a failed item")
    if not requires_failure and failed != 0:
        raise ValueError("completed batch result cannot include failed items")


def _validate_batch_items(items: list[Mapping[str, Any]]) -> None:
    allowed_keys = {"index", "operation", "ok", "result", "error"}
    for item in items:
        if set(item) - allowed_keys or not {"index", "operation", "ok"}.issubset(item):
            raise ValueError("batch item has an invalid shape")
        if isinstance(item["index"], bool) or not isinstance(item["index"], int):
            raise ValueError("batch item index must be an integer")
        if not isinstance(item["operation"], str) or not item["operation"]:
            raise ValueError("batch item operation must be a non-empty string")
        if not isinstance(item["ok"], bool):
            raise ValueError("batch item ok must be a boolean")
        if item["ok"]:
            if "error" in item or not isinstance(item.get("result"), Mapping):
                raise ValueError("successful batch item must contain result only")
        elif "result" in item or not isinstance(item.get("error"), Mapping):
            raise ValueError("failed batch item must contain error only")
