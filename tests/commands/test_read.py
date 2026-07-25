"""Fake/golden tests for typed rclone-backed read operations."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from hermes_mailcloud.commands.read import ReadCommands
from hermes_mailcloud.config import ResolvedConfig
from hermes_mailcloud.core.errors import ErrorKind, ErrorPayload, MailCloudError
from hermes_mailcloud.rclone.runner import RcloneResult, RcloneRunnerError

FIXTURES = Path(__file__).parents[1] / "rclone" / "fixtures"


@dataclass
class RecordingBackend:
    results: list[RcloneResult]
    calls: list[tuple[tuple[str, ...], float | None]] = field(default_factory=list)

    def require_success(
        self, args: Sequence[str], *, timeout_seconds: float | None = None
    ) -> RcloneResult:
        self.calls.append((tuple(args), timeout_seconds))
        return self.results.pop(0)


@dataclass
class FlakyNetworkBackend:
    result: RcloneResult
    failures_before_success: int
    calls: list[tuple[tuple[str, ...], float | None]] = field(default_factory=list)

    def require_success(
        self, args: Sequence[str], *, timeout_seconds: float | None = None
    ) -> RcloneResult:
        self.calls.append((tuple(args), timeout_seconds))
        if len(self.calls) <= self.failures_before_success:
            raise RcloneRunnerError(
                ErrorPayload(ErrorKind.NETWORK_ERROR, "rclone network request failed")
            )
        return self.result


def _config(*, remote: str | None = "mailru:") -> ResolvedConfig:
    return ResolvedConfig(
        profile="test",
        config_path=Path("config.toml"),
        remote=remote,
        rclone_path="rclone",
        private_root="/Hermes/private",
        public_root="/Hermes/public",
        temp_root="/Hermes/.tmp",
        links_journal=None,
        default_overwrite="never",
        deny_dangerous_publish=True,
        require_yes_for_destructive=True,
        probe_public_url_after_publish=True,
        timeout_seconds=60,
        retries=0,
    )


def test_ls_uses_the_fake_backend_and_normalizes_the_golden_listing() -> None:
    backend = RecordingBackend(
        [RcloneResult(0, (FIXTURES / "lsjson-success.json").read_text(), "", 1)]
    )

    result = ReadCommands(backend, _config(), timeout_seconds=7, retries=0).ls("/Hermes")

    assert result == {
        "remote_path": "/Hermes",
        "items": [
            {"name": "private", "path": "/Hermes/private", "type": "directory"},
            {
                "modified": "2026-07-25T01:02:03Z",
                "name": "notes.txt",
                "path": "/Hermes/private/notes.txt",
                "size": 17,
                "type": "file",
            },
        ],
    }
    assert backend.calls == [(("lsjson", "mailru:/Hermes"), 7)]


def test_ls_passes_declared_filter_flags_to_rclone() -> None:
    backend = RecordingBackend([RcloneResult(0, "[]", "", 1)])

    result = ReadCommands(backend, _config(), timeout_seconds=60, retries=0).ls(
        "/Hermes", recursive=True, files_only=True
    )

    assert result == {"remote_path": "/Hermes", "items": []}
    assert backend.calls == [(("lsjson", "mailru:/Hermes", "--recursive", "--files-only"), 60)]


def test_ls_rejects_incompatible_filters_before_calling_the_backend() -> None:
    backend = RecordingBackend([])

    with pytest.raises(MailCloudError) as caught:
        ReadCommands(backend, _config(), timeout_seconds=60, retries=0).ls(
            "/Hermes", files_only=True, dirs_only=True
        )

    assert caught.value.error.kind is ErrorKind.INVALID_ARGUMENTS
    assert backend.calls == []


def test_stat_uses_the_fake_backend_and_only_exposes_supported_metadata() -> None:
    backend = RecordingBackend(
        [RcloneResult(0, (FIXTURES / "lsjson-stat-success.json").read_text(), "", 1)]
    )

    result = ReadCommands(backend, _config(), timeout_seconds=11, retries=0).stat(
        "/Hermes/private/notes.txt"
    )

    assert result == {
        "remote_path": "/Hermes/private/notes.txt",
        "type": "file",
        "size": 17,
        "modified": "2026-07-25T01:02:03Z",
        "hashes": {"MD5": "0123456789abcdef0123456789abcdef"},
    }
    assert backend.calls == [
        (("lsjson", "mailru:/Hermes/private/notes.txt", "--stat", "--hash"), 11)
    ]


@pytest.mark.parametrize("method", ["ls", "stat"])
def test_read_operations_require_a_configured_remote_before_backend_use(method: str) -> None:
    backend = RecordingBackend([])
    commands = ReadCommands(backend, _config(remote=None), timeout_seconds=60, retries=0)

    with pytest.raises(MailCloudError) as caught:
        getattr(commands, method)("/Hermes")

    assert caught.value.error.kind is ErrorKind.REMOTE_NOT_CONFIGURED
    assert backend.calls == []


def test_ls_retries_only_transient_backend_failures_using_the_configured_budget() -> None:
    backend = FlakyNetworkBackend(RcloneResult(0, "[]", "", 1), failures_before_success=1)

    result = ReadCommands(backend, _config(), timeout_seconds=60, retries=1).ls("/Hermes")

    assert result == {"remote_path": "/Hermes", "items": []}
    assert backend.calls == [
        (("lsjson", "mailru:/Hermes"), 60),
        (("lsjson", "mailru:/Hermes"), 60),
    ]
