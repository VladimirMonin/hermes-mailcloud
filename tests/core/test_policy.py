"""Fail-closed tests: rejected policy requests never reach a fake runner."""

from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from hermes_mailcloud.core.errors import ErrorKind
from hermes_mailcloud.core.policy import (
    OperationRequest,
    PolicyDecision,
    PolicyViolation,
    execute_with_policy,
)


@dataclass
class FakeRunner:
    calls: list[PolicyDecision] = field(default_factory=list)

    def __call__(self, decision: PolicyDecision) -> str:
        self.calls.append(decision)
        return "backend-called"


@pytest.mark.parametrize(
    ("operation_request", "kind"),
    [
        (
            OperationRequest("publish", remote_path="/Personal/report.pdf", yes=True),
            ErrorKind.UNSAFE_PUBLIC_PATH,
        ),
        (
            OperationRequest(
                "publish", remote_path="/Hermes/public/../../Personal/report.pdf", yes=True
            ),
            ErrorKind.UNSAFE_PUBLIC_PATH,
        ),
        (
            OperationRequest(
                "publish", local_path="./.env", remote_path="/Hermes/public/report.txt", yes=True
            ),
            ErrorKind.DANGEROUS_FILE_PATTERN,
        ),
        (
            OperationRequest("publish", remote_path="/Hermes/public/report.txt"),
            ErrorKind.CONFIRMATION_REQUIRED,
        ),
        (
            OperationRequest("rm", remote_path="/Hermes/private/old.txt"),
            ErrorKind.CONFIRMATION_REQUIRED,
        ),
        (OperationRequest("batch", batch_has_writes=True), ErrorKind.CONFIRMATION_REQUIRED),
        (
            OperationRequest("upload", remote_path="/Hermes/private/report.txt", retries=1),
            ErrorKind.INVALID_ARGUMENTS,
        ),
        (OperationRequest("ls", remote_path="/Hermes", retries=-1), ErrorKind.INVALID_ARGUMENTS),
        (OperationRequest("ls", remote_path="relative/path"), ErrorKind.INVALID_ARGUMENTS),
    ],
)
def test_unsafe_requests_fail_before_the_runner_is_called(
    operation_request: OperationRequest, kind: ErrorKind
) -> None:
    runner = FakeRunner()

    with pytest.raises(PolicyViolation) as caught:
        execute_with_policy(operation_request, runner)

    assert caught.value.error.kind is kind
    assert runner.calls == []


def test_dry_run_validates_publish_without_yes_or_backend_call() -> None:
    runner = FakeRunner()

    guarded = execute_with_policy(
        OperationRequest("publish", remote_path="/Hermes/public/report.txt", dry_run=True), runner
    )

    assert guarded.executed is False
    assert guarded.value is None
    assert guarded.decision.remote_path == "/Hermes/public/report.txt"
    assert guarded.decision.dry_run_result()["dry_run"] is True
    assert runner.calls == []


def test_safe_read_retry_and_confirmed_public_link_can_call_runner() -> None:
    runner = FakeRunner()

    read = execute_with_policy(OperationRequest("ls", remote_path="/Hermes", retries=2), runner)
    link = execute_with_policy(
        OperationRequest("link", remote_path="/Hermes/public/report.txt"), runner
    )

    assert read.executed is True and read.value == "backend-called"
    assert link.executed is True and link.value == "backend-called"
    assert [decision.request.operation for decision in runner.calls] == ["ls", "link"]
