"""Offline CLI/package controls for explicit user-scoped rclone preparation."""

from __future__ import annotations

import json
import os
import socket
from pathlib import Path

import jsonschema
import pytest
from tests.helpers.rclone_install import archive_fixture, environment
from typer.testing import CliRunner

from hermes_mailcloud.cli import app


@pytest.fixture
def isolated(monkeypatch, tmp_path):
    values = environment(tmp_path)
    for key in ("HMC_RCLONE_PATH", "HMC_REMOTE", "HMC_PROFILE", "HMC_LINKS_JOURNAL"):
        monkeypatch.delenv(key, raising=False)
    for key, value in values.items():
        monkeypatch.setenv(key, value)

    def no_network(*args, **kwargs):
        raise AssertionError("ordinary offline CLI must not open the network")

    monkeypatch.setattr(socket.socket, "connect", no_network)
    return values


def test_setup_human_help_is_an_explicit_network_free_command(isolated) -> None:
    result = CliRunner().invoke(app, ["setup", "--help"])
    assert result.exit_code == 0, result.output
    assert "--archive" in result.output
    assert "rclone" in result.output


def test_setup_json_dry_run_does_not_download_or_create_user_data(isolated) -> None:
    result = CliRunner().invoke(app, ["setup", "--dry-run", "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["operation"] == "setup" and payload["ok"] is True
    assert payload["result"]["dependency"] == "rclone"
    assert payload["result"]["status"] == "dry_run"
    assert payload["result"]["cloud_configured"] is False
    assert not (Path(isolated["XDG_DATA_HOME"]) / "hermes-mailcloud").exists()
    assert not (Path(isolated["LOCALAPPDATA"]) / "hermes-mailcloud").exists()


def test_doctor_explains_next_step_without_preparing_the_dependency(isolated) -> None:
    result = CliRunner().invoke(app, ["--json", "doctor"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["result"]["mode"] == "read_only"
    assert payload["result"]["checks"]["rclone_installed"] is False
    assert payload["result"]["checks"]["cloud_access"] is False
    assert any("hermes-mailcloud setup" in warning for warning in payload["warnings"])
    assert not (Path(isolated["XDG_DATA_HOME"]) / "hermes-mailcloud").exists()
    assert not (Path(isolated["LOCALAPPDATA"]) / "hermes-mailcloud").exists()


@pytest.mark.parametrize("arguments", [["--help"], ["version"], ["--json", "version"]])
def test_existing_readiness_commands_do_not_bootstrap_or_download(isolated, arguments) -> None:
    result = CliRunner().invoke(app, arguments)
    assert result.exit_code == 0, result.output
    assert not (Path(isolated["XDG_DATA_HOME"]) / "hermes-mailcloud").exists()
    assert not (Path(isolated["LOCALAPPDATA"]) / "hermes-mailcloud").exists()


def test_setup_explicit_missing_override_is_not_replaced_by_managed_copy(isolated) -> None:
    missing = Path(isolated["HOME"]) / ("explicit-missing.exe" if os.name == "nt" else "missing")
    os.environ["HMC_RCLONE_PATH"] = str(missing)
    result = CliRunner().invoke(app, ["--json", "setup"])
    assert result.exit_code == 4, result.output
    payload = json.loads(result.stdout)
    assert payload["operation"] == "setup" and payload["ok"] is False
    assert payload["error"]["kind"] == "rclone_not_found"
    assert str(missing) not in result.output


def test_setup_cli_success_uses_real_installer_and_new_schema(isolated, monkeypatch, tmp_path):
    from hermes_mailcloud.rclone import install

    system = "windows" if os.name == "nt" else "linux"
    payload, specification, _ = archive_fixture(system)
    release = install.Release(**specification)
    archive = tmp_path / "verified-local.zip"
    archive.write_bytes(payload)
    monkeypatch.setattr(install, "pinned_release", lambda: release)
    monkeypatch.setattr(install, "_verify_executable", lambda *a, **k: release.version)
    result = CliRunner().invoke(app, ["setup", "--archive", str(archive), "--json"])
    assert result.exit_code == 0, result.output
    envelope = json.loads(result.stdout)
    assert envelope["operation"] == "setup" and envelope["ok"] is True
    assert envelope["result"]["status"] == "installed"
    assert envelope["result"]["cloud_configured"] is False
    schema = json.loads(
        (
            Path(__file__).resolve().parents[2] / "schemas" / "result-envelope.schema.json"
        ).read_bytes()
    )
    jsonschema.validate(envelope, schema)
    assert str(install.managed_data_root(isolated)) not in result.output
    assert install.managed_rclone_path(isolated) is not None


@pytest.mark.parametrize(
    "bad",
    [
        {"cloud_configured": True},
        {"source": "download-from-user-url"},
        {"version": None},
        {"status": "maybe"},
        {"private_path": "forbidden"},
    ],
)
def test_setup_success_schema_rejects_inconsistent_or_unscoped_results(bad):
    schema = json.loads(
        (
            Path(__file__).resolve().parents[2] / "schemas" / "result-envelope.schema.json"
        ).read_bytes()
    )
    payload = {
        "ok": True,
        "operation": "setup",
        "result": {
            "dependency": "rclone",
            "status": "installed",
            "source": "managed",
            "version": "v1.75.2",
            "cloud_configured": False,
        }
        | bad,
    }
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(payload, schema)


def test_pinned_manifest_is_package_data_and_no_rclone_binary_is_vendored():
    from importlib.resources import files

    package = files("hermes_mailcloud.rclone")
    manifest = json.loads(package.joinpath("releases.json").read_bytes())
    assert manifest["version"] == "v1.75.2"
    assert not any(
        value.name.endswith((".zip", ".exe")) or value.name == "rclone"
        for value in package.iterdir()
    )
