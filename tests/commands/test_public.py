"""Fake-backend and CLI tests for guarded public publish/link commands."""

from __future__ import annotations

import json
import sys
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import cast

import pytest

import hermes_mailcloud.journal as journal_module
from hermes_mailcloud._platform import PrivateStorageError
from hermes_mailcloud.commands.public import PublicCommands
from hermes_mailcloud.config import ResolvedConfig
from hermes_mailcloud.core.errors import ErrorKind, MailCloudError
from hermes_mailcloud.journal import MAX_JOURNAL_BYTES, JournalError, LinkJournal
from hermes_mailcloud.rclone.parser import PublicLink
from hermes_mailcloud.rclone.runner import RcloneResult

_TESTS_ROOT = next(parent for parent in Path(__file__).resolve().parents if parent.name == "tests")
if str(_TESTS_ROOT) not in sys.path:
    sys.path.insert(0, str(_TESTS_ROOT))

from helpers.cli_fake import CliFakeHarness  # noqa: E402
from helpers.journal_worker import broaden_capability, make_reparse_link  # noqa: E402

PUBLIC_URL = "https://cloud.mail.ru/public/public-command-capability/path"


@dataclass
class RecordingBackend:
    link_stdout: str = f"{PUBLIC_URL}\n"
    calls: list[tuple[tuple[str, ...], float | None]] = field(default_factory=list)

    def require_success(
        self, args: Sequence[str], *, timeout_seconds: float | None = None
    ) -> RcloneResult:
        self.calls.append((tuple(args), timeout_seconds))
        stdout = self.link_stdout if args[0] == "link" else ""
        return RcloneResult(0, stdout, "", 1)


def _config(*, journal: Path | None, remote: str | None = "mailru:") -> ResolvedConfig:
    return ResolvedConfig(
        profile="test",
        config_path=Path("config.toml"),
        remote=remote,
        rclone_path="rclone",
        private_root="/Hermes/private",
        public_root="/Hermes/public",
        temp_root="/Hermes/.tmp",
        links_journal=journal,
        default_overwrite="never",
        deny_dangerous_publish=True,
        require_yes_for_destructive=True,
        probe_public_url_after_publish=True,
        timeout_seconds=60,
        retries=0,
    )


def _journal_path(root: Path) -> Path:
    return root / "private-state" / "links.jsonl"


def _lock_path(journal: Path) -> Path:
    return journal.with_name(f".{journal.name}.lock")


def _prepare_private_journal(journal: Path) -> None:
    LinkJournal(journal).record("publish", "/Hermes/public/seed.txt", PublicLink(PUBLIC_URL))


def test_publish_orders_upload_link_and_private_journal_after_policy_validation(
    tmp_path: Path,
) -> None:
    source = tmp_path / "report.txt"
    source.write_text("public", encoding="utf-8")
    journal = _journal_path(tmp_path)
    backend = RecordingBackend()

    result = PublicCommands(backend, _config(journal=journal), timeout_seconds=9).publish(
        str(source), "/Hermes/public/report.txt", yes=True
    )

    assert result == {
        "local_path": str(source),
        "remote_path": "/Hermes/public/report.txt",
        "published": True,
        "bytes": 6,
        "overwrite": "never",
        "public_url_fingerprint": PublicLink(PUBLIC_URL).fingerprint,
        "backend": "rclone",
    }
    assert backend.calls == [
        (("copyto", str(source), "mailru:/Hermes/public/report.txt", "--immutable"), 9),
        (("link", "mailru:/Hermes/public/report.txt"), 9),
    ]
    journal_payloads = [
        json.loads(line) for line in journal.read_text(encoding="utf-8").splitlines()
    ]
    assert [payload["operation"] for payload in journal_payloads] == ["publish"]
    assert journal_payloads[0]["remote_path"] == "/Hermes/public/report.txt"
    assert journal_payloads[0]["public_url"] == PUBLIC_URL
    assert journal_payloads[0]["public_url_fingerprint"] == result["public_url_fingerprint"]
    assert PUBLIC_URL not in json.dumps(result)


