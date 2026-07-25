"""Fake tests for policy-bounded rclone mkdir execution."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from hermes_mailcloud.commands.mkdir import MkdirCommand
from hermes_mailcloud.config import ResolvedConfig
from hermes_mailcloud.core.errors import ErrorKind, MailCloudError
from hermes_mailcloud.rclone.runner import RcloneResult


@dataclass
class RecordingBackend:
    calls: list[tuple[tuple[str, ...], float | None]] = field(default_factory=list)

    def require_success(
        self, args: Sequence[str], *, timeout_seconds: float | None = None
    ) -> RcloneResult:
        self.calls.append((tuple(args), timeout_seconds))
        return RcloneResult(0, "", "", 1)


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


def test_mkdir_executes_a_normalized_target_once_without_write_retries() -> None:
    backend = RecordingBackend()

    result = MkdirCommand(backend, _config(), timeout_seconds=9).run("/Hermes/private/./reports")

    assert result == {"remote_path": "/Hermes/private/reports", "created": True}
    assert backend.calls == [(("mkdir", "mailru:/Hermes/private/reports"), 9)]


def test_mkdir_dry_run_returns_a_plan_without_calling_the_backend() -> None:
    backend = RecordingBackend()

    result = MkdirCommand(backend, _config(), timeout_seconds=60).run(
        "/Hermes/private/reports", dry_run=True
    )

    assert result == {
        "remote_path": "/Hermes/private/reports",
        "dry_run": True,
        "plan": [
            {"step": "validate_arguments", "status": "planned"},
            {"step": "execute", "status": "planned"},
        ],
    }
    assert backend.calls == []


@pytest.mark.parametrize("remote_path", ["relative/path", "", "/Hermes/\x00reports"])
def test_mkdir_rejects_unsafe_remote_paths_before_backend_use(remote_path: str) -> None:
    backend = RecordingBackend()

    with pytest.raises(MailCloudError) as caught:
        MkdirCommand(backend, _config(), timeout_seconds=60).run(remote_path)

    assert caught.value.error.kind is ErrorKind.INVALID_ARGUMENTS
    assert backend.calls == []


def test_mkdir_requires_a_configured_remote_even_for_a_dry_run() -> None:
    backend = RecordingBackend()

    with pytest.raises(MailCloudError) as caught:
        MkdirCommand(backend, _config(remote=None), timeout_seconds=60).run(
            "/Hermes/private/reports", dry_run=True
        )

    assert caught.value.error.kind is ErrorKind.REMOTE_NOT_CONFIGURED
    assert backend.calls == []
