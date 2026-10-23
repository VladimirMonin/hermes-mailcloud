"""Contract tests for the versioned JSON schemas."""

from __future__ import annotations

import json
import re
from collections.abc import Iterator
from pathlib import Path
from typing import Any, cast

import pytest
from jsonschema import Draft202012Validator, ValidationError
from referencing import Registry, Resource

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_DIR = ROOT / "schemas"
DOCS_DIR = ROOT / "docs"
SCHEMA_PATHS = {
    "result-envelope": SCHEMA_DIR / "result-envelope.schema.json",
    "doctor-report": SCHEMA_DIR / "doctor-report.schema.json",
    "batch-plan": SCHEMA_DIR / "batch-plan.schema.json",
}


def _schemas() -> dict[str, dict[str, Any]]:
    return {
        name: json.loads(path.read_text(encoding="utf-8")) for name, path in SCHEMA_PATHS.items()
    }


def _registry(schemas: dict[str, dict[str, Any]]) -> Registry:
    return Registry().with_resources(
        (str(schema["$id"]), Resource.from_contents(schema)) for schema in schemas.values()
    )


def _validator(schema_name: str) -> Draft202012Validator:
    schemas = _schemas()
    return Draft202012Validator(schemas[schema_name], registry=_registry(schemas))


def _iter_documented_json_examples() -> Iterator[tuple[Path, str, str]]:
    """Yield classified JSON examples after requiring an explicit doc contract marker."""
    default_pattern = re.compile(r"<!-- hmc-json-example-default: ([a-z-]+) -->")
    example_pattern = re.compile(r"<!-- hmc-json-example: ([a-z-]+) -->")
    allowed_kinds = {"result-envelope", "doctor-report", "batch-plan", "non-contract"}

    for path in sorted(DOCS_DIR.rglob("*.md")):
        default_kind: str | None = None
        pending_kind: str | None = None
        lines = path.read_text(encoding="utf-8").splitlines()
        line_number = 0

        while line_number < len(lines):
            line = lines[line_number]
            if match := default_pattern.fullmatch(line):
                default_kind = match.group(1)
            elif match := example_pattern.fullmatch(line):
                pending_kind = match.group(1)
            elif line.lower() == "```json":
                start_line = line_number + 1
                line_number += 1
                payload_lines: list[str] = []
                while line_number < len(lines) and lines[line_number] != "```":
                    payload_lines.append(lines[line_number])
                    line_number += 1
                assert line_number < len(lines), f"{path}:{start_line} has no closing JSON fence"
                kind = pending_kind or default_kind
                assert kind in allowed_kinds, (
                    f"{path}:{start_line} must declare hmc-json-example or hmc-json-example-default"
                )
                yield path, kind, "\n".join(payload_lines)
                pending_kind = None
            line_number += 1


def _assert_batch_result_invariants(payload: dict[str, Any]) -> None:
    """Enforce batch arithmetic and index invariants outside JSON Schema's reach."""
    result = cast(dict[str, Any], payload["result"])
    items = cast(list[dict[str, Any]], result["items"])
    total = result["total"]
    succeeded = result["succeeded"]
    failed = result["failed"]

    assert total == len(items), "total must equal the number of result.items"
    assert succeeded + failed == total, "succeeded + failed must equal total"
    assert succeeded == sum(item["ok"] for item in items), "succeeded must match item outcomes"
    assert failed == sum(not item["ok"] for item in items), "failed must match item outcomes"
    assert [item["index"] for item in items] == list(range(total)), (
        "item indices must be unique and contiguous from zero"
    )
    if result["status"] == "completed":
        assert failed == 0 and succeeded == total, "completed batches cannot contain failures"
    else:
        assert failed > 0, "partial_failure batches must contain a failure"