def test_link_applies_public_path_and_dangerous_remote_object_policy_before_rclone(
    tmp_path: Path,
) -> None:
    backend = RecordingBackend()
    command = PublicCommands(backend, _config(journal=_journal_path(tmp_path)), timeout_seconds=60)

    with pytest.raises(MailCloudError) as outside:
        command.link("/Hermes/private/report.txt")
    with pytest.raises(MailCloudError) as dangerous:
        command.link("/Hermes/public/credentials.txt")
    with pytest.raises(MailCloudError) as retried:
        command.link("/Hermes/public/report.txt", retries=1)

    assert outside.value.error.kind is ErrorKind.UNSAFE_PUBLIC_PATH
    assert dangerous.value.error.kind is ErrorKind.DANGEROUS_FILE_PATTERN
    assert retried.value.error.kind is ErrorKind.INVALID_ARGUMENTS
    assert backend.calls == []


def test_publish_requires_confirmation_and_journal_before_any_cloud_call(tmp_path: Path) -> None:
    source = tmp_path / "report.txt"
    source.write_text("public", encoding="utf-8")
    backend = RecordingBackend()
    configured = PublicCommands(
        backend, _config(journal=_journal_path(tmp_path)), timeout_seconds=60
    )

    with pytest.raises(MailCloudError) as unconfirmed:
        configured.publish(str(source), "/Hermes/public/report.txt")
    with pytest.raises(MailCloudError) as no_journal:
        PublicCommands(backend, _config(journal=None), timeout_seconds=60).publish(
            str(source), "/Hermes/public/report.txt", yes=True
        )

    assert unconfirmed.value.error.kind is ErrorKind.CONFIRMATION_REQUIRED
    assert no_journal.value.error.kind is ErrorKind.CONFIG_ERROR
    assert backend.calls == []


def _make_journal_preflight_fail(
    journal: Path, failure: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    if failure == "unreadable_journal":
        _prepare_private_journal(journal)

        def deny_read(*_args: object, **_kwargs: object) -> bytes:
            raise PrivateStorageError("local link journal could not be read safely")

        monkeypatch.setattr(journal_module, "_read_private_journal", deny_read)
        return

    _prepare_private_journal(journal)

    if failure == "insecure_lock":
        broaden_capability(_lock_path(journal))
        return
    if failure == "symlink_lock":
        lock = _lock_path(journal)
        lock.unlink()
        target = journal.parent / "link-target"
        target.mkdir()
        try:
            make_reparse_link(lock, target)
        except OSError:
            pytest.skip("creating a test reparse link is unavailable in this environment")
        return
    if failure == "invalid_permission_journal":
        broaden_capability(journal)
        return
    if failure == "oversized_journal":
        journal.write_bytes(b"x" * (MAX_JOURNAL_BYTES + 1))
        return
    raise AssertionError(f"unknown journal preflight failure: {failure}")


@pytest.mark.parametrize("operation", ["publish", "link"])
@pytest.mark.parametrize(
    "failure",
    [
        "insecure_lock",
        "symlink_lock",
        "invalid_permission_journal",
        "unreadable_journal",
        "oversized_journal",
    ],
)
def test_public_operations_fail_closed_on_deterministic_journal_preflight_errors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, operation: str, failure: str
) -> None:
    source = tmp_path / "report.txt"
    source.write_text("public", encoding="utf-8")
    journal = _journal_path(tmp_path)
    _make_journal_preflight_fail(journal, failure, monkeypatch)
    backend = RecordingBackend()
    command = PublicCommands(backend, _config(journal=journal), timeout_seconds=9)

    with pytest.raises(JournalError):
        if operation == "publish":
            command.publish(str(source), "/Hermes/public/report.txt", yes=True)
        else:
            command.link("/Hermes/public/report.txt")

    assert backend.calls == []


@pytest.mark.parametrize("operation", ["publish", "link"])
def test_backend_success_then_journal_failure_is_safe_and_never_retried(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, operation: str
) -> None:
    source = tmp_path / "report.txt"
    source.write_text("public", encoding="utf-8")
    journal = _journal_path(tmp_path)
    backend = RecordingBackend()
    command = PublicCommands(backend, _config(journal=journal), timeout_seconds=9)

    def fail_replace(_path: Path, _content: bytes) -> None:
        raise JournalError("simulated local record failure")

    monkeypatch.setattr(journal_module, "_atomic_replace", fail_replace)

    with pytest.raises(JournalError) as caught:
        if operation == "publish":
            command.publish(str(source), "/Hermes/public/report.txt", yes=True)
        else:
            command.link("/Hermes/public/report.txt")

    assert caught.value.error.kind is ErrorKind.UNKNOWN_ERROR
    assert "remote effect may have occurred" in str(caught.value)
    assert "will not be retried" in str(caught.value)
    assert PUBLIC_URL not in str(caught.value)
    assert str(journal.parent) not in str(caught.value)
    assert [call[0][0] for call in backend.calls] == (
        ["copyto", "link"] if operation == "publish" else ["link"]
    )
    assert not journal.exists()


