"""Fake-backend tests for upload and atomic local download behavior."""

from __future__ import annotations

import os
import time
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from hermes_mailcloud.commands.transfer import TransferCommands
from hermes_mailcloud.config import ResolvedConfig
from hermes_mailcloud.core.errors import ErrorKind, ErrorPayload, MailCloudError
from hermes_mailcloud.rclone.runner import RcloneResult, RcloneRunnerError


@dataclass
class RecordingBackend:
    calls: list[tuple[tuple[str, ...], float | None]] = field(default_factory=list)

    def require_success(
        self, args: Sequence[str], *, timeout_seconds: float | None = None
    ) -> RcloneResult:
        self.calls.append((tuple(args), timeout_seconds))
        return RcloneResult(0, "", "", 1)


@dataclass
class DownloadBackend:
    payload: bytes
    modified_ns: int
    failure: RcloneRunnerError | None = None
    calls: list[tuple[tuple[str, ...], float | None]] = field(default_factory=list)

    def require_success(
        self, args: Sequence[str], *, timeout_seconds: float | None = None
    ) -> RcloneResult:
        self.calls.append((tuple(args), timeout_seconds))
        temporary = Path(args[2])
        temporary.write_bytes(self.payload)
        os.utime(temporary, ns=(self.modified_ns, self.modified_ns))
        if self.failure is not None:
            raise self.failure
        return RcloneResult(0, "", "", 1)


def _config(*, remote: str | None = "mailru:", overwrite: str = "never") -> ResolvedConfig:
    return ResolvedConfig(
        profile="test",
        config_path=Path("config.toml"),
        remote=remote,
        rclone_path="rclone",
        private_root="/Hermes/private",
        public_root="/Hermes/public",
        temp_root="/Hermes/.tmp",
        links_journal=None,
        default_overwrite=overwrite,
        deny_dangerous_publish=True,
        require_yes_for_destructive=True,
        probe_public_url_after_publish=True,
        timeout_seconds=60,
        retries=0,
    )


@pytest.mark.parametrize(
    ("overwrite", "expected_flag"),
    [("never", "--immutable"), ("always", "--ignore-times"), ("if-newer", "--update")],
)
def test_upload_uses_exact_rclone_overwrite_argv_without_link_calls(
    tmp_path: Path, overwrite: str, expected_flag: str
) -> None:
    source = tmp_path / "report.txt"
    source.write_bytes(b"private")
    backend = RecordingBackend()

    result = TransferCommands(backend, _config(), timeout_seconds=9).upload(
        str(source), "/Hermes/private/report.txt", overwrite=overwrite
    )

    assert result == {
        "local_path": str(source),
        "remote_path": "/Hermes/private/report.txt",
        "published": False,
        "bytes": 7,
        "overwrite": overwrite,
    }
    assert backend.calls == [
        (("copyto", str(source), "mailru:/Hermes/private/report.txt", expected_flag), 9)
    ]


def test_upload_dry_run_validates_without_starting_rclone(tmp_path: Path) -> None:
    source = tmp_path / "report.txt"
    source.write_text("private", encoding="utf-8")
    backend = RecordingBackend()

    result = TransferCommands(backend, _config(), timeout_seconds=60).upload(
        str(source), "/Hermes/private/report.txt", dry_run=True
    )

    assert result["dry_run"] is True
    assert result["overwrite"] == "never"
    assert backend.calls == []


@pytest.mark.parametrize("overwrite", ["invalid", "NEVER"])
def test_upload_rejects_unknown_overwrite_before_starting_rclone(
    tmp_path: Path, overwrite: str
) -> None:
    source = tmp_path / "report.txt"
    source.write_text("private", encoding="utf-8")
    backend = RecordingBackend()

    with pytest.raises(MailCloudError) as caught:
        TransferCommands(backend, _config(), timeout_seconds=60).upload(
            str(source), "/Hermes/private/report.txt", overwrite=overwrite
        )

    assert caught.value.error.kind is ErrorKind.INVALID_ARGUMENTS
    assert backend.calls == []


