"""Production publication policy and native private journal through the public API."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from tests.helpers.application import RecordingBackend, synthetic_environment
from tests.helpers.cli_fake import CliFakeHarness
from tests.helpers.journal_worker import broaden_capability

from hermes_mailcloud.application import CallOptions, MailCloudApplication
from hermes_mailcloud.core.errors import ErrorKind
from hermes_mailcloud.journal import LinkJournal
from hermes_mailcloud.rclone.parser import PublicLink
from hermes_mailcloud.rclone.runner import RcloneResult

PUBLIC_URL = "https://cloud.mail.ru/public/s2-synthetic-capability/fixture"
LINK = RcloneResult(0, PUBLIC_URL + "\n", "access_token=publication-private-sentinel", 0)
SUCCESS = RcloneResult(0, "", "", 0)


def _call(app, operation, source, path="/Hermes/public/report.txt", *, options=None):
    if operation == "publish":
        return app.publish(str(source), path, options=options)
    return app.link(path, options=options)


@pytest.mark.parametrize("operation", ["publish", "link"])
def test_public_success_orders_native_journal_preflight_and_exposes_only_fingerprint(
    tmp_path, operation
) -> None:
    source = tmp_path / "report.txt"
    source.write_bytes(b"public synthetic file")
    environment = synthetic_environment(tmp_path, '[profiles.default]\nremote="fake:"\nretries=4\n')
    journal = Path(environment["HMC_LINKS_JOURNAL"])
    observed = []

    def external(args):
        lock = journal.with_name(f".{journal.name}.lock")
        assert lock.is_file(), "publication reached cloud before native journal preflight"
        assert not journal.exists()
        observed.append(args[0])
        return LINK if args[0] == "link" else SUCCESS

    backend = RecordingBackend(*([external, external] if operation == "publish" else [external]))
    app = MailCloudApplication(environment=environment, backend_factory=lambda *a, **kw: backend)
    result = _call(app, operation, source, options=CallOptions(yes=True))
    assert result.ok and result.operation == operation
    assert observed == (["copyto", "link"] if operation == "publish" else ["link"])
    assert result.result["public_url_fingerprint"] == PublicLink(PUBLIC_URL).fingerprint
    assert PUBLIC_URL not in repr(result) + result.to_json()
    assert "publication-private-sentinel" not in repr(result) + result.to_json()
    records = [json.loads(line) for line in journal.read_text(encoding="utf-8").splitlines()]
    assert len(records) == 1
    assert records[0]["public_url"] == PUBLIC_URL
    assert (
        records[0]["operation"] == operation
        and records[0]["remote_path"] == "/Hermes/public/report.txt"
    )
    assert records[0]["public_url_fingerprint"] == result.result["public_url_fingerprint"]
    if operation == "publish":
        assert result.result["published"] is True and result.result["bytes"] == 21
        assert backend.calls[0][0] == [
            "copyto",
            str(source),
            "fake:/Hermes/public/report.txt",
            "--immutable",
        ]
    else:
        assert backend.calls[0][0] == ["link", "fake:/Hermes/public/report.txt"]


@pytest.mark.parametrize("operation", ["publish", "link"])
@pytest.mark.parametrize(
    "path,kind",
    [
        ("/Hermes/private/report.txt", ErrorKind.UNSAFE_PUBLIC_PATH),
        ("/Hermes/publicity/report.txt", ErrorKind.UNSAFE_PUBLIC_PATH),
        ("/Hermes/public", ErrorKind.UNSAFE_PUBLIC_PATH),
        ("/Hermes/public/../../private/report.txt", ErrorKind.UNSAFE_PUBLIC_PATH),
        ("/Hermes/public/.env", ErrorKind.DANGEROUS_FILE_PATTERN),
        ("/Hermes/public/id_rsa", ErrorKind.DANGEROUS_FILE_PATTERN),
    ],
)
def test_public_path_and_danger_guards_precede_confirmation_and_journal(
    tmp_path, operation, path, kind
) -> None:
    source = tmp_path / "report.txt"
    source.write_text("fixture", encoding="utf-8")
    environment = synthetic_environment(tmp_path)
    backend = RecordingBackend()
    app = MailCloudApplication(environment=environment, backend_factory=lambda *a, **kw: backend)
    result = _call(app, operation, source, path)
    assert result.error.kind is kind and backend.calls == []
    assert not Path(environment["HMC_LINKS_JOURNAL"]).parent.exists()


@pytest.mark.parametrize("name", [".env", "id_rsa", "secrets.json"])
def test_publish_dangerous_local_source_is_not_hidden_by_a_safe_remote_name(tmp_path, name) -> None:
    source = tmp_path / name
    source.write_bytes(b"synthetic secret-shaped fixture")
    backend = RecordingBackend()
    app = MailCloudApplication(
        environment=synthetic_environment(tmp_path), backend_factory=lambda *a, **kw: backend
    )
    result = app.publish(str(source), "/Hermes/public/report.txt", options=CallOptions(yes=True))
    assert result.error.kind is ErrorKind.DANGEROUS_FILE_PATTERN and backend.calls == []


def test_publish_requires_real_confirmation_and_refusal_does_not_poison_the_next_call(
    tmp_path,
) -> None:
    source = tmp_path / "report.txt"
    source.write_bytes(b"fixture")
    environment = synthetic_environment(tmp_path)
    backends = []

    def factory(*a, **kw):
        backend = RecordingBackend(SUCCESS, LINK)
        backends.append(backend)
        return backend

    app = MailCloudApplication(environment=environment, backend_factory=factory)
    refused = app.publish(str(source), "/Hermes/public/report.txt")
    assert refused.error.kind is ErrorKind.CONFIRMATION_REQUIRED
    assert backends[0].calls == [] and not Path(environment["HMC_LINKS_JOURNAL"]).parent.exists()
    completed = app.publish(str(source), "/Hermes/public/report.txt", options=CallOptions(yes=True))
    assert completed.ok and len(backends[1].calls) == 2
    refused_again = app.publish(str(source), "/Hermes/public/report.txt")
    assert refused_again.error.kind is ErrorKind.CONFIRMATION_REQUIRED and backends[2].calls == []
    assert refused.error.kind is ErrorKind.CONFIRMATION_REQUIRED


@pytest.mark.parametrize("operation", ["publish", "link"])
@pytest.mark.parametrize("failure", ["parent-file", "unsafe-journal", "unsafe-lock"])
def test_native_journal_preflight_failure_prevents_every_cloud_call(
    tmp_path, operation, failure
) -> None:
    source = tmp_path / "report.txt"
    source.write_bytes(b"fixture")
    environment = synthetic_environment(tmp_path)
    journal = Path(environment["HMC_LINKS_JOURNAL"])
    if failure == "parent-file":
        journal.parent.write_bytes(b"not a directory")
    else:
        LinkJournal(journal).record("link", "/Hermes/public/seed.txt", PublicLink(PUBLIC_URL))
        broaden_capability(
            journal if failure == "unsafe-journal" else journal.with_name(f".{journal.name}.lock")
        )
    backend = RecordingBackend()
    app = MailCloudApplication(environment=environment, backend_factory=lambda *a, **kw: backend)
    result = _call(app, operation, source, options=CallOptions(yes=True))
    assert not result.ok and result.error is not None
    assert backend.calls == []
    assert PUBLIC_URL not in repr(result) + result.to_json()


@pytest.mark.parametrize("operation", ["publish", "link"])
def test_post_link_native_record_failure_is_safe_matches_cli_and_never_retries_or_rolls_back(
    tmp_path, operation
) -> None:
    source = tmp_path / "report.txt"
    source.write_bytes(b"fixture")
    api_root, cli_root = tmp_path / "api", tmp_path / "cli"
    api_root.mkdir()
    cli_root.mkdir()
    environment = synthetic_environment(api_root)
    journal = Path(environment["HMC_LINKS_JOURNAL"])

    def cloud_link(args):
        assert args == ["link", "fake:/Hermes/public/report.txt"]
        broaden_capability(journal.with_name(f".{journal.name}.lock"))
        return LINK

    backend = RecordingBackend(*([SUCCESS, cloud_link] if operation == "publish" else [cloud_link]))
    app = MailCloudApplication(environment=environment, backend_factory=lambda *a, **kw: backend)
    direct = _call(app, operation, source, options=CallOptions(yes=True))
    harness = CliFakeHarness.create(cli_root)
    args = [
        operation,
        *([str(source)] if operation == "publish" else []),
        "/Hermes/public/report.txt",
        "--json",
        "--yes",
    ]
    cli = harness.run(
        *args,
        responses={"link": {"stdout": PUBLIC_URL + "\n"}},
        sabotage={"command": "link", "mode": "broaden-lock", "journal": str(harness.journal)},
    )
    assert direct.exit_code == cli.returncode == 1
    assert direct.error.kind is ErrorKind.UNKNOWN_ERROR
    assert "remote effect may have occurred" in direct.error.message
    assert "will not be retried" in direct.error.message
    assert cli.stderr == "" and json.loads(cli.stdout) == direct.to_payload()
    assert (
        [args[0] for args, _ in backend.calls]
        == [args[0] for args in harness.recorded_calls()]
        == (["copyto", "link"] if operation == "publish" else ["link"])
    )
    assert not journal.exists() and not harness.journal.exists()
    for value in (repr(direct), direct.to_json(), cli.stdout, cli.stderr):
        assert PUBLIC_URL not in value and "publication-private-sentinel" not in value


def test_public_dry_run_still_validates_a_real_source_and_policy(tmp_path) -> None:
    backend = RecordingBackend()
    environment = synthetic_environment(tmp_path)
    app = MailCloudApplication(environment=environment, backend_factory=lambda *a, **kw: backend)
    missing = app.publish(
        str(tmp_path / "missing.txt"),
        "/Hermes/public/report.txt",
        options=CallOptions(dry_run=True),
    )
    assert not missing.ok and missing.error.kind is ErrorKind.NOT_FOUND
    assert backend.calls == [] and not Path(environment["HMC_LINKS_JOURNAL"]).parent.exists()
