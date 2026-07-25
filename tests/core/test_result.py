"""Tests for stable schema-compatible result and error models."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from hermes_mailcloud.core.errors import EXIT_CODE_BY_KIND, ErrorKind, ErrorPayload
from hermes_mailcloud.core.result import ResultEnvelope

SCHEMA_PATH = Path(__file__).resolve().parents[2] / "schemas" / "result-envelope.schema.json"


def _validator() -> Draft202012Validator:
    return Draft202012Validator(json.loads(SCHEMA_PATH.read_text(encoding="utf-8")))


def test_every_frozen_error_kind_serializes_with_its_schema_exit_code() -> None:
    validator = _validator()

    for kind, expected_exit_code in EXIT_CODE_BY_KIND.items():
        envelope = ResultEnvelope.failure("ls", ErrorPayload(kind, "safe failure"))
        payload = envelope.to_payload()

        assert envelope.exit_code == expected_exit_code
        assert payload["error"]["exit_code"] == expected_exit_code
        validator.validate(payload)


def test_result_envelope_sanitizes_nested_error_details_before_serialization() -> None:
    envelope = ResultEnvelope.failure(
        "publish",
        ErrorPayload(
            ErrorKind.NETWORK_ERROR,
            "backend diagnostic",
            {
                "access_token": "token-sentinel",
                "nested": {"cookie": "cookie-sentinel"},
                "raw": "Authorization: Bearer auth-sentinel",
            },
        ),
    )
    rendered = envelope.to_json()

    for sentinel in ("token-sentinel", "cookie-sentinel", "auth-sentinel"):
        assert sentinel not in rendered
    _validator().validate(json.loads(rendered))


def test_batch_partial_is_the_only_result_bearing_failure_and_exits_11() -> None:
    envelope = ResultEnvelope.batch_partial(
        [
            {"index": 0, "operation": "mkdir", "ok": True, "result": {}},
            {
                "index": 1,
                "operation": "publish",
                "ok": False,
                "error": ErrorPayload(ErrorKind.NETWORK_ERROR, "provider unavailable").to_payload(),
            },
        ]
    )

    assert envelope.exit_code == 11
    payload = envelope.to_payload()
    assert "error" not in payload
    _validator().validate(payload)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"ok": True, "operation": "ls", "error": ErrorPayload(ErrorKind.NOT_FOUND, "missing")},
        {"ok": False, "operation": "ls", "result": {}},
        {"ok": False, "operation": "batch", "result": {"status": "partial_failure"}},
    ],
)
def test_result_envelope_rejects_invalid_result_error_combinations(
    kwargs: dict[str, object],
) -> None:
    with pytest.raises(ValueError):
        ResultEnvelope(**kwargs)  # type: ignore[arg-type]
