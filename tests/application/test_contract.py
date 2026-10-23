"""Executable in-process contract, lazy behavior and transport independence."""

from __future__ import annotations

import ast
import json
import subprocess
import sys
import textwrap
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest
from tests.helpers.application import synthetic_environment

from hermes_mailcloud import __version__
from hermes_mailcloud.application import (
    CallOptions,
    ConfigOverrides,
    MailCloudApplication,
    composition,
)
from hermes_mailcloud.application.service import _finalize
from hermes_mailcloud.core.errors import ErrorKind, ErrorPayload
from hermes_mailcloud.core.result import ResultEnvelope


def test_only_implemented_operations_are_public_and_options_are_small_and_frozen() -> None:
    assert {name for name in vars(MailCloudApplication) if not name.startswith("_")} == {
        "version",
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
        "setup",
        "doctor",
        "batch",
        "batch_file",
    }
    first, second = CallOptions(), CallOptions()
    assert first.config == ConfigOverrides() and first.config is not second.config
    assert first.retries is None and first.timeout_seconds is None
    assert first.yes is False and first.dry_run is False
    with pytest.raises(FrozenInstanceError):
        first.yes = True
    with pytest.raises(TypeError):
        MailCloudApplication().stat()
    with pytest.raises(TypeError):
        MailCloudApplication().version(unknown=True)


def test_constructor_and_version_are_lazy_and_silent(tmp_path: Path, monkeypatch, capsys) -> None:
    def forbidden(*_args, **_kwargs):
        pytest.fail("lazy operation touched configuration/backend")

    monkeypatch.setattr(composition, "load_config", forbidden)
    monkeypatch.setattr(composition, "create_backend", forbidden)
    monkeypatch.setattr(subprocess, "Popen", forbidden)
    missing = tmp_path / "missing-config.toml"
    application = MailCloudApplication(
        environment={"HMC_CONFIG": str(missing), "HMC_PROFILE": "work"}
    )
    result = application.version(
        options=CallOptions(trace_id="lazy", config=ConfigOverrides(remote="x:"))
    )
    assert result.to_payload() == {
        "ok": True,
        "operation": "version",
        "profile": "work",
        "trace_id": "lazy",
        "result": {"version": __version__},
    }
    assert not missing.exists()
    assert capsys.readouterr() == ("", "")


@pytest.mark.parametrize(
    "options",
    [
        {},
        False,
        CallOptions(config={}),
        CallOptions(config=None),
        CallOptions(config=ConfigOverrides(profile=1)),
        CallOptions(config=ConfigOverrides(remote=True)),
        CallOptions(config=ConfigOverrides(config_path="not-a-Path")),
        CallOptions(trace_id=0),
        CallOptions(yes="false"),
        CallOptions(yes=0),
        CallOptions(dry_run=1),
        CallOptions(dry_run="false"),
        CallOptions(timeout_seconds=True),
        CallOptions(timeout_seconds=0),
        CallOptions(timeout_seconds=-1),
        CallOptions(timeout_seconds=1.5),
        CallOptions(timeout_seconds=float("nan")),
        CallOptions(timeout_seconds="2"),
        CallOptions(retries=True),
        CallOptions(retries=-1),
        CallOptions(retries=1.0),
        CallOptions(retries="0"),
    ],
)
def test_invalid_options_are_typed_refusals_before_config_or_backend(options) -> None:
    def forbidden(*_args, **_kwargs):
        pytest.fail("invalid input reached an effect")

    application = MailCloudApplication(
        environment={}, config_loader=forbidden, backend_factory=forbidden
    )
    for envelope in (
        application.version(options=options),
        application.ls("/Hermes", options=options),
    ):
        assert envelope.error.kind is ErrorKind.INVALID_ARGUMENTS
        assert envelope.exit_code == 2
        assert envelope.result is None


def test_finalizer_copies_all_direct_data_and_preserves_error_types() -> None:
    public = "https://cloud.mail.ru/public/direct-finalizer-capability/path"
    original = ResultEnvelope.success(
        "ls",
        {"items": [{"token": "result-secret", "count": 0}], "link": public},
        trace_id="token=trace-secret",
        profile="password=profile-secret",
        remote="cookie=remote-secret",
        warnings=("token=warning-secret",),
    )
    safe = _finalize(original)
    assert safe.result["items"] == [{"token": "[REDACTED]", "count": 0}]
    safe.result["items"].append({"count": 1})
    assert len(original.result["items"]) == 1
    error = _finalize(
        ResultEnvelope.failure(
            "stat",
            ErrorPayload(
                ErrorKind.NOT_FOUND,
                "token=message-secret",
                {"token": "detail-secret", "attempts": 0},
            ),
        )
    )
    assert error.error.kind is ErrorKind.NOT_FOUND and error.exit_code == 7
    assert error.error.details == {"token": "[REDACTED]", "attempts": 0}
    for sentinel in (
        public,
        "result-secret",
        "trace-secret",
        "profile-secret",
        "remote-secret",
        "warning-secret",
        "message-secret",
        "detail-secret",
    ):
        assert sentinel not in repr(safe) + repr(error)


