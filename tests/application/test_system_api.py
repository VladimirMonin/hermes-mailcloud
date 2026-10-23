"""System operations keep the real installer/doctor owners independent of CLI."""

from __future__ import annotations

import io
import json
import os
import sys
from pathlib import Path

import pytest
from tests.helpers.application import RecordingBackend, synthetic_environment
from tests.helpers.cli_fake import CliFakeHarness
from tests.helpers.rclone_install import archive_fixture
from tests.helpers.rclone_install import environment as install_environment

from hermes_mailcloud.application import CallOptions, MailCloudApplication, composition
from hermes_mailcloud.core.errors import ErrorKind
from hermes_mailcloud.rclone import install
from hermes_mailcloud.rclone.runner import RcloneResult, RcloneRunner


def test_source_drift_live_doctor_dry_run_refuses_before_configuration(monkeypatch) -> None:
    from typer.testing import CliRunner

    import hermes_mailcloud.cli as cli
    from hermes_mailcloud.application import composition

    reached = []

    def forbidden(*args, **kwargs):
        reached.append("config")
        raise AssertionError("live dry-run must refuse before loading configuration")

    monkeypatch.setattr(composition, "load_config", forbidden)
    result = CliRunner().invoke(cli.app, ["doctor", "--live", "--yes", "--dry-run", "--json"])
    assert result.exit_code == 2, result.output
    assert reached == []


@pytest.mark.parametrize(
    "method,kwargs",
    [
        ("setup", {"archive": "archive.zip"}),
        ("setup", {"archive": True}),
        ("doctor", {"live": "false"}),
        ("doctor", {"live": 1}),
        ("doctor", {"live": None}),
    ],
)
def test_system_arguments_refuse_before_loader(method, kwargs) -> None:
    reached = []

    def forbidden(*a, **kw):
        reached.append(True)
        raise AssertionError("invalid scalar reached configuration")

    app = MailCloudApplication(environment={}, config_loader=forbidden, backend_factory=forbidden)
    result = getattr(app, method)(**kwargs)
    assert result.exit_code == 2 and result.error.kind is ErrorKind.INVALID_ARGUMENTS
    assert reached == []


@pytest.mark.parametrize("yes,dry_run,code", [(False, False, 9), (False, True, 9), (True, True, 2)])
def test_direct_live_admission_precedes_config_with_confirmation_priority(
    yes, dry_run, code
) -> None:
    reached = []

    def forbidden(*a, **kw):
        reached.append(True)
        raise AssertionError("refusal reached configuration")

    app = MailCloudApplication(environment={}, config_loader=forbidden, backend_factory=forbidden)
    result = app.doctor(live=True, options=CallOptions(yes=yes, dry_run=dry_run))
    assert result.exit_code == code and not result.ok and reached == []


@pytest.mark.parametrize("method", ["setup", "doctor"])
@pytest.mark.parametrize(
    "options",
    [
        CallOptions(yes="false"),
        CallOptions(dry_run=0),
        CallOptions(retries=True),
        CallOptions(timeout_seconds=0),
        {},
    ],
)
def test_system_options_are_not_annotation_only(method, options) -> None:
    reached = []

    def forbidden(*a, **kw):
        reached.append(True)
        raise AssertionError("invalid options reached configuration")

    result = getattr(MailCloudApplication(environment={}, config_loader=forbidden), method)(
        options=options
    )
    assert result.exit_code == 2 and reached == []