def test_public_dry_runs_validate_without_journal_or_backend_calls(tmp_path: Path) -> None:
    source = tmp_path / "report.txt"
    source.write_text("public", encoding="utf-8")
    backend = RecordingBackend()
    command = PublicCommands(backend, _config(journal=None), timeout_seconds=60)

    published = command.publish(str(source), "/Hermes/public/report.txt", dry_run=True)
    linked = command.link("/Hermes/public/report.txt", dry_run=True)
    published_plan = cast(list[dict[str, str]], published["plan"])
    linked_plan = cast(list[dict[str, str]], linked["plan"])

    assert published["published"] is False
    assert [item["step"] for item in published_plan] == [
        "validate_local_file",
        "validate_public_root",
        "upload",
        "create_public_link",
        "record_link_journal",
    ]
    assert [item["step"] for item in linked_plan] == [
        "validate_public_root",
        "create_public_link",
        "record_link_journal",
    ]
    assert backend.calls == []


def test_cli_public_commands_emit_only_fingerprints_and_keep_capabilities_in_journal(
    tmp_path: Path,
) -> None:
    harness = CliFakeHarness.create(tmp_path)
    source = tmp_path / "report [1] & ü.txt"
    source.write_text("public", encoding="utf-8")
    remote_path = "/Hermes/public/отчёт [1] & done.txt"
    responses = {"link": {"stdout": f"{PUBLIC_URL}\n"}}

    published = harness.run(
        "publish",
        str(source),
        remote_path,
        "--yes",
        "--json",
        responses=responses,
    )
    linked = harness.run("link", remote_path, "--json", responses=responses)

    assert published.returncode == 0, published.stderr
    assert linked.returncode == 0, linked.stderr
    assert published.stderr == linked.stderr == ""
    assert PUBLIC_URL not in published.stdout + linked.stdout
    assert (
        json.loads(published.stdout)["result"]["public_url_fingerprint"]
        == PublicLink(PUBLIC_URL).fingerprint
    )
    assert (
        json.loads(linked.stdout)["result"]["public_url_fingerprint"]
        == PublicLink(PUBLIC_URL).fingerprint
    )
    records = [
        json.loads(line) for line in harness.journal.read_text(encoding="utf-8").splitlines()
    ]
    assert [record["operation"] for record in records] == ["publish", "link"]
    assert all(record["public_url"] == PUBLIC_URL for record in records)
    calls = harness.recorded_calls()
    assert calls == [
        ["copyto", str(source), f"fake:{remote_path}", "--immutable"],
        ["link", f"fake:{remote_path}"],
        ["link", f"fake:{remote_path}"],
    ]


def test_cli_public_link_parse_errors_do_not_emit_raw_provider_capabilities(
    tmp_path: Path,
) -> None:
    harness = CliFakeHarness.create(tmp_path)
    remote_path = "/Hermes/public/report.txt"

    result = harness.run(
        "link",
        remote_path,
        "--json",
        responses={"link": {"stdout": f"{PUBLIC_URL} {PUBLIC_URL}\n"}},
    )

    assert result.returncode == 13
    assert json.loads(result.stdout)["error"]["kind"] == "parse_error"
    assert PUBLIC_URL not in result.stdout + result.stderr
    assert not harness.journal.exists()


def test_cli_keeps_unlink_absent_until_its_live_invalidation_capability_passes(
    tmp_path: Path,
) -> None:
    harness = CliFakeHarness.create(tmp_path)

    result = harness.run("unlink", "/Hermes/public/report.txt", "--json")

    assert result.returncode == 2
    assert json.loads(result.stdout)["error"]["kind"] == "invalid_arguments"
    assert harness.recorded_calls() == []