@pytest.mark.parametrize("schema_name", sorted(SCHEMA_PATHS))
def test_schema_examples_validate(schema_name: str) -> None:
    schema = _schemas()[schema_name]
    validator = _validator(schema_name)

    Draft202012Validator.check_schema(schema)
    for example in cast(list[object], schema["examples"]):
        assert "https://cloud.mail.ru/public/" not in json.dumps(example)
        validator.validate(example)


def test_documented_json_examples_are_classified_valid_and_redacted() -> None:
    for path, schema_name, raw_example in _iter_documented_json_examples():
        assert "https://cloud.mail.ru/public/" not in raw_example, (
            f"{path} contains a raw public capability URL"
        )
        example = json.loads(raw_example)
        if schema_name != "non-contract":
            _validator(schema_name).validate(example)


def test_result_envelope_requires_exactly_one_result_or_error() -> None:
    validator = _validator("result-envelope")
    success_with_error = {
        "ok": True,
        "operation": "ls",
        "result": {},
        "error": {"kind": "unknown_error", "message": "unexpected", "exit_code": 1},
    }
    failure_with_result = {
        "ok": False,
        "operation": "ls",
        "result": {},
        "error": {"kind": "not_found", "message": "missing", "exit_code": 7},
    }

    with pytest.raises(ValidationError):
        validator.validate(success_with_error)
    with pytest.raises(ValidationError):
        validator.validate(failure_with_result)


def test_error_kind_requires_its_frozen_exit_code() -> None:
    validator = _validator("result-envelope")
    valid_not_found = {
        "ok": False,
        "operation": "stat",
        "error": {"kind": "not_found", "message": "missing", "exit_code": 7},
    }
    wrong_not_found_exit = {
        "ok": False,
        "operation": "stat",
        "error": {"kind": "not_found", "message": "missing", "exit_code": 9},
    }

    validator.validate(valid_not_found)
    with pytest.raises(ValidationError):
        validator.validate(wrong_not_found_exit)


def test_batch_partial_failure_uses_result_items_and_exit_code_11() -> None:
    _validator("result-envelope").validate(
        {
            "ok": False,
            "operation": "batch",
            "result": {
                "status": "partial_failure",
                "exit_code": 11,
                "total": 2,
                "succeeded": 1,
                "failed": 1,
                "items": [
                    {"index": 0, "operation": "mkdir", "ok": True, "result": {}},
                    {
                        "index": 1,
                        "operation": "publish",
                        "ok": False,
                        "error": {
                            "kind": "network_error",
                            "message": "provider unavailable",
                            "exit_code": 10,
                        },
                    },
                ],
            },
        }
    )


def test_batch_success_requires_result_items() -> None:
    with pytest.raises(ValidationError):
        _validator("result-envelope").validate(
            {
                "ok": True,
                "operation": "batch",
                "result": {"status": "completed", "total": 1, "succeeded": 1, "failed": 0},
            }
        )