@pytest.mark.parametrize("source_kind", ["archive", "download"])
def test_setup_uses_real_installer_version_check_activation_and_snapshot(
    tmp_path, monkeypatch, source_kind
) -> None:
    env = install_environment(tmp_path)
    original_env = dict(env)
    payload, specification, executable = archive_fixture("windows" if os.name == "nt" else "linux")
    release = install.Release(**specification)
    archive = tmp_path / "pinned.zip"
    archive.write_bytes(payload)
    root = install.managed_data_root(env)
    assert root.is_relative_to(tmp_path) and not root.exists()
    monkeypatch.setattr(install, "pinned_release", lambda: release)
    calls, downloads = [], []

    class VersionEdge(RcloneRunner):
        def run(self, args, *, timeout_seconds=None):
            assert args[-1] == "version" and Path(args[1]).read_bytes() == b""
            calls.append((list(args), timeout_seconds))
            return RcloneResult(0, f"rclone {release.version}\n", "", 0)

    monkeypatch.setattr(install, "RcloneRunner", VersionEdge)

    class Download(io.BytesIO):
        status = 200
        headers = {"Content-Length": str(len(payload))}

        def geturl(self):
            return release.url

    def download(url, *, timeout_seconds):
        downloads.append((url, timeout_seconds))
        return Download(payload)

    monkeypatch.setattr(install, "_open_download", download)

    def no_file_backend(*a, **kw):
        raise AssertionError("setup must not compose a file backend")

    app = MailCloudApplication(environment=env, backend_factory=no_file_backend)
    env["LOCALAPPDATA"] = str(tmp_path / "unused-local-data")
    env["XDG_DATA_HOME"] = str(tmp_path / "unused-xdg-data")
    result = app.setup(
        archive=archive if source_kind == "archive" else None,
        options=CallOptions(timeout_seconds=17, retries=3),
    )
    assert (
        result.ok
        and result.result["status"] == "installed"
        and result.result["cloud_configured"] is False
    )
    installed = Path(install.managed_rclone_path(original_env))
    assert installed.is_relative_to(root) and installed.read_bytes() == executable
    assert len(calls) == 1 and 0 < calls[0][1] <= 10
    assert len(downloads) == (source_kind == "download")
    assert not list(root.glob(".stage-*"))
    before = {p.relative_to(root): p.read_bytes() for p in root.rglob("*") if p.is_file()}
    assert app.setup(archive=archive).result["status"] == "already_available"
    missing_env = {**original_env, "HMC_RCLONE_PATH": str(tmp_path / "absent.exe")}
    refused = MailCloudApplication(environment=missing_env).setup()
    assert refused.error.kind is ErrorKind.RCLONE_NOT_FOUND
    assert {p.relative_to(root): p.read_bytes() for p in root.rglob("*") if p.is_file()} == before
    assert (
        not (tmp_path / "unused-local-data").exists()
        and not (tmp_path / "unused-xdg-data").exists()
    )


@pytest.mark.parametrize("failure", ["archive", "version"])
def test_setup_failure_keeps_neighbor_and_never_activates_unverified_bytes(
    tmp_path, monkeypatch, failure
) -> None:
    env = install_environment(tmp_path)
    payload, specification, _ = archive_fixture("windows" if os.name == "nt" else "linux")
    release = install.Release(**specification)
    monkeypatch.setattr(install, "pinned_release", lambda: release)
    archive = tmp_path / "pinned.zip"
    archive.write_bytes(payload + b"changed" if failure == "archive" else payload)
    neighbor = tmp_path / "neighbor.bin"
    neighbor.write_bytes(b"must survive")

    class WrongVersion(RcloneRunner):
        def run(self, args, *, timeout_seconds=None):
            return RcloneResult(0, "rclone v0.0.0\n", "", 0)

    monkeypatch.setattr(install, "RcloneRunner", WrongVersion)
    result = MailCloudApplication(environment=env).setup(archive=archive)
    root = install.managed_data_root(env)
    assert result.error.kind is ErrorKind.PARSE_ERROR
    assert not (root / "active.json").exists() and not list(root.glob(".stage-*"))
    assert neighbor.read_bytes() == b"must survive"


def test_setup_dry_run_and_other_calls_never_bootstrap(tmp_path, monkeypatch) -> None:
    env = install_environment(tmp_path)

    def forbidden(*a, **kw):
        raise AssertionError("implicit installation/download/execution")

    monkeypatch.setattr(install, "_open_download", forbidden)
    monkeypatch.setattr(install, "_verify_executable", forbidden)
    backend = RecordingBackend(RcloneResult(1, "", "not found", 0))
    app = MailCloudApplication(environment=env, backend_factory=lambda *a, **kw: backend)
    assert app.version().ok
    planned = app.setup(
        archive=tmp_path / "not-required-for-plan.zip", options=CallOptions(dry_run=True)
    )
    assert planned.ok and planned.result["status"] == "dry_run" and backend.calls == []
    report = app.doctor()
    assert report.ok and report.result["mode"] == "read_only"
    assert not install.managed_data_root(env).exists()


def test_read_only_doctor_preserves_checks_warnings_and_independent_about(tmp_path) -> None:
    backend = RecordingBackend(
        RcloneResult(0, "rclone v1.75.2 token=doctor-private-sentinel\n", "", 0),
        RcloneResult(0, "fake:\n", "", 0),
        RcloneResult(1, "private-provider-stream", "network unreachable", 0),
        RcloneResult(0, "{}", "", 0),
    )
    app = MailCloudApplication(
        environment=synthetic_environment(tmp_path), backend_factory=lambda *a, **kw: backend
    )
    result = app.doctor(options=CallOptions(dry_run=True, timeout_seconds=7))
    assert result.ok and result.result["mode"] == "read_only"
    assert result.result["checks"]["cloud_access"] is False
    assert [args[0] for args, _ in backend.calls] == ["version", "listremotes", "lsd", "about"]
    assert all(timeout == 7 for _, timeout in backend.calls)
    assert "doctor-private-sentinel" not in repr(result) + result.to_json()
    assert "private-provider-stream" not in repr(result) + result.to_json()