def test_write_retry_budget_is_rejected_before_transfer(tmp_path: Path) -> None:
    source = tmp_path / "report.txt"
    source.write_text("private", encoding="utf-8")
    backend = RecordingBackend()

    with pytest.raises(MailCloudError) as caught:
        TransferCommands(backend, _config(), timeout_seconds=60).upload(
            str(source), "/Hermes/private/report.txt", retries=1
        )

    assert caught.value.error.kind is ErrorKind.INVALID_ARGUMENTS
    assert backend.calls == []


def test_download_commits_a_completed_temporary_file_after_rclone_success(tmp_path: Path) -> None:
    destination = tmp_path / "report.txt"
    modified_ns = time.time_ns()
    backend = DownloadBackend(b"downloaded", modified_ns)

    result = TransferCommands(backend, _config(), timeout_seconds=11).download(
        "/Hermes/private/report.txt", str(destination)
    )

    assert result == {
        "remote_path": "/Hermes/private/report.txt",
        "local_path": str(destination),
        "overwrite": "never",
        "bytes": 10,
        "updated": True,
    }
    assert backend.calls[0][0][:2] == ("copyto", "mailru:/Hermes/private/report.txt")
    assert backend.calls[0][1] == 11
    assert destination.read_bytes() == b"downloaded"
    assert list(tmp_path.glob(".report.txt.*.hermes-mailcloud-part")) == []


def test_download_never_reports_conflict_without_backend_or_target_change(tmp_path: Path) -> None:
    destination = tmp_path / "report.txt"
    destination.write_text("original", encoding="utf-8")
    backend = RecordingBackend()

    with pytest.raises(MailCloudError) as caught:
        TransferCommands(backend, _config(), timeout_seconds=60).download(
            "/Hermes/private/report.txt", str(destination)
        )

    assert caught.value.error.kind is ErrorKind.CONFLICT
    assert destination.read_text(encoding="utf-8") == "original"
    assert backend.calls == []


def test_download_timeout_cleans_partial_temp_and_preserves_existing_target(tmp_path: Path) -> None:
    destination = tmp_path / "report.txt"
    destination.write_text("original", encoding="utf-8")
    backend = DownloadBackend(
        b"partial",
        time.time_ns(),
        failure=RcloneRunnerError(ErrorPayload(ErrorKind.TIMEOUT, "rclone command timed out")),
    )

    with pytest.raises(RcloneRunnerError) as caught:
        TransferCommands(backend, _config(), timeout_seconds=1).download(
            "/Hermes/private/report.txt", str(destination), overwrite="always"
        )

    assert caught.value.error.kind is ErrorKind.TIMEOUT
    assert destination.read_text(encoding="utf-8") == "original"
    assert list(tmp_path.glob(".report.txt.*.hermes-mailcloud-part")) == []


def test_download_if_newer_preserves_a_newer_local_target_and_cleans_temp(tmp_path: Path) -> None:
    destination = tmp_path / "report.txt"
    destination.write_text("newer-local", encoding="utf-8")
    destination_time = time.time_ns()
    os.utime(destination, ns=(destination_time, destination_time))
    backend = DownloadBackend(b"older-remote", destination_time - 1)

    result = TransferCommands(backend, _config(), timeout_seconds=60).download(
        "/Hermes/private/report.txt", str(destination), overwrite="if-newer"
    )

    assert result["updated"] is False
    assert result["bytes"] == len(b"newer-local")
    assert destination.read_text(encoding="utf-8") == "newer-local"
    assert list(tmp_path.glob(".report.txt.*.hermes-mailcloud-part")) == []


def test_download_dry_run_never_creates_a_temp_or_starts_rclone(tmp_path: Path) -> None:
    destination = tmp_path / "report.txt"
    backend = RecordingBackend()

    result = TransferCommands(backend, _config(), timeout_seconds=60).download(
        "/Hermes/private/report.txt", str(destination), dry_run=True
    )

    assert result["dry_run"] is True
    assert backend.calls == []
    assert list(tmp_path.glob(".report.txt.*.hermes-mailcloud-part")) == []
