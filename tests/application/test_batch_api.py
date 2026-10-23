"""Both JSON inputs share the real batch parser/preflight/execution and safe outcome."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from tests.helpers.application import RecordingBackend, synthetic_environment
from tests.helpers.cli_fake import CliFakeHarness

from hermes_mailcloud.application import CallOptions, MailCloudApplication, composition
from hermes_mailcloud.batch import parse_batch_document
from hermes_mailcloud.rclone.runner import RcloneResult, RcloneRunner

SUCCESS = RcloneResult(0, "", "", 0)
PUBLIC_URL = "https://cloud.mail.ru/public/s3-batch-synthetic/capability"
ITEM = {"Path": "file.txt", "Name": "file.txt", "IsDir": False, "Size": 0}
BYTES = b"batch-download\x00\xff\n"


def _document(source, destination):
    return {
        "version": 1,
        "operations": [
            {"op": "ls", "remote_path": "/TEST/batch"},
            {"op": "stat", "remote_path": "/TEST/batch/file.txt"},
            {"op": "mkdir", "remote_path": "/TEST/batch/directory"},
            {"op": "upload", "local_path": str(source), "remote_path": "/TEST/batch/upload.txt"},
            {
                "op": "download",
                "remote_path": "/TEST/batch/file.txt",
                "local_path": str(destination),
            },
            {
                "op": "mv",
                "src_remote_path": "/TEST/batch/a.txt",
                "dst_remote_path": "/TEST/batch/moved.txt",
            },
            {
                "op": "cp",
                "src_remote_path": "/TEST/batch/a.txt",
                "dst_remote_path": "/TEST/batch/copied.txt",
            },
            {"op": "rm", "remote_path": "/TEST/batch/deleted.txt"},
            {
                "op": "publish",
                "local_path": str(source),
                "remote_path": "/Hermes/public/report.txt",
            },
            {"op": "link", "remote_path": "/Hermes/public/report.txt"},
        ],
    }


def _call(app, entry, document, path, options):
    if entry == "batch_file":
        path.write_text(json.dumps(document), encoding="utf-8")
        return app.batch_file(path, options=options)
    return app.batch(document, options=options)


@pytest.mark.parametrize("entry", ["batch", "batch_file"])
def test_both_entries_run_every_real_owner_with_one_config_and_resource_readbacks(
    tmp_path, entry
) -> None:
    source, destination, plan = (
        tmp_path / "input.txt",
        tmp_path / "output.bin",
        tmp_path / "plan.json",
    )
    source.write_bytes(b"batch source")
    environment = synthetic_environment(
        tmp_path, '[profiles.default]\nremote="fake:"\nretries=3\ndefault_overwrite="always"\n'
    )

    def download(args):
        Path(args[2]).write_bytes(BYTES)
        return SUCCESS

    backend = RecordingBackend(
        RcloneResult(0, json.dumps([ITEM]), "", 0),
        RcloneResult(0, json.dumps(ITEM), "", 0),
        SUCCESS,
        SUCCESS,
        download,
        SUCCESS,
        SUCCESS,
        SUCCESS,
        SUCCESS,
        RcloneResult(0, PUBLIC_URL + "\n", "", 0),
        RcloneResult(0, PUBLIC_URL + "\n", "", 0),
    )
    loads, factories = [], []

    def load(overrides, *, environment):
        loads.append(environment)
        return composition.load_config(overrides, environment=environment)

    def factory(config, *, environment):
        factories.append(environment)
        return backend

    app = MailCloudApplication(environment=environment, config_loader=load, backend_factory=factory)
    document = _document(source, destination)
    result = _call(app, entry, document, plan, CallOptions(yes=True, timeout_seconds=11))
    assert result.ok and result.operation == "batch" and result.error is None
    assert len(loads) == len(factories) == 1 and loads[0] is factories[0]
    assert (
        result.result["total"] == result.result["succeeded"] == 10 and result.result["failed"] == 0
    )
    assert [item["operation"] for item in result.result["items"]] == [
        item["op"] for item in document["operations"]
    ]
    assert [item["index"] for item in result.result["items"]] == list(range(10))
    assert result.result["items"][0]["result"]["items"][0]["size"] == 0
    assert destination.read_bytes() == BYTES and source.read_bytes() == b"batch source"
    assert len(backend.calls) == 11 and all(timeout == 11 for _, timeout in backend.calls)
    assert not Path(backend.calls[4][0][2]).exists()
    for item in result.result["items"]:
        if item["operation"] in {"upload", "download", "mv", "cp", "publish"}:
            assert item["result"]["overwrite"] == "never", "batch default is not profile overwrite"
    journal = Path(environment["HMC_LINKS_JOURNAL"])
    records = [json.loads(line) for line in journal.read_text(encoding="utf-8").splitlines()]
    assert [record["operation"] for record in records] == ["publish", "link"]
    assert all(record["public_url"] == PUBLIC_URL for record in records)
    assert PUBLIC_URL not in repr(result) + result.to_json()


@pytest.mark.parametrize("entry", ["batch", "batch_file"])
def test_all_item_dry_run_validates_and_preserves_backend_journal_and_local_targets(
    tmp_path, entry
) -> None:
    source, destination, path = (
        tmp_path / "input.txt",
        tmp_path / "output.bin",
        tmp_path / "plan.json",
    )
    source.write_bytes(b"dry input")
    document = _document(source, destination)
    path.write_text(json.dumps(document), encoding="utf-8")
    environment = synthetic_environment(tmp_path)
    before = {
        p.relative_to(tmp_path): p.read_bytes() if p.is_file() else None
        for p in tmp_path.rglob("*")
    }
    backend = RecordingBackend()
    app = MailCloudApplication(environment=environment, backend_factory=lambda *a, **kw: backend)
    result = _call(app, entry, document, path, CallOptions(dry_run=True))
    assert result.ok and result.result["total"] == 10
    assert all(
        item["result"]["dry_run"] is True and item["result"]["plan"]
        for item in result.result["items"]
    )
    assert backend.calls == []
    assert {
        p.relative_to(tmp_path): p.read_bytes() if p.is_file() else None
        for p in tmp_path.rglob("*")
    } == before


@pytest.mark.parametrize(
    "document",
    [
        None,
        [],
        {"version": True, "operations": []},
        {"version": 1, "defaults": None, "operations": [{"op": "mkdir", "remote_path": "/TEST/a"}]},
        {"version": 1, "operations": [{"op": "mkdir", "remote_path": "/TEST/a"}, {"op": "unlink"}]},
        parse_batch_document({"version": 1, "operations": [{"op": "ls", "remote_path": "/TEST"}]}),
    ],
)
def test_invalid_document_or_trusted_plan_refuses_before_config(document) -> None:
    reached = []

    def forbidden(*a, **kw):
        reached.append(True)
        raise AssertionError("parser must run before config")

    result = MailCloudApplication(environment={}, config_loader=forbidden).batch(document)
    assert result.exit_code == 2 and reached == []


@pytest.mark.parametrize("value", [None, "plan.json", True, 1])
def test_file_entry_requires_path_before_filesystem_or_config(value) -> None:
    reached = []

    def forbidden(*a, **kw):
        reached.append(True)
        raise AssertionError("invalid path reached config")

    result = MailCloudApplication(environment={}, config_loader=forbidden).batch_file(value)
    assert result.exit_code == 2 and result.operation == "batch" and reached == []


@pytest.mark.parametrize("entry", ["batch", "batch_file"])
@pytest.mark.parametrize(
    "options",
    [
        CallOptions(yes=1),
        CallOptions(dry_run="false"),
        CallOptions(retries=True),
        CallOptions(timeout_seconds=0),
        {},
    ],
)
def test_batch_options_refuse_before_parsing_or_loader(tmp_path, entry, options) -> None:
    reached = []

    def forbidden(*a, **kw):
        reached.append(True)
        raise AssertionError("invalid options reached config")

    app = MailCloudApplication(environment={}, config_loader=forbidden)
    result = (
        app.batch(None, options=options)
        if entry == "batch"
        else app.batch_file(tmp_path / "unreadable.json", options=options)
    )
    assert result.exit_code == 2 and reached == []


@pytest.mark.parametrize("entry", ["batch", "batch_file"])
@pytest.mark.parametrize(
    "options,code",
    [
        (CallOptions(), 9),
        (CallOptions(yes=True, retries=1), 2),
        (CallOptions(dry_run=True, retries=1), 2),
    ],
)
def test_outer_confirmation_and_write_retries_prevent_every_backend_call(
    tmp_path, entry, options, code
) -> None:
    backend = RecordingBackend()
    app = MailCloudApplication(
        environment=synthetic_environment(tmp_path), backend_factory=lambda *a, **kw: backend
    )
    result = _call(
        app,
        entry,
        {"version": 1, "operations": [{"op": "mkdir", "remote_path": "/TEST/a"}]},
        tmp_path / "plan.json",
        options,
    )
    assert result.exit_code == code and backend.calls == []


@pytest.mark.parametrize("entry", ["batch", "batch_file"])
@pytest.mark.parametrize("continuation", [False, True])
@pytest.mark.parametrize("unexpected", [False, True])
def test_partial_keeps_order_schema_privacy_and_fresh_call(
    tmp_path, entry, continuation, unexpected
) -> None:
    backend = RecordingBackend(
        SUCCESS,
        RuntimeError("access_token=batch-private-edge-sentinel")
        if unexpected
        else RcloneResult(
            1, "private-provider-stream", "network unreachable token=batch-private-edge-sentinel", 0
        ),
        SUCCESS,
    )
    factories = []

    def factory(*a, **kw):
        factories.append(True)
        return backend

    app = MailCloudApplication(environment=synthetic_environment(tmp_path), backend_factory=factory)
    document = {
        "version": 1,
        "defaults": {"continue_on_error": continuation},
        "operations": [{"op": "mkdir", "remote_path": f"/TEST/{i}"} for i in range(3)],
    }
    result = _call(
        app, entry, document, tmp_path / "plan.json", CallOptions(yes=True, trace_id="partial")
    )
    assert result.exit_code == 11 and not result.ok and result.error is None
    assert result.result["status"] == "partial_failure" and result.result["total"] == (
        3 if continuation else 2
    )
    assert [item["index"] for item in result.result["items"]] == list(range(result.result["total"]))
    assert result.result["items"][0]["ok"] is True and result.result["items"][1]["ok"] is False
    assert result.result["items"][1]["error"]["kind"] == (
        "unknown_error" if unexpected else "network_error"
    )
    assert "batch-private-edge-sentinel" not in repr(result) + result.to_json()
    assert "private-provider-stream" not in repr(result) + result.to_json()
    schema = json.loads(
        (Path(__file__).resolve().parents[2] / "schemas/result-envelope.schema.json").read_text(
            encoding="utf-8"
        )
    )
    Draft202012Validator(schema).validate(result.to_payload())
    later = app.batch(
        {"version": 1.0, "operations": [{"op": "ls", "remote_path": "/TEST"}]},
        options=CallOptions(dry_run=True),
    )
    assert later.ok and later.trace_id is None and len(factories) == 2
    assert len(backend.calls) == (3 if continuation else 2)


def test_read_only_batch_uses_profile_retry_budget_but_explicit_zero_disables_it(tmp_path) -> None:
    environment = synthetic_environment(tmp_path, '[profiles.default]\nremote="fake:"\nretries=1\n')
    backend = RecordingBackend(
        RcloneResult(1, "", "network unreachable", 0), RcloneResult(0, json.dumps([ITEM]), "", 0)
    )
    app = MailCloudApplication(environment=environment, backend_factory=lambda *a, **kw: backend)
    document = {"version": 1, "operations": [{"op": "ls", "remote_path": "/TEST"}]}
    result = app.batch(document)
    assert result.ok and len(backend.calls) == 2 and result.result["items"][0]["result"]["items"]
    backend.responses = [RcloneResult(1, "", "network unreachable", 0)]
    failed = app.batch(document, options=CallOptions(retries=0))
    assert failed.exit_code == 11 and len(backend.calls) == 3


def test_real_preflight_checks_every_item_and_public_journal_before_first_backend(tmp_path) -> None:
    source = tmp_path / "source.txt"
    source.write_bytes(b"preflight")
    environment = synthetic_environment(tmp_path)
    backend = RecordingBackend()
    app = MailCloudApplication(environment=environment, backend_factory=lambda *a, **kw: backend)
    document = {
        "version": 1,
        "operations": [
            {
                "op": "publish",
                "local_path": str(source),
                "remote_path": "/Hermes/public/report.txt",
            },
            {"op": "rm", "remote_path": "/TEST"},
        ],
    }
    result = app.batch(document, options=CallOptions(yes=True))
    assert result.exit_code == 2 and result.error is not None and backend.calls == []
    journal = Path(environment["HMC_LINKS_JOURNAL"])
    assert journal.parent.is_dir() and journal.with_name(f".{journal.name}.lock").is_file()
    assert not journal.exists()


@pytest.mark.parametrize("continuation", [False, True])
def test_document_file_and_subprocess_cli_partial_payload_exit_schema_parity(
    tmp_path, continuation
) -> None:
    harness = CliFakeHarness.create(tmp_path)
    document = {
        "version": 1,
        "defaults": {"continue_on_error": continuation},
        "operations": [
            {"op": "mkdir", "remote_path": "/TEST/first"},
            {"op": "mkdir", "remote_path": "/TEST/fail"},
            {"op": "mkdir", "remote_path": "/TEST/third"},
        ],
    }
    path = tmp_path / "plan.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    cli = harness.run(
        "batch",
        str(path),
        "--yes",
        "--json",
        "--trace-id",
        "batch-parity",
        responses={
            json.dumps(["mkdir", "fake:/TEST/fail"]): {
                "returncode": 1,
                "stderr": "network unreachable token=batch-private-edge-sentinel",
            }
        },
    )
    app = MailCloudApplication(
        environment=synthetic_environment(tmp_path),
        backend_factory=lambda config, *, environment: RcloneRunner(
            (sys.executable, str(harness.script)), environment=environment
        ),
    )
    direct = app.batch(document, options=CallOptions(yes=True, trace_id="batch-parity"))
    file_result = app.batch_file(path, options=CallOptions(yes=True, trace_id="batch-parity"))
    assert direct.exit_code == file_result.exit_code == cli.returncode == 11
    assert (
        cli.stderr == ""
        and json.loads(cli.stdout) == direct.to_payload() == file_result.to_payload()
    )
    assert len(harness.recorded_calls()) == (9 if continuation else 6)
    assert "batch-private-edge-sentinel" not in cli.stdout + repr(direct)


def test_cli_file_handler_reaches_real_application_and_preserves_unknown_item_results(
    tmp_path, monkeypatch
) -> None:
    from typer.testing import CliRunner

    import hermes_mailcloud.cli as cli

    for key, value in synthetic_environment(tmp_path).items():
        monkeypatch.setenv(key, value)
    path = tmp_path / "plan.json"
    path.write_text(
        json.dumps(
            {
                "version": 1,
                "operations": [
                    {"op": "mkdir", "remote_path": "/TEST/first"},
                    {"op": "mkdir", "remote_path": "/TEST/second"},
                ],
            }
        ),
        encoding="utf-8",
    )
    backend = RecordingBackend(SUCCESS, ValueError("access_token=unexpected-item-private"))
    monkeypatch.setattr(composition, "create_backend", lambda *a, **kw: backend)
    reached, original = [], MailCloudApplication.batch_file

    def observed(self, *args, **kwargs):
        reached.append(args)
        return original(self, *args, **kwargs)

    monkeypatch.setattr(MailCloudApplication, "batch_file", observed)
    result = CliRunner().invoke(cli.app, ["batch", str(path), "--yes", "--json"])
    payload = json.loads(result.stdout)
    assert result.exit_code == 11 and len(reached) == 1 and reached[0] == (path,)
    assert (
        payload["result"]["items"][0]["ok"] is True
        and payload["result"]["items"][1]["error"]["kind"] == "unknown_error"
    )
    assert "error" not in payload and "unexpected-item-private" not in result.stdout
    assert len(backend.calls) == 2


@pytest.mark.parametrize("entry", ["batch", "batch_file"])
def test_bad_environment_profile_does_not_mask_parser_or_missing_file(tmp_path, entry) -> None:
    environment = synthetic_environment(tmp_path)
    environment["HMC_PROFILE"] = " "
    reached = []

    def forbidden(*a, **kw):
        reached.append(True)
        raise AssertionError("parser refusal must precede configuration")

    app = MailCloudApplication(environment=environment, config_loader=forbidden)
    result = (
        app.batch({"version": 1, "defaults": None, "operations": []})
        if entry == "batch"
        else app.batch_file(tmp_path / "missing.json")
    )
    assert result.exit_code == (2 if entry == "batch" else 7) and reached == []