def test_live_doctor_reuses_real_probes_http_and_cleanup_without_trusting_cli(tmp_path) -> None:
    from tests.doctor.test_doctor import FakeBackend, SequenceOpener

    backends = []

    def factory(*a, **kw):
        backend = FakeBackend(unlink_returncode=1, unlink_stderr="backend operation not supported")
        backends.append(backend)
        return backend

    opener = SequenceOpener([200, 200, 404, 200, 200, 404])
    app = MailCloudApplication(
        environment=synthetic_environment(tmp_path, '[profiles.default]\nremote="mailru:"\n'),
        backend_factory=factory,
        http_opener=opener,
    )
    refused = app.doctor(live=True)
    assert refused.exit_code == 9 and backends == []
    result = app.doctor(live=True, options=CallOptions(yes=True, timeout_seconds=7))
    assert result.ok and result.result["checks"]["cleanup"] is True
    assert result.result["checks"]["file_cycle"] is True
    assert result.result["capabilities"]["file_ops"] == "supported"
    assert result.result["capabilities"]["public_link_unlink"] == "unsupported"
    roots = result.result["test_roots"]
    assert len(roots) == len(set(roots)) == 3 and all(
        root.startswith("/TEST/hermes-mailcloud-") for root in roots
    )
    assert len(opener.calls) == 6 and result.warnings
    assert any("not shipped" in warning for warning in result.warnings)
    assert "doctor-version-sentinel" not in repr(result)
    after = app.doctor()
    assert after.ok and after.result["mode"] == "read_only" and len(backends) == 2
    assert all(args[0] in {"version", "listremotes", "lsd", "about"} for args in backends[1].calls)


@pytest.mark.parametrize("operation", ["setup", "doctor"])
def test_system_direct_subprocess_cli_payload_schema_and_channels(tmp_path, operation) -> None:
    harness = CliFakeHarness.create(tmp_path)
    kwargs = {"options": CallOptions(dry_run=operation == "setup", trace_id="system-parity")}
    args = [operation, "--json", "--trace-id", "system-parity"]
    if operation == "setup":
        args.append("--dry-run")
    cli = harness.run(
        *args,
        responses={
            "version": {"stdout": "rclone v1.75.2\n"},
            "listremotes": {"stdout": "fake:\n"},
            "about": {"stdout": "{}"},
        },
    )
    app = MailCloudApplication(
        environment=synthetic_environment(tmp_path),
        backend_factory=lambda config, *, environment: RcloneRunner(
            (sys.executable, str(harness.script)), environment=environment
        ),
    )
    direct = getattr(app, operation)(**kwargs)
    assert direct.exit_code == cli.returncode == 0, cli.stdout + cli.stderr
    assert cli.stderr == "" and json.loads(cli.stdout) == direct.to_payload()
    from tests.test_schemas import _validator

    # Bind all local $refs; never let schema validation retrieve a remote URI.
    _validator("doctor-report" if operation == "doctor" else "result-envelope").validate(
        direct.to_payload()
    )
    assert len(harness.recorded_calls()) == (8 if operation == "doctor" else 0)


@pytest.mark.parametrize("operation", ["setup", "doctor"])
def test_system_cli_handler_calls_actual_application_owner(
    tmp_path, monkeypatch, operation
) -> None:
    from typer.testing import CliRunner

    import hermes_mailcloud.cli as cli

    for key, value in synthetic_environment(tmp_path).items():
        monkeypatch.setenv(key, value)
    backend = RecordingBackend(RcloneResult(1, "", "not found", 0))
    monkeypatch.setattr(composition, "create_backend", lambda *a, **kw: backend)
    reached, original = [], getattr(MailCloudApplication, operation)

    def observed(self, *args, **kwargs):
        reached.append(operation)
        return original(self, *args, **kwargs)

    monkeypatch.setattr(MailCloudApplication, operation, observed)
    args = [operation, "--json"] + (["--dry-run"] if operation == "setup" else [])
    result = CliRunner().invoke(cli.app, args)
    assert result.exit_code == 0, result.output
    assert reached == [operation] and json.loads(result.stdout)["operation"] == operation
    assert len(backend.calls) == (1 if operation == "doctor" else 0)


@pytest.mark.parametrize(
    "method,kwargs,options,code",
    [
        ("doctor", {"live": True}, CallOptions(), 9),
        ("doctor", {"live": True}, CallOptions(yes=True, dry_run=True), 2),
        ("setup", {"archive": "not-a-Path.zip"}, CallOptions(), 2),
    ],
)
def test_system_admission_is_not_masked_by_invalid_environment_profile(
    method, kwargs, options, code
) -> None:
    reached = []

    def forbidden(*a, **kw):
        reached.append(True)
        raise AssertionError("admission must precede configuration")

    result = getattr(
        MailCloudApplication(environment={"HMC_PROFILE": " "}, config_loader=forbidden), method
    )(**kwargs, options=options)
    assert result.exit_code == code and reached == []
