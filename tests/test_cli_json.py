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


@pytest.mark.parametrize(
    ("arguments", "selected"),
    [([], "work"), (["--profile", "default"], "default"), (["--profile", "other"], "other")],
)
def test_version_profile_selection_is_lazy(
    tmp_path: Path, arguments: list[str], selected: str
) -> None:
    result = _run_cli(
        "--json",
        *arguments,
        "version",
        environment={"HMC_PROFILE": "work", "HMC_CONFIG": str(tmp_path / "absent.toml")},
    )
    assert result.returncode == 0 and result.stderr == ""
    payload = json.loads(result.stdout)
    assert payload["profile"] == selected and "remote" not in payload
    assert payload["result"]["version"]


def test_profile_help_explains_environment_and_default() -> None:
    result = _run_cli("--help")
    assert result.returncode == 0
    assert "HMC_PROFILE" in result.stdout and "default" in result.stdout


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


@pytest.mark.parametrize(
    ("profile_arguments", "profile", "remote"),
    [([], "work", "work:"), (["--profile", "default"], "default", "default:")],
    ids=["omitted-profile-uses-environment", "explicit-default-wins"],
)
def test_cli_profile_environment_and_explicit_default(
    tmp_path: Path, profile_arguments: list[str], profile: str, remote: str
) -> None:
    config = tmp_path / "profiles.toml"
    config.write_text(
        '[profiles.default]\nremote = "default:"\n[profiles.work]\nremote = "work:"\n',
        encoding="utf-8",
    )
    environment = _doctor_environment(tmp_path)
    environment.pop("HMC_REMOTE")
    environment.update(HMC_CONFIG=str(config), HMC_PROFILE="work")
    result = _run_cli("--json", *profile_arguments, "doctor", environment=environment)

    assert result.returncode == 0
    assert result.stderr == ""
    payload = json.loads(result.stdout)
    assert payload["profile"] == profile
    assert payload["remote"] == remote
    assert payload["result"]["mode"] == "read_only"


@pytest.mark.parametrize(
    ("arguments", "code", "kind"),
    [
        (["doctor"], 3, "config_error"),
        (["mkdir", "/Hermes/private/planned", "--dry-run"], 3, "config_error"),
        (["batch", "absent-plan.json"], 7, "not_found"),
        (["ls", "/Hermes"], 3, "config_error"),
        (["version"], 3, "config_error"),
    ],
)
def test_invalid_environment_profile_cannot_escape_safe_error_metadata(
    tmp_path: Path, arguments: list[str], code: int, kind: str
) -> None:
    result = _run_cli(
        "--json",
        *arguments,
        environment={**_doctor_environment(tmp_path), "HMC_PROFILE": " "},
    )
    assert result.returncode == code and result.stderr == ""
    assert result.stdout.count("\n") == 1
    assert json.loads(result.stdout)["error"]["kind"] == kind


def test_batch_missing_plan_returns_a_typed_nonzero_json_error() -> None:
    result = _run_cli("batch", "plan.json", "--json")

    assert result.returncode == 7
    payload = json.loads(result.stdout)
    assert payload["operation"] == "batch"
    assert payload["ok"] is False
    assert payload["error"]["kind"] == "not_found"
    assert result.stderr == ""
