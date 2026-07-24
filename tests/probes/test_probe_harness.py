"""Offline contract tests for the safe probe harness."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from io import StringIO
from pathlib import Path
from typing import Any

import pytest

from hermes_mailcloud.probes.core import (
    MAX_HTTP_BODY_BYTES,
    CommandResult,
    main,
    probe_public_url,
    redact_text,
    run_file_ops_probe,
    run_publish_probe,
    run_unlink_probe,
    sanitize_value,
    validate_test_root,
)

VALID_ROOT = "/TEST/hermes-mailcloud-20260724T235959Z-abc12345"
PUBLIC_URL = "https://cloud.mail.ru/public/example-token/path"


@dataclass
class FakeRunner:
    """In-memory runner proving unit tests never invoke a real subprocess."""

    failed_command: str | None = None
    failure_stderr: str = "Password=not-for-output"
    unlink_returncode: int = 0
    calls: list[tuple[str, ...]] = field(default_factory=list)

    def run(self, args: list[str], *, timeout: float | None = None) -> CommandResult:
        del timeout
        self.calls.append(tuple(args))
        if args[0] == self.failed_command:
            return CommandResult(returncode=17, stdout="", stderr=self.failure_stderr)
        if args[0] == "lsd" and args[1].endswith(VALID_ROOT):
            return CommandResult(returncode=3, stdout="", stderr="directory not found")
        if args[0] == "copyto" and args[1].startswith("mailru:/"):
            Path(args[2]).write_text("hermes-mailcloud probe\n", encoding="utf-8")
        if args[:2] == ["link", "--unlink"]:
            return CommandResult(
                returncode=self.unlink_returncode, stdout="", stderr="backend says no"
            )
        if args[0] == "link":
            return CommandResult(returncode=0, stdout=f"{PUBLIC_URL}\n", stderr="")
        if args[0] == "version":
            return CommandResult(returncode=0, stdout="rclone v1.74.3\n", stderr="")
        if args[0] == "listremotes":
            return CommandResult(returncode=0, stdout="mailru:\n", stderr="")
        if args[0] == "lsjson":
            return CommandResult(returncode=0, stdout="[]", stderr="")
        return CommandResult(returncode=0, stdout="", stderr="")


class FakeHttpResponse:
    def __init__(self, *, status: int = 200, content_type: str = "text/html") -> None:
        self.status = status
        self.headers = {"Content-Type": content_type}
        self.read_sizes: list[int] = []

    def read(self, size: int) -> bytes:
        self.read_sizes.append(size)
        return b"x" * size

    def close(self) -> None:
        return None


@dataclass
class FakeOpener:
    response: FakeHttpResponse = field(default_factory=FakeHttpResponse)
    calls: list[Any] = field(default_factory=list)

    def open(self, request: Any, *, timeout: float) -> FakeHttpResponse:
        self.calls.append((request, timeout))
        return self.response


@dataclass
class SequenceOpener:
    statuses: list[int]
    calls: list[Any] = field(default_factory=list)

    def open(self, request: Any, *, timeout: float) -> FakeHttpResponse:
        self.calls.append((request, timeout))
        return FakeHttpResponse(status=self.statuses.pop(0))


def test_redact_text_removes_credentials_and_public_capability_urls() -> None:
    raw = (
        "access_token=abc123 Password=my-secret "
        "Authorization: Bearer *** Cookie: session=cookie-value "
        '"access_token": "quoted-token-sentinel" '
        '"password": "quoted-password-sentinel" '
        '"cookie": "quoted-cookie-sentinel" '
        '"authorization": "Bearer quoted-authorization-sentinel" '
        r"{\"access_token\":\"escaped-token-sentinel\"} "
        r"{\\\"password\\\":\\\"double-escaped-password-sentinel\\\"} "
        f"link={PUBLIC_URL}"
    )

    redacted = redact_text(raw)

    for secret in (
        "abc123",
        "my-secret",
        "bearer-value",
        "cookie-value",
        "quoted-token-sentinel",
        "quoted-password-sentinel",
        "quoted-cookie-sentinel",
        "quoted-authorization-sentinel",
        "escaped-token-sentinel",
        "double-escaped-password-sentinel",
        PUBLIC_URL,
    ):
        assert secret not in redacted
    assert "[REDACTED]" in redacted
    assert "sha256:" in redacted


def test_sanitize_value_redacts_values_under_sensitive_mapping_keys() -> None:
    payload = {
        "access_token": "mapping-token-sentinel",
        "nested": {"Cookie": "mapping-cookie-sentinel"},
        "safe": "unchanged",
    }

    sanitized = sanitize_value(payload)
    rendered = json.dumps(sanitized)

    assert "mapping-token-sentinel" not in rendered
    assert "mapping-cookie-sentinel" not in rendered
    assert sanitized["safe"] == "unchanged"


@pytest.mark.parametrize(
    "root",
    [
        "/TEST",
        "/TEST/",
        "/TEST/../Hermes/private",
        "/Hermes/public",
        "/TEST/not-a-hermes-mailcloud-run",
    ],
)
def test_validate_test_root_rejects_non_generated_or_escape_roots(root: str) -> None:
    with pytest.raises(ValueError):
        validate_test_root(root)


def test_validate_test_root_accepts_only_a_generated_direct_descendant() -> None:
    assert validate_test_root(VALID_ROOT) == VALID_ROOT


def test_mutating_probe_requires_hmc_live_before_any_runner_call() -> None:
    runner = FakeRunner()

    outcome = run_file_ops_probe(
        remote="mailru:", root=VALID_ROOT, runner=runner, live_enabled=False
    )

    assert outcome.ok is False
    assert outcome.error["kind"] == "live_not_enabled"
    assert runner.calls == []


def test_fake_runner_exercises_file_probe_and_accounts_for_cleanup() -> None:
    runner = FakeRunner()

    outcome = run_file_ops_probe(
        remote="mailru:", root=VALID_ROOT, runner=runner, live_enabled=True
    )

    assert outcome.ok is True
    assert outcome.checks == {
        "root_absent": True,
        "mkdir": True,
        "upload": True,
        "list": True,
        "download": True,
        "content_match": True,
        "move": True,
        "delete": True,
    }
    assert outcome.cleanup["complete"] is True
    assert outcome.cleanup["root"] == VALID_ROOT
    assert any(call[0] == "rmdir" for call in runner.calls)
    assert all(call[0] != "subprocess" for call in runner.calls)


def test_failure_report_is_sanitized_and_still_attempts_isolated_cleanup() -> None:
    runner = FakeRunner(failed_command="copyto")

    outcome = run_file_ops_probe(
        remote="mailru:", root=VALID_ROOT, runner=runner, live_enabled=True
    )
    rendered = json.dumps(outcome.to_payload())

    assert outcome.ok is False
    assert outcome.error["kind"] == "rclone_command_failed"
    assert "not-for-output" not in rendered
    assert outcome.cleanup["complete"] is True
    assert any(call[0] == "rmdir" for call in runner.calls)


def test_publish_probe_uses_fake_runner_and_never_serializes_public_url() -> None:
    runner = FakeRunner()
    opener = SequenceOpener([200, 200, 404])

    outcome = run_publish_probe(
        remote="mailru:", root=VALID_ROOT, runner=runner, live_enabled=True, opener=opener
    )
    rendered = json.dumps(outcome.to_payload())

    assert outcome.ok is True
    assert outcome.checks["link_create"] is True
    assert outcome.checks["public_url_probe"] is True
    assert outcome.cleanup["complete"] is True
    assert outcome.cleanup["public_capability_count"] == 1
    assert outcome.cleanup["invalidated_public_capability_count"] == 1
    assert len(opener.calls) == 3
    assert any(call[0] == "deletefile" for call in runner.calls)
    assert PUBLIC_URL not in rendered
    assert outcome.result["public_url_fingerprint"].startswith("sha256:")


def test_publish_probe_marks_cleanup_incomplete_when_public_capability_stays_reachable() -> None:
    runner = FakeRunner()
    opener = SequenceOpener([200, 200, 200])

    outcome = run_publish_probe(
        remote="mailru:", root=VALID_ROOT, runner=runner, live_enabled=True, opener=opener
    )

    assert outcome.ok is False
    assert outcome.error["kind"] == "cleanup_failed"
    assert outcome.cleanup["complete"] is False
    assert outcome.cleanup["invalidated_public_capability_count"] == 0
    assert outcome.cleanup["unresolved_public_capability_fingerprints"] == [
        outcome.result["public_url_fingerprint"]
    ]


def test_unlink_probe_proves_invalidation_with_a_fake_404() -> None:
    runner = FakeRunner()
    opener = SequenceOpener([200, 200, 404])

    outcome = run_unlink_probe(
        remote="mailru:", root=VALID_ROOT, runner=runner, live_enabled=True, opener=opener
    )

    assert outcome.ok is True
    assert outcome.result["unlink_supported"] is True
    assert outcome.result["post_unlink_status_code"] == 404
    assert outcome.cleanup["complete"] is True


def test_public_url_policy_rejects_non_mailru_hosts_without_http_call() -> None:
    opener = FakeOpener()

    with pytest.raises(ValueError):
        probe_public_url("https://example.invalid/public/nope", opener=opener)

    assert opener.calls == []


def test_public_url_probe_bounds_response_body_and_redacts_url() -> None:
    opener = FakeOpener()

    report = probe_public_url(PUBLIC_URL, opener=opener)
    rendered = json.dumps(report)

    assert report["http_accessible"] is True
    assert report["download_mode"] == "browser_page"
    assert len(opener.calls) == 2
    assert opener.response.read_sizes == [MAX_HTTP_BODY_BYTES]
    assert PUBLIC_URL not in rendered
    assert report["public_url_fingerprint"].startswith("sha256:")


def test_entrypoint_emits_json_failure_without_real_calls(
    capsys: pytest.CaptureFixture[str],
) -> None:
    runner = FakeRunner()

    exit_code = main(
        "01_file_ops_probe",
        ["--remote", "mailru:", "--root", VALID_ROOT, "--json"],
        runner=runner,
        environment={},
    )

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 1
    assert payload["ok"] is False
    assert payload["error"]["kind"] == "live_not_enabled"
    assert runner.calls == []


def test_entrypoint_redacts_structured_diagnostics_in_stdout_and_artifact(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    sentinels = (
        "structured-token-sentinel",
        "structured-password-sentinel",
        "structured-cookie-sentinel",
        "structured-authorization-sentinel",
    )
    runner = FakeRunner(
        failed_command="copyto",
        failure_stderr=(
            r"{\"access_token\":\"structured-token-sentinel\","
            r"\"password\":\"structured-password-sentinel\","
            r"\"cookie\":\"structured-cookie-sentinel\","
            r"\"authorization\":\"Bearer structured-authorization-sentinel\"}"
        ),
    )
    artifact_dir = tmp_path / "probe-results"

    exit_code = main(
        "01_file_ops_probe",
        [
            "--remote",
            "mailru:",
            "--root",
            VALID_ROOT,
            "--json",
            "--artifacts-dir",
            str(artifact_dir),
        ],
        runner=runner,
        environment={"HMC_LIVE": "1"},
    )

    artifact = next(artifact_dir.glob("*.json"))
    rendered = capsys.readouterr().out + artifact.read_text(encoding="utf-8")

    assert exit_code == 1
    assert len(rendered.splitlines()) == 2
    for sentinel in sentinels:
        assert sentinel not in rendered


def test_public_url_entrypoint_writes_only_a_sanitized_opt_in_artifact(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    artifact_dir = tmp_path / "probe-results"

    exit_code = main(
        "04_public_url_probe",
        ["--json", "--artifacts-dir", str(artifact_dir)],
        opener=FakeOpener(),
        environment={},
        private_input=StringIO(f"{PUBLIC_URL}\n"),
    )

    payload = json.loads(capsys.readouterr().out)
    artifact_files = list(artifact_dir.glob("*.json"))
    assert exit_code == 0
    assert payload["ok"] is True
    assert payload["artifact"] == {"requested": True, "written": True}
    assert len(artifact_files) == 1
    assert PUBLIC_URL not in artifact_files[0].read_text(encoding="utf-8")


def test_public_url_entrypoint_rejects_raw_capability_in_argv(
    capsys: pytest.CaptureFixture[str],
) -> None:
    exit_code = main(
        "04_public_url_probe",
        [PUBLIC_URL, "--json"],
        environment={},
        private_input=StringIO(f"{PUBLIC_URL}\n"),
    )

    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 1
    assert payload["error"]["kind"] == "invalid_input"
    assert PUBLIC_URL not in json.dumps(payload)


@pytest.mark.parametrize("argv", [["--help"], ["--not-an-option"]])
def test_entrypoint_help_and_argument_failures_are_exactly_one_json_object(
    argv: list[str], capsys: pytest.CaptureFixture[str]
) -> None:
    runner = FakeRunner()

    exit_code = main("04_public_url_probe", argv, runner=runner, environment={})

    captured = capsys.readouterr()
    lines = captured.out.splitlines()
    payload = json.loads(captured.out)

    assert captured.err == ""
    assert len(lines) == 1
    assert payload["probe"] == "04_public_url_probe"
    assert exit_code == (0 if argv == ["--help"] else 1)
    assert runner.calls == []
