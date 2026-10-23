"""File calls reach real config/services/policy/runner; only external execution is fake."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from tests.helpers.application import RecordingBackend, synthetic_environment
from tests.helpers.cli_fake import CliFakeHarness

from hermes_mailcloud.application import CallOptions, MailCloudApplication, composition
from hermes_mailcloud.core.errors import ErrorKind, ErrorPayload
from hermes_mailcloud.rclone.runner import RcloneResult, RcloneRunner, RcloneRunnerError

WRITES = ("mkdir", "upload", "download", "mv", "cp", "rm", "publish", "link")
SUCCESS = RcloneResult(0, "", "", 0)
BYTES = b"synthetic-download\x00\xff\r\n"


def _arguments(operation: str, source: Path, destination: Path) -> tuple[str, ...]:
    return {
        "mkdir": ("/TEST/api/dir",),
        "upload": (str(source), "/TEST/api/file.txt"),
        "download": ("/TEST/api/file.txt", str(destination)),
        "mv": ("/TEST/api/file.txt", "/TEST/api/moved.txt"),
        "cp": ("/TEST/api/file.txt", "/TEST/api/copied.txt"),
        "rm": ("/TEST/api/file.txt",),
        "publish": (str(source), "/Hermes/public/file.txt"),
        "link": ("/Hermes/public/file.txt",),
    }[operation]


def _download(args) -> RcloneResult:
    Path(args[2]).write_bytes(BYTES)
    return SUCCESS


@pytest.mark.parametrize("operation", WRITES)
@pytest.mark.parametrize(
    "options",
    [
        {"yes": True},
        CallOptions(yes="false"),
        CallOptions(dry_run=1),
        CallOptions(retries=True),
        CallOptions(timeout_seconds=float("nan")),
        CallOptions(config={"remote": "fake:"}),
    ],
)
def test_invalid_write_options_refuse_before_config_or_backend(operation, options) -> None:
    reached = []

    def forbidden(*args, **kwargs):
        reached.append("effect")
        raise AssertionError("invalid input reached configuration/backend")

    app = MailCloudApplication(environment={}, config_loader=forbidden, backend_factory=forbidden)
    result = getattr(app, operation)(
        *_arguments(operation, Path("source"), Path("dest")), options=options
    )
    assert not result.ok and result.exit_code == 2
    assert result.error.kind is ErrorKind.INVALID_ARGUMENTS
    assert reached == []


@pytest.mark.parametrize(
    "operation,args,kwargs,field",
    [
        ("mkdir", (None,), {}, "remote_path"),
        ("upload", (Path("file"), "/TEST/api/f"), {}, "local_path"),
        ("upload", ("file", 1), {}, "remote_path"),
        ("download", (1, "file"), {}, "remote_path"),
        ("download", ("/TEST/api/f", Path("file")), {}, "local_path"),
        ("mv", (False, "/TEST/api/f"), {}, "source_path"),
        ("mv", ("/TEST/api/f", []), {}, "target_path"),
        ("cp", (None, "/TEST/api/f"), {}, "source_path"),
        ("cp", ("/TEST/api/f", 2), {}, "target_path"),
        ("rm", ("/TEST/api/f",), {"recursive": "false"}, "recursive"),
        ("rm", ("/TEST/api/f",), {"recursive": 0}, "recursive"),
        ("rm", (None,), {}, "remote_path"),
        ("publish", (Path("file"), "/Hermes/public/f"), {}, "local_path"),
        ("publish", ("file", {}), {}, "remote_path"),
        ("link", (False,), {}, "remote_path"),
    ],
)
def test_operation_types_are_checked_before_loader(operation, args, kwargs, field) -> None:
    reached = []

    def forbidden(*args, **kwargs):
        reached.append(True)
        raise AssertionError("loader must not run")

    result = getattr(MailCloudApplication(config_loader=forbidden), operation)(*args, **kwargs)
    assert result.exit_code == 2 and result.error.details == {"field": field}
    assert reached == []


@pytest.mark.parametrize("operation", ("upload", "download", "mv", "cp", "publish"))
@pytest.mark.parametrize("overwrite", [True, 0, [], {}, "ALWAYS", "", "sometimes"])
def test_overwrite_choice_is_a_strict_runtime_contract(operation, overwrite) -> None:
    reached = []

    def forbidden(*args, **kwargs):
        reached.append(True)
        raise AssertionError("loader must not run")

    result = getattr(MailCloudApplication(config_loader=forbidden), operation)(
        *_arguments(operation, Path("source"), Path("dest")), overwrite=overwrite
    )
    assert result.exit_code == 2 and result.error.details == {"field": "overwrite"}
    assert reached == []


@pytest.mark.parametrize("operation", WRITES)
@pytest.mark.parametrize("dry_run", [False, True])
def test_explicit_write_retry_budget_is_rejected_before_any_execution(
    tmp_path, operation, dry_run
) -> None:
    source = tmp_path / "input.txt"
    source.write_bytes(b"private fixture")
    backend = RecordingBackend()
    environment = synthetic_environment(tmp_path, '[profiles.default]\nremote="fake:"\nretries=4\n')
    app = MailCloudApplication(environment=environment, backend_factory=lambda *a, **kw: backend)
    result = getattr(app, operation)(
        *_arguments(operation, source, tmp_path / "download.txt"),
        options=CallOptions(yes=True, dry_run=dry_run, retries=1),
    )
    assert result.exit_code == 2 and result.error.kind is ErrorKind.INVALID_ARGUMENTS
    assert backend.calls == []
    assert not Path(environment["HMC_LINKS_JOURNAL"]).parent.exists()
    assert not (tmp_path / "download.txt").exists()


@pytest.mark.parametrize("operation", ("mkdir", "upload", "download", "mv", "cp", "rm"))
def test_real_file_owner_uses_profile_timeout_but_not_profile_read_retries(
    tmp_path, operation
) -> None:
    source, destination = tmp_path / "input.txt", tmp_path / "output.txt"
    source.write_bytes(b"upload bytes")
    backend = RecordingBackend(_download if operation == "download" else SUCCESS)
    app = MailCloudApplication(
        environment=synthetic_environment(
            tmp_path,
            '[profiles.default]\nremote="fake:"\nretries=4\ntimeout_seconds=17\ndefault_overwrite="if-newer"\n',
        ),
        backend_factory=lambda *a, **kw: backend,
    )
    result = getattr(app, operation)(
        *_arguments(operation, source, destination), options=CallOptions(yes=True)
    )
    assert result.ok and result.operation == operation and result.profile == "default"
    assert result.remote == "fake:" and len(backend.calls) == 1
    argv, timeout = backend.calls[0]
    assert timeout == 17
    assert (
        argv[0]
        == {
            "mkdir": "mkdir",
            "upload": "copyto",
            "download": "copyto",
            "mv": "moveto",
            "cp": "copyto",
            "rm": "deletefile",
        }[operation]
    )
    if operation == "download":
        assert destination.read_bytes() == BYTES
        assert result.result["bytes"] == len(BYTES) and result.result["updated"] is True
        assert not Path(argv[2]).exists()
    if operation in {"upload", "download", "mv", "cp"}:
        assert result.result["overwrite"] == "if-newer"
    if operation in {"upload", "mv", "cp"}:
        assert argv[-1] == "--update"
    if operation == "upload":
        assert result.result["published"] is False and result.result["bytes"] == 12
    assert source.read_bytes() == b"upload bytes"


@pytest.mark.parametrize("operation", WRITES)
def test_write_dry_run_has_a_meaningful_plan_and_no_backend_temp_or_journal_effect(
    tmp_path, operation
) -> None:
    source, destination = tmp_path / "input.txt", tmp_path / "output.txt"
    source.write_bytes(b"dry-run input")
    environment = synthetic_environment(tmp_path)
    before = {
        p.relative_to(tmp_path): p.read_bytes() if p.is_file() else None
        for p in tmp_path.rglob("*")
    }
    backend = RecordingBackend()
    app = MailCloudApplication(environment=environment, backend_factory=lambda *a, **kw: backend)
    result = getattr(app, operation)(
        *_arguments(operation, source, destination), options=CallOptions(dry_run=True)
    )
    assert result.ok and result.result["dry_run"] is True and result.result["plan"]
    assert all(step["status"] == "planned" for step in result.result["plan"])
    assert backend.calls == []
    assert {
        p.relative_to(tmp_path): p.read_bytes() if p.is_file() else None
        for p in tmp_path.rglob("*")
    } == before


@pytest.mark.parametrize("operation", WRITES)
@pytest.mark.parametrize("kind", [ErrorKind.NETWORK_ERROR, ErrorKind.TIMEOUT])
def test_transient_failure_is_one_attempt_and_a_fresh_call_does_not_inherit_failure(
    tmp_path, operation, kind
) -> None:
    source, destination = tmp_path / "input.txt", tmp_path / "output.txt"
    source.write_bytes(b"fixture")
    failing = RecordingBackend(
        RcloneResult(
            1, "private-provider-stream", "i/o timeout access_token=private-timeout-sentinel", 0
        )
        if kind is ErrorKind.NETWORK_ERROR
        else RcloneRunnerError(ErrorPayload(ErrorKind.TIMEOUT, "rclone command timed out"))
    )
    recovery_response = (
        _download
        if operation == "download"
        else RcloneResult(0, "https://cloud.mail.ru/public/api-fixture/capability\n", "", 0)
    )
    recovering = RecordingBackend(
        *([SUCCESS, recovery_response] if operation == "publish" else [recovery_response])
    )
    runners = iter((failing, recovering))
    app = MailCloudApplication(
        environment=synthetic_environment(tmp_path), backend_factory=lambda *a, **kw: next(runners)
    )
    args = _arguments(operation, source, destination)
    failed = getattr(app, operation)(
        *args, options=CallOptions(yes=True, timeout_seconds=3, trace_id="first")
    )
    assert not failed.ok and failed.error.kind is kind
    assert len(failing.calls) == 1 and failing.calls[0][1] == 3
    assert "private-provider-stream" not in repr(failed) + failed.to_json()
    assert "private-timeout-sentinel" not in repr(failed) + failed.to_json()
    recovered = getattr(app, operation)(*args, options=CallOptions(yes=True))
    assert recovered.ok and recovered.trace_id is None
    assert len(recovering.calls) == (2 if operation == "publish" else 1)
    assert all(timeout == 60 for _, timeout in recovering.calls)
    assert failed.trace_id == "first" and failed.ok is False


@pytest.mark.parametrize(
    "mode", ["never", "partial-timeout", "concurrent-never", "newer", "older", "always"]
)
def test_download_preserves_real_targets_and_cleans_only_its_temporary(tmp_path, mode) -> None:
    destination, neighbor = tmp_path / "download.bin", tmp_path / "neighbor.bin"
    neighbor.write_bytes(b"untouched neighbor")
    if mode != "concurrent-never":
        destination.write_bytes(b"original target")
        os.utime(destination, (1700000000, 1700000000))
    temporary_paths = []

    def execute(args):
        temporary = Path(args[2])
        temporary_paths.append(temporary)
        assert temporary.parent == destination.parent and temporary != destination
        temporary.write_bytes(BYTES)
        os.utime(temporary, (1700000030 if mode == "newer" else 1699999970,) * 2)
        if mode == "partial-timeout":
            raise RcloneRunnerError(ErrorPayload(ErrorKind.TIMEOUT, "rclone command timed out"))
        if mode == "concurrent-never":
            destination.write_bytes(b"concurrent winner")
        return SUCCESS

    backend = RecordingBackend(execute)
    app = MailCloudApplication(
        environment=synthetic_environment(tmp_path), backend_factory=lambda *a, **kw: backend
    )
    overwrite = {
        "never": "never",
        "partial-timeout": "always",
        "concurrent-never": "never",
        "newer": "if-newer",
        "older": "if-newer",
        "always": "always",
    }[mode]
    result = app.download("/TEST/api/file.bin", str(destination), overwrite=overwrite)
    expected = (
        BYTES
        if mode in {"newer", "always"}
        else b"concurrent winner"
        if mode == "concurrent-never"
        else b"original target"
    )
    assert destination.read_bytes() == expected and neighbor.read_bytes() == b"untouched neighbor"
    assert all(not path.exists() for path in temporary_paths)
    assert len(backend.calls) == (0 if mode == "never" else 1)
    if mode in {"never", "concurrent-never"}:
        assert result.error.kind is ErrorKind.CONFLICT
    elif mode == "partial-timeout":
        assert result.error.kind is ErrorKind.TIMEOUT
    else:
        assert result.ok and result.result["updated"] is (mode != "older")
        assert result.result["bytes"] == len(expected)


@pytest.mark.parametrize(
    "path", ["/", "/TEST", "/Hermes", "/Hermes/public", "/Hermes/private", "/Hermes/.tmp"]
)
@pytest.mark.parametrize("recursive", [False, True])
def test_protected_removal_still_refuses_even_with_confirmation(tmp_path, path, recursive) -> None:
    backend = RecordingBackend()
    app = MailCloudApplication(
        environment=synthetic_environment(tmp_path), backend_factory=lambda *a, **kw: backend
    )
    result = app.rm(path, recursive=recursive, options=CallOptions(yes=True))
    assert result.error.kind is ErrorKind.INVALID_ARGUMENTS and backend.calls == []


@pytest.mark.parametrize("operation", WRITES)
@pytest.mark.parametrize("refused", [False, True])
def test_direct_and_subprocess_cli_share_payload_schema_exit_and_real_owners(
    tmp_path, operation, refused
) -> None:
    harness = CliFakeHarness.create(tmp_path)
    source, destination = tmp_path / "input.txt", tmp_path / "output.txt"
    source.write_bytes(b"parity input")
    args = list(_arguments(operation, source, destination))
    if refused:
        index = 1 if operation in {"upload", "publish"} else 0
        args[index] = "relative/path"
    kwargs = (
        {"overwrite": "always"}
        if operation in {"upload", "download", "mv", "cp", "publish"}
        else {}
    )
    cli_args = [operation, *args, "--json", "--yes", "--trace-id", "file-parity"]
    if kwargs:
        cli_args += ["--overwrite", "always"]
    cli = harness.run(*cli_args, responses={"copyto": {"download_text": "parity downloaded bytes"}})
    app = MailCloudApplication(
        environment=synthetic_environment(tmp_path),
        backend_factory=lambda config, *, environment: RcloneRunner(
            (sys.executable, str(harness.script)), environment=environment
        ),
    )
    direct = getattr(app, operation)(
        *args, **kwargs, options=CallOptions(yes=True, trace_id="file-parity")
    )
    assert direct.exit_code == cli.returncode == (2 if refused else 0), cli.stderr + cli.stdout
    assert cli.stderr == "" and json.loads(cli.stdout) == direct.to_payload()
    schema = json.loads(
        (Path(__file__).resolve().parents[2] / "schemas/result-envelope.schema.json").read_text(
            encoding="utf-8"
        )
    )
    Draft202012Validator(schema).validate(json.loads(cli.stdout))
    assert len(harness.recorded_calls()) == (0 if refused else 4 if operation == "publish" else 2)
    if operation == "download" and not refused:
        assert destination.read_bytes() == b"parity downloaded bytes"
    if operation in {"publish", "link"} and not refused:
        assert direct.result["public_url_fingerprint"].startswith("sha256:")
        # The two consumers deliberately have distinct disposable journal locators.
        for journal in (Path(app._environment["HMC_LINKS_JOURNAL"]), harness.journal):
            records = [
                json.loads(line) for line in journal.read_text(encoding="utf-8").splitlines()
            ]
            assert len(records) == 1 and records[0]["operation"] == operation
            assert records[0]["public_url_fingerprint"] == direct.result["public_url_fingerprint"]
            assert records[0]["remote_path"] == "/Hermes/public/file.txt"


@pytest.mark.parametrize("operation", WRITES)
def test_each_cli_handler_reaches_the_actual_application_not_a_canned_response(
    tmp_path, monkeypatch, operation
) -> None:
    from typer.testing import CliRunner

    import hermes_mailcloud.cli as cli

    source, destination = tmp_path / "input.txt", tmp_path / "output.txt"
    source.write_bytes(b"observed input")
    for key, value in synthetic_environment(tmp_path).items():
        monkeypatch.setenv(key, value)
    backend = RecordingBackend(
        *(
            [SUCCESS, RcloneResult(0, "https://cloud.mail.ru/public/observer/capability\n", "", 0)]
            if operation == "publish"
            else [
                _download
                if operation == "download"
                else RcloneResult(0, "https://cloud.mail.ru/public/observer/capability\n", "", 0)
            ]
        )
    )
    monkeypatch.setattr(composition, "create_backend", lambda *a, **kw: backend)
    original, reached = getattr(MailCloudApplication, operation), []

    def observed(self, *args, **kwargs):
        reached.append(operation)
        return original(self, *args, **kwargs)

    monkeypatch.setattr(MailCloudApplication, operation, observed)
    result = CliRunner().invoke(
        cli.app, ["--json", "--yes", operation, *_arguments(operation, source, destination)]
    )
    assert result.exit_code == 0, result.output
    assert reached == [operation] and json.loads(result.stdout)["operation"] == operation
    assert len(backend.calls) == (2 if operation == "publish" else 1)
    if operation == "download":
        assert destination.read_bytes() == BYTES
