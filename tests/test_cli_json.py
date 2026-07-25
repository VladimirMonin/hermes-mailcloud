"""Subprocess-level JSON output contract tests for the Typer CLI plumbing."""

from __future__ import annotations

import json
import subprocess
import sys

import pytest


def _run_cli(*arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "hermes_mailcloud.cli", *arguments],
        capture_output=True,
        text=True,
        timeout=10,
    )


def test_json_placeholder_returns_one_error_document_and_nonzero_exit() -> None:
    result = _run_cli("--json", "--profile", "test", "--trace-id", "trace-123", "doctor")

    assert result.returncode == 12
    assert result.stderr == ""
    assert result.stdout.count("\n") == 1
    payload = json.loads(result.stdout)
    assert payload == {
        "error": {
            "exit_code": 12,
            "kind": "backend_unsupported",
            "message": "doctor is not implemented in this build",
        },
        "ok": False,
        "operation": "doctor",
        "profile": "test",
        "trace_id": "trace-123",
    }


def test_global_options_are_accepted_after_the_command_name() -> None:
    result = _run_cli(
        "doctor",
        "--json",
        "--profile",
        "test",
        "--timeout",
        "7",
        "--retries",
        "0",
        "--dry-run",
        "--yes",
        "--no-color",
    )

    assert result.returncode == 12
    assert json.loads(result.stdout)["error"]["kind"] == "backend_unsupported"
    assert result.stderr == ""


def test_json_version_is_a_single_success_envelope() -> None:
    result = _run_cli("version", "--json", "--pretty")

    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert payload["operation"] == "version"
    assert isinstance(payload["result"]["version"], str)


def test_human_placeholder_fails_honestly_without_stdout_output() -> None:
    result = _run_cli("doctor")

    assert result.returncode == 12
    assert result.stdout == ""
    assert "doctor is not implemented in this build" in result.stderr


def test_json_missing_argument_returns_one_typed_error_document() -> None:
    result = _run_cli("--json", "ls")

    assert result.returncode == 2
    assert result.stderr == ""
    assert result.stdout.count("\n") == 1
    assert json.loads(result.stdout) == {
        "error": {
            "exit_code": 2,
            "kind": "invalid_arguments",
            "message": "invalid command arguments",
        },
        "ok": False,
        "operation": "ls",
    }


@pytest.mark.parametrize(
    "operation",
    [
        "cli",
        "version",
        "doctor",
        "ls",
        "stat",
        "mkdir",
        "upload",
        "download",
        "mv",
        "cp",
        "rm",
        "publish",
        "link",
        "batch",
    ],
)
@pytest.mark.parametrize("json_before_command", [True, False])
def test_every_json_help_path_emits_one_json_document_without_rich_output(
    operation: str, json_before_command: bool
) -> None:
    command = [] if operation == "cli" else [operation]
    if json_before_command:
        arguments = ["--json", *command, "--help"]
    else:
        arguments = [*command, "--json", "--help"]

    result = _run_cli(*arguments)

    assert result.returncode == 0
    assert result.stderr == ""
    assert "Usage:" not in result.stdout
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert payload["operation"] == "cli"
    assert payload["result"]["help"]["command"] == operation


@pytest.mark.parametrize(
    ("operation", "arguments"),
    [
        ("ls", ["/Hermes"]),
        ("stat", ["/Hermes/example.txt"]),
        ("mkdir", ["/Hermes/private/reports"]),
        ("upload", ["local.txt", "/Hermes/private/remote.txt"]),
        ("download", ["/Hermes/private/remote.txt", "local.txt"]),
        ("mv", ["/Hermes/private/a.txt", "/Hermes/private/b.txt"]),
        ("cp", ["/Hermes/private/a.txt", "/Hermes/private/b.txt"]),
        ("rm", ["/Hermes/private/old.txt"]),
        ("publish", ["local.txt", "/Hermes/public/remote.txt"]),
        ("link", ["/Hermes/public/remote.txt"]),
        ("batch", ["plan.json"]),
    ],
)
def test_every_unimplemented_v0_1_command_returns_a_typed_nonzero_json_error(
    operation: str, arguments: list[str]
) -> None:
    result = _run_cli(operation, *arguments, "--json")

    assert result.returncode == 12
    payload = json.loads(result.stdout)
    assert payload["operation"] == operation
    assert payload["ok"] is False
    assert payload["error"]["kind"] == "backend_unsupported"
    assert result.stderr == ""
