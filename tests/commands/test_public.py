"""Fake-backend and CLI tests for guarded public publish/link commands."""

from __future__ import annotations

import json
import os
import stat as stat_module
import subprocess
import sys
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import cast

import pytest

import hermes_mailcloud.journal as journal_module
from hermes_mailcloud.commands.public import PublicCommands
from hermes_mailcloud.config import ResolvedConfig
from hermes_mailcloud.core.errors import ErrorKind, MailCloudError
from hermes_mailcloud.journal import MAX_JOURNAL_BYTES, JournalError
from hermes_mailcloud.rclone.parser import PublicLink
from hermes_mailcloud.rclone.runner import RcloneResult

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


def test_publish_orders_upload_link_and_private_journal_after_policy_validation(
    tmp_path: Path,
) -> None:
    source = tmp_path / "report.txt"
    source.write_text("public", encoding="utf-8")
    journal = tmp_path / "links.jsonl"
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
    journal_payload = json.loads(journal.read_text(encoding="utf-8"))
    assert journal_payload["operation"] == "publish"
    assert journal_payload["remote_path"] == "/Hermes/public/report.txt"
    assert journal_payload["public_url"] == PUBLIC_URL
    assert journal_payload["public_url_fingerprint"] == result["public_url_fingerprint"]
    assert PUBLIC_URL not in json.dumps(result)


def test_link_applies_public_path_and_dangerous_remote_object_policy_before_rclone(
    tmp_path: Path,
) -> None:
    backend = RecordingBackend()
    command = PublicCommands(backend, _config(journal=tmp_path / "links.jsonl"), timeout_seconds=60)

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
        backend, _config(journal=tmp_path / "links.jsonl"), timeout_seconds=60
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
    if failure == "insecure_lock":
        lock_path = journal.with_name(f".{journal.name}.lock")
        lock_path.write_bytes(b"")
        lock_path.chmod(0o644)
        return
    if failure == "symlink_lock":
        journal.with_name(f".{journal.name}.lock").symlink_to("untrusted-lock-target")
        return
    if failure == "invalid_permission_journal":
        journal.write_bytes(b'{"version":1}\n')
        journal.chmod(0o644)
        return
    if failure == "oversized_journal":
        journal.write_bytes(b"x" * (MAX_JOURNAL_BYTES + 1))
        journal.chmod(0o600)
        return
    if failure == "unreadable_journal":
        journal.write_bytes(b'{"version":1}\n')
        journal.chmod(0o600)
        original_open = journal_module.os.open

        def deny_journal_open(
            candidate: str | Path,
            flags: int,
            mode: int = 0o777,
            *,
            dir_fd: int | None = None,
        ) -> int:
            if Path(candidate) == journal:
                raise PermissionError("journal read denied")
            return original_open(candidate, flags, mode, dir_fd=dir_fd)

        monkeypatch.setattr(journal_module.os, "open", deny_journal_open)
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
    journal = tmp_path / "links.jsonl"
    _make_journal_preflight_fail(journal, failure, monkeypatch)
    backend = RecordingBackend()
    command = PublicCommands(backend, _config(journal=journal), timeout_seconds=9)

    with pytest.raises(JournalError):
        if operation == "publish":
            command.publish(str(source), "/Hermes/public/report.txt", yes=True)
        else:
            command.link("/Hermes/public/report.txt")

    assert backend.calls == []


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


_FAKE_RCLONE = """#!/usr/bin/env python3
import json
import sys
from pathlib import Path

command, *args = sys.argv[1:]
with Path(__file__).with_name("rclone.jsonl").open("a", encoding="utf-8") as output:
    output.write(json.dumps([command, *args]) + "\\n")
if command == "copyto":
    raise SystemExit(0)
if command == "link":
    url = "https://cloud.mail.ru/public/public-command-capability/path"
    print(f"{url} {url}" if "ambiguous" in Path(__file__).name else url)
    raise SystemExit(0)
sys.stderr.write("unexpected fake command token=raw-backend-sentinel\\n")
raise SystemExit(97)
"""


def _fake_rclone(tmp_path: Path, *, name: str = "fake-rclone") -> Path:
    binary = tmp_path / name
    binary.write_text(_FAKE_RCLONE, encoding="utf-8")
    binary.chmod(binary.stat().st_mode | stat_module.S_IXUSR)
    return binary


def _run_cli(
    binary: Path,
    journal: Path,
    *arguments: str,
    extra_environment: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "hermes_mailcloud.cli", *arguments],
        capture_output=True,
        text=True,
        timeout=10,
        env={
            **os.environ,
            "HMC_REMOTE": "fake:",
            "HMC_RCLONE_PATH": str(binary),
            "HMC_LINKS_JOURNAL": str(journal),
            **(extra_environment or {}),
        },
    )


def test_cli_public_commands_emit_only_fingerprints_and_keep_capabilities_in_journal(
    tmp_path: Path,
) -> None:
    binary = _fake_rclone(tmp_path)
    journal = tmp_path / "links.jsonl"
    source = tmp_path / "report.txt"
    source.write_text("public", encoding="utf-8")

    published = _run_cli(
        binary,
        journal,
        "publish",
        str(source),
        "/Hermes/public/report.txt",
        "--yes",
        "--json",
    )
    linked = _run_cli(binary, journal, "link", "/Hermes/public/report.txt", "--json")

    assert published.returncode == 0
    assert linked.returncode == 0
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
    records = [json.loads(line) for line in journal.read_text(encoding="utf-8").splitlines()]
    assert [record["operation"] for record in records] == ["publish", "link"]
    assert all(record["public_url"] == PUBLIC_URL for record in records)


def test_cli_public_link_parse_errors_do_not_emit_raw_provider_capabilities(tmp_path: Path) -> None:
    binary = _fake_rclone(tmp_path, name="ambiguous-rclone")
    journal = tmp_path / "links.jsonl"

    result = _run_cli(
        binary,
        journal,
        "link",
        "/Hermes/public/report.txt",
        "--json",
    )

    assert result.returncode == 13
    assert json.loads(result.stdout)["error"]["kind"] == "parse_error"
    assert PUBLIC_URL not in result.stdout + result.stderr
    assert not journal.exists()


def test_cli_keeps_unlink_absent_until_its_live_invalidation_capability_passes(
    tmp_path: Path,
) -> None:
    binary = _fake_rclone(tmp_path)
    journal = tmp_path / "links.jsonl"

    result = _run_cli(binary, journal, "unlink", "/Hermes/public/report.txt", "--json")

    assert result.returncode == 2
    assert json.loads(result.stdout)["error"]["kind"] == "invalid_arguments"
    assert not (tmp_path / "rclone.jsonl").exists()