def test_projection_failure_never_returns_raw_data(monkeypatch) -> None:
    from hermes_mailcloud.application import service

    def broken(_value):
        raise RuntimeError("private-projection-sentinel")

    monkeypatch.setattr(service, "sanitize_value", broken)
    result = MailCloudApplication(environment={}).version(
        options=CallOptions(trace_id="token=private-trace-sentinel")
    )
    assert result.error.kind is ErrorKind.UNKNOWN_ERROR and result.exit_code == 1
    assert result.trace_id is None
    assert "private-projection-sentinel" not in repr(result)
    assert "private-trace-sentinel" not in repr(result)


def test_application_imports_do_not_name_cli_frameworks() -> None:
    root = Path(__file__).resolve().parents[2] / "src/hermes_mailcloud/application"
    forbidden = {"typer", "click", "rich", "PySide6", "mcp", "cli"}
    modules = sorted(root.glob("*.py"))
    assert len(modules) == 5
    for path in modules:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or "", *(alias.name for alias in node.names)]
            else:
                continue
            assert not forbidden.intersection(part for name in names for part in name.split(".")), (
                path
            )


def test_real_read_api_executes_with_cli_sdk_imports_blocked(tmp_path: Path) -> None:
    environment = synthetic_environment(tmp_path)
    fake = tmp_path / "external.py"
    fake.write_text(
        "import json\n"
        'print(json.dumps([{"Path":"a.txt","Name":"a.txt","IsDir":False,"Size":0}]))\n',
        encoding="utf-8",
    )
    source = textwrap.dedent(f"""
        import importlib.abc, json, sys
        class NoShell(importlib.abc.MetaPathFinder):
            def find_spec(self, fullname, path=None, target=None):
                if (fullname.split('.')[0] in {{'typer', 'click', 'rich', 'PySide6', 'mcp'}}
                        or fullname == 'hermes_mailcloud.cli'):
                    raise AssertionError('CLI SDK import: ' + fullname)
        sys.meta_path.insert(0, NoShell())
        from hermes_mailcloud.application import MailCloudApplication, CallOptions
        from hermes_mailcloud.rclone.runner import RcloneRunner
        def factory(config, *, environment):
            return RcloneRunner((sys.executable, {str(fake)!r}), environment=environment)
        app = MailCloudApplication(backend_factory=factory)
        assert app.version().ok
        read = app.ls('/Hermes')
        assert read.ok and read.result['items'][0]['size'] == 0
        setup = app.setup(options=CallOptions(dry_run=True))
        assert setup.ok and setup.result['status'] == 'dry_run'
        doctor = app.doctor()
        assert doctor.ok and doctor.result['mode'] == 'read_only'
        document = {{'version': 1, 'operations': [{{'op': 'ls', 'remote_path': '/Hermes'}}]}}
        batch = app.batch(document, options=CallOptions(dry_run=True))
        assert batch.ok and batch.result['items'][0]['result']['dry_run'] is True
        planned = app.mkdir('/TEST/api-plan', options=CallOptions(dry_run=True))
        assert planned.ok and planned.result['dry_run'] is True and planned.result['plan']
        protected = app.rm('/TEST', options=CallOptions(yes=True))
        assert not protected.ok and protected.exit_code == 2
        refused = app.ls('/Hermes', recursive=1)
        assert refused.exit_code == 2
        assert not any(name.split('.')[0] in {{'typer', 'click', 'rich'}} for name in sys.modules)
        assert 'hermes_mailcloud.cli' not in sys.modules
        print(json.dumps(read.to_payload()))
    """)
    result = subprocess.run(
        [sys.executable, "-c", source],
        env=environment,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=15,
    )
    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    assert json.loads(result.stdout)["result"]["items"] == [
        {"path": "/Hermes/a.txt", "name": "a.txt", "type": "file", "size": 0}
    ]
