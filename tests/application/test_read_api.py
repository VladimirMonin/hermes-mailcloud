"""Real application -> config -> read service/policy/parser -> synthetic external edge."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from tests.helpers.application import RecordingBackend, synthetic_environment
from tests.helpers.cli_fake import CliFakeHarness

from hermes_mailcloud.application import CallOptions, MailCloudApplication, composition
from hermes_mailcloud.core.errors import ErrorKind, ErrorPayload, MailCloudError
from hermes_mailcloud.rclone.runner import RcloneResult, RcloneRunner

ITEM = {"Path": "a ü &;$%.txt", "Name": "a ü &;$%.txt", "IsDir": False, "Size": 0}


def test_ls_keeps_real_policy_parser_flags_and_nonempty_metadata(tmp_path: Path, capsys) -> None:
    backend = RecordingBackend(RcloneResult(0, json.dumps([ITEM]), "", 0))
    app = MailCloudApplication(
        environment=synthetic_environment(tmp_path), backend_factory=lambda config, **kw: backend
    )
    result = app.ls(
        "/Hermes//private/.",
        recursive=True,
        files_only=True,
        options=CallOptions(timeout_seconds=7, retries=0),
    )
    assert result.ok and result.operation == "ls"
    assert result.result == {
        "remote_path": "/Hermes/private",
        "items": [
            {
                "path": "/Hermes/private/a ü &;$%.txt",
                "name": ITEM["Name"],
                "type": "file",
                "size": 0,
            }
        ],
    }
    assert backend.calls == [(["lsjson", "fake:/Hermes/private", "--recursive", "--files-only"], 7)]
    assert capsys.readouterr() == ("", "")


@pytest.mark.parametrize("hashes", [None, {"MD5": "0123456789abcdef0123456789abcdef"}])
def test_file_stat_preserves_optional_validated_hashes(tmp_path: Path, hashes) -> None:
    metadata = dict(ITEM)
    if hashes is not None:
        metadata["Hashes"] = hashes
    backend = RecordingBackend(RcloneResult(0, json.dumps(metadata), "", 0))
    result = MailCloudApplication(
        environment=synthetic_environment(tmp_path), backend_factory=lambda config, **kw: backend
    ).stat("/Hermes/a.txt")
    assert result.ok and result.result["remote_path"] == "/Hermes/a.txt"
    assert result.result["type"] == "file" and result.result["size"] == 0
    assert result.result.get("hashes") == hashes
    assert backend.calls == [(["lsjson", "fake:/Hermes/a.txt", "--stat", "--hash"], 60)]


def test_directory_stat_keeps_requested_normalized_path(tmp_path: Path) -> None:
    backend = RecordingBackend(
        RcloneResult(0, '{"Path":"","Name":"","IsDir":true,"Size":-1}', "", 0)
    )
    result = MailCloudApplication(
        environment=synthetic_environment(tmp_path), backend_factory=lambda config, **kw: backend
    ).stat("/TEST//directory/.")
    assert result.ok
    assert result.result["remote_path"] == "/TEST/directory"
    assert result.result["type"] == "directory"


@pytest.mark.parametrize(
    "arguments",
    [
        {"remote_path": 1},
        {"remote_path": None},
        {"remote_path": Path("/Hermes")},
        {"remote_path": "/Hermes", "recursive": 1},
        {"remote_path": "/Hermes", "files_only": "false"},
        {"remote_path": "/Hermes", "dirs_only": 0},
    ],
)
def test_operation_types_refuse_before_loader(arguments) -> None:
    def forbidden(*_args, **_kwargs):
        pytest.fail("invalid operation type reached configuration")

    result = MailCloudApplication(environment={}, config_loader=forbidden).ls(**arguments)
    assert result.error.kind is ErrorKind.INVALID_ARGUMENTS and result.exit_code == 2


@pytest.mark.parametrize("path", ["", "relative", "//Hermes/ambiguous-root", "/Hermes/\x00"])
def test_bad_remote_paths_refuse_before_execution(tmp_path: Path, path: str) -> None:
    backend = RecordingBackend()
    result = MailCloudApplication(
        environment=synthetic_environment(tmp_path), backend_factory=lambda config, **kw: backend
    ).stat(path)
    assert result.error.kind is ErrorKind.INVALID_ARGUMENTS and result.exit_code == 2
    assert backend.calls == []


def test_standalone_read_dry_run_retains_read_only_execution(tmp_path: Path) -> None:
    backend = RecordingBackend(RcloneResult(0, "[]", "", 0))
    result = MailCloudApplication(
        environment=synthetic_environment(tmp_path), backend_factory=lambda config, **kw: backend
    ).ls("/Hermes", dirs_only=True, options=CallOptions(dry_run=True, yes=False))
    assert result.ok and result.result["items"] == []
    assert backend.calls == [(["lsjson", "fake:/Hermes", "--dirs-only"], 60)]


def test_files_dirs_conflict_remains_with_real_service(tmp_path: Path) -> None:
    backend = RecordingBackend()
    result = MailCloudApplication(
        environment=synthetic_environment(tmp_path), backend_factory=lambda config, **kw: backend
    ).ls("/Hermes", files_only=True, dirs_only=True)
    assert result.error.kind is ErrorKind.INVALID_ARGUMENTS
    assert "--files-only" in result.error.message and backend.calls == []


@pytest.mark.parametrize("transient", ["network is unreachable", "i/o timeout"])
def test_profile_read_retries_recover_through_real_runner_error_mapping(
    tmp_path: Path, transient: str
) -> None:
    environment = synthetic_environment(
        tmp_path, '[profiles.default]\nremote="fake:"\nretries=1\ntimeout_seconds=9\n'
    )
    backend = RecordingBackend(RcloneResult(1, "", transient, 0), RcloneResult(0, "[]", "", 0))
    result = MailCloudApplication(
        environment=environment, backend_factory=lambda config, **kw: backend
    ).ls("/Hermes")
    assert result.ok and result.result["items"] == []
    assert backend.calls == [(["lsjson", "fake:/Hermes"], 9)] * 2


@pytest.mark.parametrize(
    ("retries", "kind", "code", "attempts"),
    [(0, ErrorKind.NETWORK_ERROR, 10, 1), (2, ErrorKind.RETRY_EXHAUSTED, 10, 3)],
)
def test_retry_exhaustion_and_explicit_zero_preserve_frozen_semantics(
    tmp_path: Path, retries, kind, code, attempts
) -> None:
    environment = synthetic_environment(tmp_path, '[profiles.default]\nremote="fake:"\nretries=5\n')
    backend = RecordingBackend(
        *[RcloneResult(1, "raw-provider-private", "network is unreachable", 0)] * attempts
    )
    result = MailCloudApplication(
        environment=environment, backend_factory=lambda config, **kw: backend
    ).ls("/Hermes", options=CallOptions(retries=retries))
    assert result.error.kind is kind and result.exit_code == code
    assert len(backend.calls) == attempts
    if attempts > 1:
        assert result.error.details["attempts"] == attempts
    assert "raw-provider-private" not in repr(result)


def test_nontransient_backend_error_is_never_retried_or_exposed(tmp_path: Path) -> None:
    raw = "raw-provider-private https://cloud.mail.ru/public/read-error-capability/path"
    backend = RecordingBackend(RcloneResult(1, raw, "permission denied " + raw, 0))
    result = MailCloudApplication(
        environment=synthetic_environment(tmp_path), backend_factory=lambda config, **kw: backend
    ).stat("/Hermes/a.txt", options=CallOptions(retries=3))
    assert result.error.kind is ErrorKind.ACCESS_DENIED and result.exit_code == 6
    assert len(backend.calls) == 1
    assert "raw-provider-private" not in repr(result) and "https://" not in repr(result)


@pytest.mark.parametrize(
    "stdout", ["not-json private-parse-sentinel", "{}", '[{"Path":"","Name":"","IsDir":true}]']
)
def test_real_parser_failure_is_safe(tmp_path: Path, stdout: str) -> None:
    backend = RecordingBackend(RcloneResult(0, stdout, "raw-stderr", 0))
    result = MailCloudApplication(
        environment=synthetic_environment(tmp_path), backend_factory=lambda config, **kw: backend
    ).ls("/Hermes")
    assert result.error.kind is ErrorKind.PARSE_ERROR and result.exit_code == 13
    assert "private-parse-sentinel" not in repr(result) and "raw-stderr" not in repr(result)


def test_safe_direct_results_precede_serialization_and_do_not_alias_provider_data(
    tmp_path: Path,
) -> None:
    name = "token=direct-read-sentinel"
    raw = json.dumps([{"Path": name, "Name": name, "IsDir": False, "Size": 0}])
    error = ErrorPayload(
        ErrorKind.NOT_FOUND,
        "password=typed-message-sentinel",
        {"token": "typed-detail-sentinel", "attempts": 0},
    )
    backend = RecordingBackend(RcloneResult(0, raw, "", 0), MailCloudError(error))
    app = MailCloudApplication(
        environment=synthetic_environment(tmp_path), backend_factory=lambda config, **kw: backend
    )
    success = app.ls("/Hermes", options=CallOptions(trace_id="token=trace-sentinel"))
    failure = app.stat("/Hermes/a.txt")
    assert success.ok and success.result["items"][0]["size"] == 0
    assert failure.error.kind is ErrorKind.NOT_FOUND and failure.exit_code == 7
    assert failure.error.details == {"token": "[REDACTED]", "attempts": 0}
    for sentinel in (name, "typed-message-sentinel", "typed-detail-sentinel", "trace-sentinel"):
        assert sentinel not in repr(success) + repr(failure)
    assert error.details["token"] == "typed-detail-sentinel"


@pytest.mark.parametrize("stage", ["loader", "factory", "execution"])
def test_unexpected_errors_are_fixed_safe_unknowns(tmp_path: Path, stage: str, capsys) -> None:
    environment = synthetic_environment(tmp_path)

    def broken(*_args, **_kwargs):
        raise RuntimeError(
            "unexpected-private-sentinel https://cloud.mail.ru/public/unexpected/path"
        )

    backend = RecordingBackend(RuntimeError("unexpected-private-sentinel"))
    app = MailCloudApplication(
        environment=environment,
        config_loader=broken if stage == "loader" else None,
        backend_factory=broken if stage == "factory" else lambda config, **kw: backend,
    )
    result = app.ls("/Hermes")
    assert result.error.kind is ErrorKind.UNKNOWN_ERROR and result.exit_code == 1
    assert (
        result.error.message
        == "unexpected application failure; operation effects may be incomplete"
    )
    assert result.error.details == {}
    assert "unexpected-private-sentinel" not in repr(result) and "https://" not in repr(result)
    assert capsys.readouterr() == ("", "")


@pytest.mark.parametrize("error", [KeyboardInterrupt(), SystemExit(17)])
def test_base_exceptions_are_not_swallowed(tmp_path: Path, error: BaseException) -> None:
    backend = RecordingBackend(error)
    app = MailCloudApplication(
        environment=synthetic_environment(tmp_path), backend_factory=lambda config, **kw: backend
    )
    with pytest.raises(type(error)):
        app.ls("/Hermes")


def test_next_call_after_failure_has_a_fresh_backend_and_options(tmp_path: Path) -> None:
    built = []
    responses = [RuntimeError("private"), RcloneResult(0, "[]", "", 0)]

    def factory(config, *, environment):
        backend = RecordingBackend(responses[len(built)])
        built.append(backend)
        return backend

    app = MailCloudApplication(environment=synthetic_environment(tmp_path), backend_factory=factory)
    assert (
        app.stat(
            "/Hermes/first", options=CallOptions(timeout_seconds=3, retries=0, trace_id="first")
        ).exit_code
        == 1
    )
    result = app.ls("/Hermes/second")
    assert result.ok and result.trace_id is None
    assert len(built) == 2 and built[0] is not built[1]
    assert built[1].calls == [(["lsjson", "fake:/Hermes/second"], 60)]


@pytest.mark.parametrize(
    ("operation", "response", "code"),
    [
        ("ls", {"stdout": json.dumps([ITEM])}, 0),
        ("stat", {"stdout": json.dumps(ITEM)}, 0),
        ("ls", {"returncode": 1, "stderr": "network is unreachable private-edge-sentinel"}, 10),
        ("stat", {"stdout": "malformed private-edge-sentinel"}, 13),
    ],
)
@pytest.mark.parametrize(
    "trace_id",
    [
        "parity",
        "token=parity-private-sentinel",
        "token=[REDACTED]parity-private-sentinel",
        "surrounding [REDACTED] token=parity-private-sentinel",
    ],
)
def test_direct_real_runner_and_cli_payload_schema_exit_parity(
    tmp_path: Path, operation, response, code, trace_id: str
) -> None:
    harness = CliFakeHarness.create(tmp_path)
    cli = harness.run(
        operation, "/Hermes", "--json", "--trace-id", trace_id, responses={"lsjson": response}
    )
    environment = synthetic_environment(tmp_path)
    app = MailCloudApplication(
        environment=environment,
        backend_factory=lambda config, *, environment: RcloneRunner(
            (sys.executable, str(harness.script)), environment=environment
        ),
    )
    direct = getattr(app, operation)("/Hermes", options=CallOptions(trace_id=trace_id))
    assert cli.returncode == direct.exit_code == code
    assert cli.stderr == ""
    assert json.loads(cli.stdout) == direct.to_payload()
    schema = json.loads(
        (Path(__file__).resolve().parents[2] / "schemas/result-envelope.schema.json").read_text(
            encoding="utf-8"
        )
    )
    Draft202012Validator(schema).validate(json.loads(cli.stdout))
    assert len(harness.recorded_calls()) == 2
    assert "private-edge-sentinel" not in cli.stdout + repr(direct)
    assert "parity-private-sentinel" not in cli.stdout + repr(direct)


@pytest.mark.parametrize("operation", ["version", "ls", "stat"])
def test_cli_calls_the_actual_application_owner(
    tmp_path: Path, monkeypatch, operation: str
) -> None:
    from typer.testing import CliRunner

    import hermes_mailcloud.cli as cli

    environment = synthetic_environment(tmp_path)
    for key, value in environment.items():
        monkeypatch.setenv(key, value)
    backend = RecordingBackend(
        RcloneResult(0, json.dumps(ITEM if operation == "stat" else [ITEM]), "", 0)
    )
    monkeypatch.setattr(composition, "create_backend", lambda config, **kw: backend)
    reached = []
    original = getattr(MailCloudApplication, operation)

    def observed(self, *args, **kwargs):
        reached.append(operation)
        return original(self, *args, **kwargs)

    monkeypatch.setattr(MailCloudApplication, operation, observed)
    arguments = ["--json", operation, *([] if operation == "version" else ["/Hermes"])]
    result = CliRunner().invoke(cli.app, arguments)
    assert result.exit_code == 0, result.output
    assert reached == [operation]
    assert json.loads(result.stdout)["ok"] is True
    assert len(backend.calls) == (0 if operation == "version" else 1)