def test_batch_result_invariants_accept_a_valid_completed_batch() -> None:
    payload = {
        "ok": True,
        "operation": "batch",
        "result": {
            "status": "completed",
            "total": 2,
            "succeeded": 2,
            "failed": 0,
            "items": [
                {"index": 0, "operation": "mkdir", "ok": True, "result": {}},
                {"index": 1, "operation": "publish", "ok": True, "result": {}},
            ],
        },
    }

    _validator("result-envelope").validate(payload)
    _assert_batch_result_invariants(payload)


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        (
            {
                "ok": False,
                "operation": "batch",
                "result": {
                    "status": "partial_failure",
                    "exit_code": 11,
                    "total": 3,
                    "succeeded": 1,
                    "failed": 1,
                    "items": [
                        {"index": 0, "operation": "mkdir", "ok": True, "result": {}},
                        {
                            "index": 1,
                            "operation": "publish",
                            "ok": False,
                            "error": {
                                "kind": "network_error",
                                "message": "provider unavailable",
                                "exit_code": 10,
                            },
                        },
                    ],
                },
            },
            "total must equal",
        ),
        (
            {
                "ok": False,
                "operation": "batch",
                "result": {
                    "status": "partial_failure",
                    "exit_code": 11,
                    "total": 2,
                    "succeeded": 2,
                    "failed": 1,
                    "items": [
                        {"index": 0, "operation": "mkdir", "ok": True, "result": {}},
                        {
                            "index": 1,
                            "operation": "publish",
                            "ok": False,
                            "error": {
                                "kind": "network_error",
                                "message": "provider unavailable",
                                "exit_code": 10,
                            },
                        },
                    ],
                },
            },
            "succeeded + failed",
        ),
        (
            {
                "ok": False,
                "operation": "batch",
                "result": {
                    "status": "partial_failure",
                    "exit_code": 11,
                    "total": 2,
                    "succeeded": 1,
                    "failed": 1,
                    "items": [
                        {"index": 0, "operation": "mkdir", "ok": True, "result": {}},
                        {
                            "index": 0,
                            "operation": "publish",
                            "ok": False,
                            "error": {
                                "kind": "network_error",
                                "message": "provider unavailable",
                                "exit_code": 10,
                            },
                        },
                    ],
                },
            },
            "item indices",
        ),
    ],
)
def test_batch_result_invariants_reject_invalid_counts_and_indices(
    payload: dict[str, Any], message: str
) -> None:
    _validator("result-envelope").validate(payload)

    with pytest.raises(AssertionError, match=re.escape(message)):
        _assert_batch_result_invariants(payload)


def test_batch_result_invariants_reject_non_contiguous_indices() -> None:
    payload = {
        "ok": True,
        "operation": "batch",
        "result": {
            "status": "completed",
            "total": 2,
            "succeeded": 2,
            "failed": 0,
            "items": [
                {"index": 0, "operation": "mkdir", "ok": True, "result": {}},
                {"index": 2, "operation": "publish", "ok": True, "result": {}},
            ],
        },
    }

    _validator("result-envelope").validate(payload)
    with pytest.raises(AssertionError, match="item indices"):
        _assert_batch_result_invariants(payload)


def test_batch_plan_rejects_post_v0_1_commands() -> None:
    plan = {
        "version": 1,
        "operations": [{"op": "sync_push", "local_path": "./in", "remote_path": "/Hermes"}],
    }

    with pytest.raises(ValidationError):
        _validator("batch-plan").validate(plan)


def test_read_only_doctor_report_has_no_mutating_checks() -> None:
    _validator("doctor-report").validate(
        {
            "ok": True,
            "operation": "doctor",
            "result": {
                "mode": "read_only",
                "checks": {
                    "config_loaded": True,
                    "rclone_installed": True,
                    "rclone_version": "1.74.3",
                    "remote_configured": True,
                    "remote_listed": True,
                    "cloud_access": True,
                    "about_available": True,
                },
                "capabilities": {
                    "file_ops": "unknown",
                    "public_link_create": "unknown",
                    "public_link_unlink": "unknown",
                },
            },
        }
    )


@pytest.mark.parametrize(
    "fragment,valid",
    [
        ({"version": 1}, True),
        ({"version": 1.0}, True),
        ({"version": True}, False),
        ({"version": "1"}, False),
        ({"version": float("nan")}, False),
        ({"version": 1, "defaults": None}, False),
    ],
)
def test_source_drift_batch_structure_matches_the_frozen_schema(fragment, valid) -> None:
    from hermes_mailcloud.batch import parse_batch_document
    from hermes_mailcloud.core.errors import ErrorKind, MailCloudError

    document = {**fragment, "operations": [{"op": "mkdir", "remote_path": "/TEST/schema"}]}
    assert _validator("batch-plan").is_valid(document) is valid
    if valid:
        parsed = parse_batch_document(document)
        assert len(parsed.operations) == 1 and parsed.operations[0].operation == "mkdir"
    else:
        with pytest.raises(MailCloudError) as caught:
            parse_batch_document(document)
        assert caught.value.error.kind is ErrorKind.INVALID_ARGUMENTS
