"""Subprocess-level JSON output contract tests for the Typer CLI plumbing."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest


def _run_cli(
    *arguments: str, environment: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env.pop("HMC_CONFIG", None)
    if environment:
        env.update(environment)
    return subprocess.run(
        [sys.executable, "-m", "hermes_mailcloud.cli", *arguments],
        capture_output=True,
        text=True,
        timeout=10,
        env=env,
    )


def _doctor_environment(tmp_path: Path) -> dict[str, str]:
    return {
        "XDG_CONFIG_HOME": str(tmp_path / "config-home"),
        "HMC_RCLONE_PATH": sys.executable,
        "HMC_REMOTE": "mailru:",
    }


def test_json_live_doctor_requires_confirmation_before_config_or_backend_access() -> None:
    result = _run_cli("--json", "--profile", "test", "--trace-id", "trace-123", "doctor", "--live")

    assert result.returncode == 9
    assert result.stderr == ""
    assert result.stdout.count("\n") == 1
    payload = json.loads(result.stdout)
    assert payload == {
        "error": {
            "exit_code": 9,
            "kind": "confirmation_required",
            "message": "doctor --live requires --yes before it can create generated /TEST objects",
        },
        "ok": False,
        "operation": "doctor",
        "profile": "test",
        "trace_id": "trace-123",
    }


def test_global_options_are_accepted_after_the_command_name(tmp_path: Path) -> None:
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
        environment=_doctor_environment(tmp_path),
    )

    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["result"]["mode"] == "read_only"
    assert payload["result"]["checks"]["rclone_installed"] is False
    assert result.stderr == ""


def test_json_version_is_a_single_success_envelope() -> None:
    result = _run_cli("version", "--json", "--pretty")

    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert payload["operation"] == "version"
    assert isinstance(payload["result"]["version"], str)


def test_human_doctor_returns_a_read_only_report_without_raw_backend_output(tmp_path: Path) -> None:
    result = _run_cli("doctor", environment=_doctor_environment(tmp_path))

    assert result.returncode == 0
    assert result.stdout == "command completed\n"
    assert result.stderr == ""


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


def test_batch_missing_plan_returns_a_typed_nonzero_json_error() -> None:
    result = _run_cli("batch", "plan.json", "--json")

    assert result.returncode == 7
    payload = json.loads(result.stdout)
    assert payload["operation"] == "batch"
    assert payload["ok"] is False
    assert payload["error"]["kind"] == "not_found"
    assert result.stderr == ""
